"""
analyzer.py — Data Quality & Technical Debt Analysis Engine
============================================================
Analyses a pandas DataFrame and returns a structured result dict
containing per-column metrics, debt category scores, an overall
debt score (0-100, higher = more debt), and recommendations.
"""

import re
import math
import pandas as pd
import numpy as np
from datetime import datetime


# ─── Weight configuration (must sum to 1.0) ─────────────────
WEIGHTS = {
    "missing_values":    0.28,
    "duplicates":        0.20,
    "empty_fields":      0.15,
    "invalid_formats":   0.17,
    "inconsistent_data": 0.20,
}

# Common date patterns
DATE_PATTERNS = [
    r'^\d{4}-\d{2}-\d{2}$',
    r'^\d{2}/\d{2}/\d{4}$',
    r'^\d{2}-\d{2}-\d{4}$',
    r'^\d{4}/\d{2}/\d{2}$',
]

EMAIL_PATTERN = re.compile(r'^[\w\.\+\-]+@[\w\-]+\.[a-zA-Z]{2,}$')
PHONE_PATTERN = re.compile(r'^[\+\d\s\-\(\)]{7,20}$')


def _clean_dtype(dtype_str: str) -> str:
    """Convert pandas dtype to a human-readable label."""
    s = str(dtype_str).lower()
    if 'datetime' in s:
        return 'datetime'
    if 'int' in s:
        return 'integer'
    if 'float' in s:
        return 'decimal'
    if 'bool' in s:
        return 'boolean'
    if 'object' in s or 'string' in s:
        return 'text'
    return s


def _is_email_col(col: str) -> bool:
    return any(k in col.lower() for k in ['email', 'mail', 'e-mail', 'e_mail'])

def _is_phone_col(col: str) -> bool:
    return any(k in col.lower() for k in ['phone', 'mobile', 'cell', 'tel', 'contact'])

def _is_date_col(col: str) -> bool:
    return any(k in col.lower() for k in ['date', 'time', 'dob', 'created', 'updated', 'timestamp', 'dt'])


def _analyse_column(series: pd.Series, col_name: str, total_rows: int) -> dict:
    non_null = series.dropna()
    missing_count = int(series.isna().sum())
    missing_pct   = round((missing_count / total_rows) * 100, 2) if total_rows else 0

    str_series  = non_null.astype(str)
    empty_count = int((str_series.str.strip() == '').sum())
    unique_count = int(series.nunique())

    invalid_format = 0
    if _is_email_col(col_name):
        invalid_format = int(str_series.apply(
            lambda v: not EMAIL_PATTERN.match(v.strip()) if v.strip() else False).sum())
    elif _is_phone_col(col_name):
        invalid_format = int(str_series.apply(
            lambda v: not PHONE_PATTERN.match(v.strip()) if v.strip() else False).sum())
    elif _is_date_col(col_name) and pd.api.types.is_object_dtype(series):
        def bad_date(v):
            v = v.strip()
            if not v:
                return False
            return not any(re.match(p, v) for p in DATE_PATTERNS)
        invalid_format = int(str_series.apply(bad_date).sum())

    # Outlier detection for numeric columns
    outlier_count = 0
    mean_val = std_val = min_val = max_val = None
    if pd.api.types.is_numeric_dtype(series) and len(non_null) > 4:
        mean_val = float(non_null.mean())
        std_val  = float(non_null.std())
        min_val  = float(non_null.min())
        max_val  = float(non_null.max())
        if std_val > 0:
            z_scores = np.abs((non_null - mean_val) / std_val)
            outlier_count = int((z_scores > 3).sum())

    # Case inconsistency for string columns
    case_inconsistency = 0
    if pd.api.types.is_object_dtype(series) and len(non_null) > 5:
        lower_vals  = str_series.str.lower().nunique()
        actual_vals = str_series.nunique()
        if lower_vals < actual_vals:
            case_inconsistency = int(actual_vals - lower_vals)

    # Column-level debt score (0-100)
    # FIX: Use amplified scale so small issues still register meaningfully
    n = total_rows or 1
    score = 0
    score += min(40, (missing_count / n) * 100 * 2)      # amplified
    score += min(20, (empty_count / n) * 100 * 2)
    score += min(20, (invalid_format / n) * 100 * 2)
    score += min(15, (outlier_count / n) * 100 * 5)       # outliers weighted higher
    score += min(10, (case_inconsistency / n) * 100 * 2)

    return {
        "column_name":          col_name,
        "data_type":            _clean_dtype(series.dtype),   # FIX: human-readable
        "total_values":         total_rows,
        "missing_count":        missing_count,
        "missing_pct":          missing_pct,
        "duplicate_count":      0,
        "empty_string_count":   empty_count,
        "invalid_format_count": invalid_format,
        "unique_count":         unique_count,
        "min_value":            str(min_val) if min_val is not None else None,
        "max_value":            str(max_val) if max_val is not None else None,
        "mean_value":           round(mean_val, 4) if mean_val is not None else None,
        "std_dev":              round(std_val, 4) if std_val is not None else None,
        "outlier_count":        outlier_count,
        "case_inconsistency":   case_inconsistency,
        "column_debt_score":    round(min(100, score), 2),
    }


