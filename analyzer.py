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


def _is_email_col(col: str) -> bool:
    keywords = ['email', 'mail', 'e-mail', 'e_mail']
    return any(k in col.lower() for k in keywords)

def _is_phone_col(col: str) -> bool:
    keywords = ['phone', 'mobile', 'cell', 'tel', 'contact']
    return any(k in col.lower() for k in keywords)

def _is_date_col(col: str) -> bool:
    keywords = ['date', 'time', 'dob', 'created', 'updated', 'timestamp', 'dt']
    return any(k in col.lower() for k in keywords)


def _analyse_column(series: pd.Series, col_name: str, total_rows: int) -> dict:
    non_null = series.dropna()
    missing_count  = int(series.isna().sum())
    missing_pct    = round((missing_count / total_rows) * 100, 2) if total_rows else 0

    str_series     = non_null.astype(str)
    empty_count    = int((str_series.str.strip() == '').sum())
    unique_count   = int(series.nunique())
    duplicate_count = 0

    invalid_format = 0
    if _is_email_col(col_name):
        invalid_format = int(str_series.apply(lambda v: not EMAIL_PATTERN.match(v.strip()) if v.strip() else False).sum())
    elif _is_phone_col(col_name):
        invalid_format = int(str_series.apply(lambda v: not PHONE_PATTERN.match(v.strip()) if v.strip() else False).sum())
    elif _is_date_col(col_name):
        def bad_date(v):
            v = v.strip()
            if not v:
                return False
            return not any(re.match(p, v) for p in DATE_PATTERNS)
        if pd.api.types.is_object_dtype(series):
            invalid_format = int(str_series.apply(bad_date).sum())
    else:
        if pd.api.types.is_numeric_dtype(series):
            invalid_format = int(series.isna().sum() - missing_count)

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
        lower_vals = str_series.str.lower().nunique()
        actual_vals = str_series.nunique()
        if lower_vals < actual_vals:
            case_inconsistency = int(actual_vals - lower_vals)

    # Column-level debt score (0-100)
    score = 0
    n = total_rows or 1
    score += min(40, (missing_count / n) * 100)
    score += min(20, (empty_count / n) * 100)
    score += min(20, (invalid_format / n) * 100)
    score += min(10, (outlier_count / n) * 100)
    score += min(10, (case_inconsistency / n) * 100)

    return {
        "column_name":         col_name,
        "data_type":           str(series.dtype),
        "total_values":        total_rows,
        "missing_count":       missing_count,
        "missing_pct":         missing_pct,
        "duplicate_count":     duplicate_count,
        "empty_string_count":  empty_count,
        "invalid_format_count":invalid_format,
        "unique_count":        unique_count,
        "min_value":           str(min_val) if min_val is not None else None,
        "max_value":           str(max_val) if max_val is not None else None,
        "mean_value":          round(mean_val, 4) if mean_val is not None else None,
        "std_dev":             round(std_val, 4) if std_val is not None else None,
        "outlier_count":       outlier_count,
        "case_inconsistency":  case_inconsistency,
        "column_debt_score":   round(min(100, score), 2),
    }


def _identify_business_columns(df: pd.DataFrame) -> list:
    """Identify columns that should be used for business key duplicate detection"""
    exclude_patterns = ['id', 'ID', 'Id', 'customer_id', 'user_id', 'employee_id', 
                       'transaction_id', 'order_id', 'product_id', 'uuid', 'guid',
                       'created_at', 'updated_at', 'timestamp', 'created_date']
    
    business_columns = []
    for col in df.columns:
        is_excluded = False
        for pattern in exclude_patterns:
            if pattern in col.lower():
                is_excluded = True
                break
        if not is_excluded:
            business_columns.append(col)
    
    # If all columns were excluded, use all columns
    if len(business_columns) == 0:
        business_columns = list(df.columns)
    
    return business_columns