def _identify_business_columns(df: pd.DataFrame) -> list:
    exclude_patterns = ['id', 'uuid', 'guid', 'created_at', 'updated_at',
                        'timestamp', 'created_date']
    business_columns = [
        col for col in df.columns
        if not any(p in col.lower() for p in exclude_patterns)
    ]
    return business_columns if business_columns else list(df.columns)


def _compute_category_scores(df, col_metrics, total_rows,
                              exact_duplicates, potential_duplicates):
    n          = total_rows or 1
    total_cells = n * len(df.columns) or 1

    total_missing = sum(m["missing_count"]        for m in col_metrics)
    total_empty   = sum(m["empty_string_count"]   for m in col_metrics)
    total_invalid = sum(m["invalid_format_count"] for m in col_metrics)
    total_outlier = sum(m["outlier_count"]         for m in col_metrics)  # FIX: include outliers

    dup_rows = potential_duplicates if potential_duplicates > 0 else exact_duplicates

    # Case inconsistency + outliers both feed into inconsistent_data
    # FIX: outliers now contribute to inconsistent_data score
    incon_count = sum(m.get("case_inconsistency", 0) for m in col_metrics)

    # FIX: amplified multipliers so small issues register meaningfully
    scores = {
        "missing_values":    round(min(100, (total_missing / total_cells) * 100 * 3), 2),
        "duplicates":        round(min(100, (dup_rows / n) * 100 * 4), 2),
        "empty_fields":      round(min(100, (total_empty / total_cells) * 100 * 3), 2),
        "invalid_formats":   round(min(100, (total_invalid / total_cells) * 100 * 4), 2),
        # FIX: inconsistent_data now includes both case mismatches AND outliers
        "inconsistent_data": round(min(100, (
            (incon_count / total_cells) * 100 * 4 +
            (total_outlier / total_cells) * 100 * 6   # outliers weighted heavily
        )), 2),
    }
    return scores, dup_rows


def _overall_score(category_scores: dict) -> float:
    score = sum(category_scores[k] * WEIGHTS[k] for k in WEIGHTS)
    return round(min(100, score), 2)


def _categorise(score: float) -> str:
    if score <= 30:
        return "Low"
    elif score <= 65:
        return "Medium"
    return "High"


def _generate_recommendations(col_metrics, category_scores,
                               exact_duplicates, potential_duplicates,
                               total_rows) -> list:
    recs = []
    n = total_rows or 1

    # ── Missing values ───────────────────────────────────────
    high_missing = [m for m in col_metrics if m["missing_pct"] >= 30]
    mod_missing  = [m for m in col_metrics if 5 <= m["missing_pct"] < 30]

    if high_missing:
        cols = ", ".join(c["column_name"] for c in high_missing[:5])
        recs.append({
            "priority": "Critical", "category": "Missing Values",
            "title": "Impute or drop columns with >30% missing data",
            "description": (f"Columns {cols} have critical missing data (≥30%). "
                            "Consider imputation strategies (mean/median/mode/ML-based) "
                            "or evaluate whether these columns should be dropped entirely."),
            "effort": "Medium Effort", "impact": "High",
            "column_ref": cols
        })
    if mod_missing:
        cols = ", ".join(c["column_name"] for c in mod_missing[:5])
        recs.append({
            "priority": "High", "category": "Missing Values",
            "title": "Address moderate missing values with imputation",
            "description": (f"Columns {cols} have 5–30% missing values. "
                            "Apply domain-appropriate imputation and document the strategy."),
            "effort": "Medium Effort", "impact": "High",
            "column_ref": cols
        })

    # ── Duplicates ───────────────────────────────────────────
    total_dup = exact_duplicates + potential_duplicates
    dup_pct   = (total_dup / n) * 100 if n > 0 else 0
    if dup_pct >= 1:                         # FIX: lower threshold — even 1% matters
        recs.append({
            "priority": "Critical" if dup_pct >= 20 else "High",
            "category": "Duplicates",
            "title": f"Remove {total_dup} duplicate rows ({dup_pct:.1f}% of dataset)",
            "description": (f"Found {exact_duplicates} exact and {potential_duplicates} "
                            "potential duplicate(s). Duplicate records inflate counts, "
                            "skew aggregations, and degrade model quality. "
                            "Implement deduplication at ingestion using composite business keys."),
            "effort": "Quick Win", "impact": "High",
            "column_ref": "Dataset-wide"
        })

    # ── Invalid formats ──────────────────────────────────────
    bad_fmt_cols = [m for m in col_metrics if m["invalid_format_count"] > 0]
    for m in bad_fmt_cols[:4]:
        recs.append({
            "priority": "High", "category": "Invalid Formats",
            "title": f"Standardise format in column '{m['column_name']}'",
            "description": (f"{m['invalid_format_count']} values in '{m['column_name']}' "
                            "fail format validation. Enforce schema-level constraints and "
                            "add validation at data entry points."),
            "effort": "Medium Effort", "impact": "Medium",
            "column_ref": m["column_name"]
        })

    # ── Outliers — FIX: now tied to inconsistent_data score ──
    outlier_cols = [m for m in col_metrics if m["outlier_count"] > 0]
    if outlier_cols:
        cols = ", ".join(c["column_name"] for c in outlier_cols[:4])
        total_out = sum(m["outlier_count"] for m in outlier_cols)
        recs.append({
            "priority": "High" if category_scores["inconsistent_data"] > 10 else "Medium",
            "category": "Inconsistent Data",
            "title": f"Investigate {total_out} statistical outlier(s) in numeric columns",
            "description": (f"Columns {cols} contain values with |Z-score| > 3, indicating "
                            "statistical outliers. These directly contribute to the Inconsistent "
                            "Data score. Validate whether they represent data entry errors or "
                            "genuine extremes and apply capping or removal as needed."),
            "effort": "Medium Effort", "impact": "High",
            "column_ref": cols
        })

    # ── Case inconsistency ───────────────────────────────────
    case_cols = [m for m in col_metrics if m.get("case_inconsistency", 0) > 0]
    if case_cols:
        cols = ", ".join(c["column_name"] for c in case_cols[:4])
        recs.append({
            "priority": "Medium", "category": "Inconsistent Data",
            "title": "Normalise text casing in categorical columns",
            "description": (f"Columns {cols} have mixed letter-case values "
                            "(e.g. 'New York' vs 'new york'). "
                            "Apply a consistent normalisation strategy (title-case or lower-case)."),
            "effort": "Quick Win", "impact": "Medium",
            "column_ref": cols
        })

    # ── Governance — FIX: only appear when actual issues exist ──
    has_owner_col = any('owner' in m['column_name'].lower() for m in col_metrics)
    owner_missing = any(
        'owner' in m['column_name'].lower() and m['missing_pct'] > 0
        for m in col_metrics
    )
    has_quality_issues = (
        category_scores["missing_values"] > 5 or
        category_scores["inconsistent_data"] > 5 or
        category_scores["duplicates"] > 5
    )

    if has_quality_issues:
        recs.append({
            "priority": "Low", "category": "Governance",
            "title": "Implement a Data Quality Monitoring Pipeline",
            "description": ("This dataset shows quality issues that would benefit from "
                            "automated monitoring. Schedule quality checks (Great Expectations / "
                            "dbt tests) on every ingestion to catch regressions early. "
                            "Define SLA thresholds per column and alert on breach."),
            "effort": "Long Term", "impact": "High",
            "column_ref": "Dataset-wide"
        })

    if has_owner_col and owner_missing:
        recs.append({
            "priority": "Low", "category": "Governance",
            "title": "Complete the Data Ownership Matrix",
            "description": ("The dataset contains a data ownership column with missing values. "
                            "Ensure every data asset has an assigned owner responsible for "
                            "quality, access control, and lifecycle management."),
            "effort": "Medium Effort", "impact": "Medium",
            "column_ref": "Data_Owner"
        })
    elif not has_owner_col:
        recs.append({
            "priority": "Low", "category": "Governance",
            "title": "Establish a Data Dictionary and Ownership Matrix",
            "description": ("No data ownership column was detected. Document each column's "
                            "business meaning, expected format, and assign a data owner. "
                            "Link to master reference data where applicable."),
            "effort": "Long Term", "impact": "Medium",
            "column_ref": "Dataset-wide"
        })

    return recs