def _compute_category_scores(df: pd.DataFrame, col_metrics: list, total_rows: int, 
                              exact_duplicates: int, potential_duplicates: int) -> dict:
    n = total_rows or 1
    total_cells = n * len(df.columns) or 1

    total_missing = sum(m["missing_count"] for m in col_metrics)
    total_empty   = sum(m["empty_string_count"] for m in col_metrics)
    total_invalid = sum(m["invalid_format_count"] for m in col_metrics)
    total_outlier = sum(m["outlier_count"] for m in col_metrics)

    # Use potential duplicates for scoring
    dup_rows = potential_duplicates if potential_duplicates > 0 else exact_duplicates
    
    # Calculate percentages directly (0-100 scale)
    missing_pct = min(100, (total_missing / total_cells) * 100)
    duplicate_pct = min(100, (dup_rows / n) * 100)
    empty_pct = min(100, (total_empty / total_cells) * 100)
    invalid_pct = min(100, (total_invalid / total_cells) * 100)
    
    # Inconsistency calculation
    incon_count = sum(m.get("case_inconsistency", 0) for m in col_metrics)
    inconsistent_pct = min(100, (incon_count / total_cells) * 100)

    scores = {
        "missing_values":    round(missing_pct, 2),
        "duplicates":        round(duplicate_pct, 2),
        "empty_fields":      round(empty_pct, 2),
        "invalid_formats":   round(invalid_pct, 2),
        "inconsistent_data": round(inconsistent_pct, 2),
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


def _generate_recommendations(col_metrics, category_scores, exact_duplicates, 
                               potential_duplicates, total_rows) -> list:
    recs = []
    n = total_rows or 1

    # Missing values
    high_missing = [m for m in col_metrics if m["missing_pct"] >= 30]
    mod_missing  = [m for m in col_metrics if 5 <= m["missing_pct"] < 30]
    if high_missing:
        cols = ", ".join(c["column_name"] for c in high_missing[:5])
        recs.append({
            "priority": "Critical", "category": "Missing Values",
            "title": f"Impute or drop columns with >30% missing data",
            "description": f"Columns {cols} have critical missing data (≥30%). "
                           "Consider imputation strategies (mean/median/mode/ML-based) "
                           "or evaluate whether these columns should be dropped entirely.",
            "effort": "Medium Effort", "impact": "High",
            "column_ref": cols
        })
    if mod_missing:
        cols = ", ".join(c["column_name"] for c in mod_missing[:5])
        recs.append({
            "priority": "High", "category": "Missing Values",
            "title": "Address moderate missing values with imputation",
            "description": f"Columns {cols} have 5–30% missing values. "
                           "Apply domain-appropriate imputation and document the strategy.",
            "effort": "Medium Effort", "impact": "High",
            "column_ref": cols
        })

    # Duplicates - Enhanced recommendation
    total_dup_issues = exact_duplicates + potential_duplicates
    dup_pct = (total_dup_issues / n) * 100 if n > 0 else 0
    
    if dup_pct >= 5:
        rec_text = f"Found {exact_duplicates} exact duplicate(s) and {potential_duplicates} potential duplicate(s)"
        if potential_duplicates > 0 and exact_duplicates == 0:
            rec_text = f"Found {potential_duplicates} potential duplicate(s) with different IDs but same business data"
        
        recs.append({
            "priority": "Critical" if dup_pct >= 20 else "High",
            "category": "Duplicates",
            "title": f"Remove {total_dup_issues} duplicate rows ({dup_pct:.1f}% of dataset)",
            "description": f"{rec_text}. Duplicate records inflate counts, skew aggregations, and degrade ML model quality. "
                           "Implement deduplication at ingestion using composite business keys.",
            "effort": "Quick Win", "impact": "High",
            "column_ref": "Dataset-wide"
        })

    # Invalid formats
    bad_fmt_cols = [m for m in col_metrics if m["invalid_format_count"] > 0]
    for m in bad_fmt_cols[:4]:
        recs.append({
            "priority": "High", "category": "Invalid Formats",
            "title": f"Standardise format in column '{m['column_name']}'",
            "description": f"{m['invalid_format_count']} values in '{m['column_name']}' fail format validation. "
                           "Enforce schema-level constraints and add validation at data entry points.",
            "effort": "Medium Effort", "impact": "Medium",
            "column_ref": m["column_name"]
        })

    # Outliers
    outlier_cols = [m for m in col_metrics if m["outlier_count"] > 0]
    if outlier_cols:
        cols = ", ".join(c["column_name"] for c in outlier_cols[:4])
        recs.append({
            "priority": "Medium", "category": "Inconsistent Data",
            "title": "Investigate statistical outliers",
            "description": f"Columns {cols} contain statistical outliers (|Z-score| > 3). "
                           "Validate whether these represent data entry errors or genuine extremes.",
            "effort": "Medium Effort", "impact": "Medium",
            "column_ref": cols
        })

    # Case inconsistency
    case_cols = [m for m in col_metrics if m.get("case_inconsistency", 0) > 0]
    if case_cols:
        cols = ", ".join(c["column_name"] for c in case_cols[:4])
        recs.append({
            "priority": "Medium", "category": "Inconsistent Data",
            "title": "Normalise text casing in categorical columns",
            "description": f"Columns {cols} have mixed letter-case values (e.g. 'New York' vs 'new york'). "
                           "Apply a consistent normalisation strategy (e.g. title-case or lower-case).",
            "effort": "Quick Win", "impact": "Medium",
            "column_ref": cols
        })

    # General governance
    recs.append({
        "priority": "Low", "category": "Governance",
        "title": "Implement a Data Quality Monitoring Pipeline",
        "description": "Schedule automated quality checks (Great Expectations / dbt tests) "
                       "on every ingestion to catch regressions early. "
                       "Define SLA thresholds per column and alert on breach.",
        "effort": "Long Term", "impact": "High",
        "column_ref": "Dataset-wide"
    })
    recs.append({
        "priority": "Low", "category": "Governance",
        "title": "Establish a Data Dictionary and Ownership Matrix",
        "description": "Document each column's business meaning, expected format, and data owner. "
                       "Link to master reference data where applicable.",
        "effort": "Long Term", "impact": "Medium",
        "column_ref": "Dataset-wide"
    })

    return recs


def analyse(df: pd.DataFrame) -> dict:
    """
    Main entry point.
    Returns a dict with keys:
        total_rows, total_columns, col_metrics, category_scores,
        exact_duplicates, potential_duplicates, debt_score, debt_category, recommendations
    """
    total_rows = len(df)
    total_cols = len(df.columns)
    
    # ⭐ DUAL DUPLICATE DETECTION ⭐
    
    # 1. EXACT DUPLICATES - All columns must match exactly (including IDs)
    exact_duplicates = int(df.duplicated().sum())
    
    # 2. POTENTIAL DUPLICATES - Ignore ID/business keys, compare only business columns
    business_columns = _identify_business_columns(df)
    df_business = df[business_columns]
    potential_duplicates = int(df_business.duplicated().sum())
    

    col_metrics = [_analyse_column(df[col], col, total_rows) for col in df.columns]
    category_scores, dup_rows = _compute_category_scores(df, col_metrics, total_rows, 
                                                          exact_duplicates, potential_duplicates)
    debt_score   = _overall_score(category_scores)
    debt_category = _categorise(debt_score)
    recommendations = _generate_recommendations(col_metrics, category_scores, 
                                                  exact_duplicates, potential_duplicates, total_rows)

    # Debt breakdown list for DB storage
    breakdown = []
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
        "inconsistent_data": sum(1 for m in col_metrics if m.get("case_inconsistency", 0) > 0),
    }
    for key, label in labels.items():
        breakdown.append({
            "category":         label,
            "score":            category_scores[key],
            "weight":           WEIGHTS[key],
            "affected_columns": affected[key],
        })

    # Sample data (first 20 rows)
    sample_df   = df.head(20).fillna("").astype(str)
    sample_data = sample_df.to_dict(orient="records")

    return {
        "total_rows":           total_rows,
        "total_columns":        total_cols,
        "col_metrics":          col_metrics,
        "category_scores":      category_scores,
        "exact_duplicates":     exact_duplicates,
        "potential_duplicates": potential_duplicates,
        "dup_rows":             potential_duplicates,  # For backward compatibility
        "debt_score":           debt_score,
        "debt_category":        debt_category,
        "breakdown":            breakdown,
        "recommendations":      recommendations,
        "sample_data":          sample_data,
        "column_headers":       list(df.columns),
    }