def analyse(df: pd.DataFrame) -> dict:
    """
    Main entry point.
    Returns a structured result dict with all quality metrics,
    scores, breakdown, recommendations and sample data.
    """
    total_rows = len(df)
    total_cols = len(df.columns)

    # Exact duplicates — all columns match
    exact_duplicates = int(df.duplicated().sum())

    # Potential duplicates — business columns only (excludes IDs)
    business_columns   = _identify_business_columns(df)
    potential_duplicates = int(df[business_columns].duplicated().sum())

    col_metrics = [_analyse_column(df[col], col, total_rows) for col in df.columns]
    category_scores, dup_rows = _compute_category_scores(
        df, col_metrics, total_rows, exact_duplicates, potential_duplicates)

    debt_score    = _overall_score(category_scores)
    debt_category = _categorise(debt_score)
    recommendations = _generate_recommendations(
        col_metrics, category_scores,
        exact_duplicates, potential_duplicates, total_rows)

    # Breakdown for DB + charts
    labels = {
        "missing_values":    "Missing Values",
        "duplicates":        "Duplicate Records",
        "empty_fields":      "Empty / Blank Fields",
        "invalid_formats":   "Invalid Formats",
        "inconsistent_data": "Inconsistent Data",
    }
    affected = {
        "missing_values":    sum(1 for m in col_metrics if m["missing_count"] > 0),
        "duplicates":        1 if (exact_duplicates + potential_duplicates) > 0 else 0,
        "empty_fields":      sum(1 for m in col_metrics if m["empty_string_count"] > 0),
        "invalid_formats":   sum(1 for m in col_metrics if m["invalid_format_count"] > 0),
        # FIX: outliers also count toward affected columns for inconsistent_data
        "inconsistent_data": sum(1 for m in col_metrics
                                 if m.get("case_inconsistency", 0) > 0
                                 or m.get("outlier_count", 0) > 0),
    }
    breakdown = [
        {
            "category":         labels[key],
            "score":            category_scores[key],
            "weight":           WEIGHTS[key],
            "affected_columns": affected[key],
        }
        for key in labels
    ]

    sample_df   = df.head(20).fillna("").astype(str)
    sample_data = sample_df.to_dict(orient="records")

    return {
        "total_rows":           total_rows,
        "total_columns":        total_cols,
        "col_metrics":          col_metrics,
        "category_scores":      category_scores,
        "exact_duplicates":     exact_duplicates,
        "potential_duplicates": potential_duplicates,
        "dup_rows":             potential_duplicates,
        "debt_score":           debt_score,
        "debt_category":        debt_category,
        "breakdown":            breakdown,
        "recommendations":      recommendations,
        "sample_data":          sample_data,
        "column_headers":       list(df.columns),
    }