"""
report_gen.py — PDF Report Generator
Uses ReportLab to generate a professional downloadable PDF assessment report.
Falls back to a plain-text summary if ReportLab is unavailable.
"""

import os
import io
import json
from datetime import datetime

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, HRFlowable, PageBreak)
    REPORTLAB = True
except ImportError:
    REPORTLAB = False


# Colour palette
C_DARK    = colors.HexColor('#0f172a')
C_PRIMARY = colors.HexColor('#3b82f6')
C_GREEN   = colors.HexColor('#22c55e')
C_AMBER   = colors.HexColor('#f59e0b')
C_RED     = colors.HexColor('#ef4444')
C_LIGHT   = colors.HexColor('#f8fafc')
C_BORDER  = colors.HexColor('#e2e8f0')


def _score_color(score):
    if score <= 30:   return C_GREEN
    if score <= 65:   return C_AMBER
    return C_RED


def generate_pdf(assessment: dict, col_metrics: list,
                 breakdown: list, recommendations: list,
                 output_path: str) -> bool:
    if not REPORTLAB:
        _fallback_txt(assessment, output_path.replace('.pdf', '.txt'))
        return False

    doc  = SimpleDocTemplate(output_path, pagesize=A4,
                              leftMargin=2*cm, rightMargin=2*cm,
                              topMargin=2*cm, bottomMargin=2*cm)
    ss   = getSampleStyleSheet()
    story = []

    # ── Styles ────────────────────────────────────────────────
    title_s = ParagraphStyle('title_s', parent=ss['Title'],
                              fontSize=22, textColor=C_DARK,
                              spaceAfter=4, leading=28)
    sub_s   = ParagraphStyle('sub_s', parent=ss['Normal'],
                              fontSize=11, textColor=colors.HexColor('#64748b'),
                              spaceAfter=2)
    h2_s    = ParagraphStyle('h2_s', parent=ss['Heading2'],
                              fontSize=14, textColor=C_PRIMARY,
                              spaceBefore=14, spaceAfter=6)
    body_s  = ParagraphStyle('body_s', parent=ss['Normal'],
                              fontSize=9, leading=14,
                              textColor=C_DARK)
    small_s = ParagraphStyle('small_s', parent=ss['Normal'],
                              fontSize=8, leading=12,
                              textColor=colors.HexColor('#475569'))

    score  = float(assessment.get('debt_score', 0))
    cat    = assessment.get('debt_category', 'Low')
    cat_c  = _score_color(score)
    
    # Get duplicate count (use potential duplicates terminology)
    dup_rows = assessment.get('duplicate_rows', 0)

    # ── Cover ─────────────────────────────────────────────────
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph("Technical Debt Assessment Report", title_s))
    story.append(Paragraph(f"Dataset: <b>{assessment.get('assessment_name','—')}</b>", sub_s))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%B %d, %Y  %H:%M')}", sub_s))
    story.append(HRFlowable(width="100%", thickness=2, color=C_PRIMARY, spaceAfter=12))

    # Score summary table — FIX: cast to int to avoid 25.0 display
    total_rows_val = int(assessment.get('total_rows', 0))
    total_cols_val = int(assessment.get('total_columns', 0))
    dup_rows       = int(assessment.get('duplicate_rows', 0))

    summary_data = [
        ["Debt Score", "Category", "Total Rows", "Total Columns", "Potential Duplicates"],
        [
            Paragraph(f'<font size="16" color="{cat_c.hexval()}">'
                      f'<b>{score:.1f}</b></font><br/><font size="8" color="#64748b">/100</font>', body_s),
            Paragraph(f'<font color="{cat_c.hexval()}"><b>{cat}</b></font>', body_s),
            f"{total_rows_val:,}",
            str(total_cols_val),
            f"{dup_rows} ({(dup_rows / max(total_rows_val, 1) * 100):.1f}%)" if dup_rows > 0 else "0",
        ]
    ]
    t = Table(summary_data, colWidths=[3.5*cm, 3*cm, 3*cm, 3*cm, 4*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_DARK),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,0), 9),
        ('BACKGROUND', (0,1), (-1,1), C_LIGHT),
        ('ALIGN',      (0,0), (-1,-1), 'CENTER'),
        ('VALIGN',     (0,0), (-1,-1), 'MIDDLE'),
        ('ROWHEIGHT',  (0,1), (-1,1), 50),
        ('GRID',       (0,0), (-1,-1), 0.5, C_BORDER),
        ('ROUNDEDCORNERS', [4]),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.4*cm))

    # ── Debt Breakdown ────────────────────────────────────────
    story.append(Paragraph("Debt Category Breakdown", h2_s))
    bd_data = [["Category", "Score", "Weight", "Affected Cols"]]
    for b in breakdown:
        s = float(b.get('score', 0))
        bd_data.append([
            b.get('category', ''),
            Paragraph(f'<font color="{_score_color(s).hexval()}"><b>{s:.1f}</b></font>', body_s),
            f"{float(b.get('weight',0))*100:.0f}%",
            str(int(float(b.get('affected_columns', 0)))),
        ])
    t2 = Table(bd_data, colWidths=[8*cm, 3*cm, 3*cm, 3*cm])
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_DARK),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 9),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [C_LIGHT, colors.white]),
        ('ALIGN',      (1,0), (-1,-1), 'CENTER'),
        ('GRID',       (0,0), (-1,-1), 0.5, C_BORDER),
    ]))
    story.append(t2)

    # ── Per-Column Metrics ────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph("Per-Column Quality Metrics", h2_s))
    cm_data = [["Column", "Type", "Missing %", "Empty", "Invalid Fmt", "Outliers", "Debt Score"]]
    for m in col_metrics[:40]:
        s = float(m.get('column_debt_score', 0))
        cm_data.append([
            Paragraph(m.get('column_name',''), small_s),
            m.get('data_type',''),
            f"{m.get('missing_pct',0):.1f}%",
            str(int(float(m.get('empty_string_count', 0)))),
            str(int(float(m.get('invalid_format_count', 0)))),
            str(int(float(m.get('outlier_count', 0)))),
            Paragraph(f'<font color="{_score_color(s).hexval()}"><b>{s:.1f}</b></font>', small_s),
        ])
    t3 = Table(cm_data, colWidths=[5*cm, 2*cm, 2.2*cm, 1.8*cm, 2.2*cm, 1.8*cm, 2.2*cm])
    t3.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), C_DARK),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.white),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE',   (0,0), (-1,-1), 8),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [C_LIGHT, colors.white]),
        ('ALIGN',      (1,0), (-1,-1), 'CENTER'),
        ('GRID',       (0,0), (-1,-1), 0.5, C_BORDER),
    ]))
    story.append(t3)

    # ── Recommendations (Fixed - no duplicate text) ─────────────────
    story.append(PageBreak())
    story.append(Paragraph("Recommendations", h2_s))
    priority_order = ["Critical", "High", "Medium", "Low"]
    for pri in priority_order:
        items = [r for r in recommendations if r.get('priority') == pri]
        if not items:
            continue
        pri_c = {"Critical": "#ef4444", "High": "#f97316",
                  "Medium": "#f59e0b", "Low": "#22c55e"}.get(pri, "#64748b")
        story.append(Paragraph(
            f'<font color="{pri_c}">● {pri} Priority</font>', h2_s))
        for rec in items:
            # Fixed: Only show title once (not duplicated)
            story.append(Paragraph(f"<b>{rec.get('title','')}</b>", body_s))
            # Description is separate, not duplicate of title
            story.append(Paragraph(rec.get('description',''), small_s))
            meta = (f"Category: {rec.get('category','—')}  |  "
                    f"Effort: {rec.get('effort','—')}  |  "
                    f"Impact: {rec.get('impact','—')}")
            story.append(Paragraph(f'<font color="#94a3b8"><i>{meta}</i></font>', small_s))
            story.append(Spacer(1, 0.3*cm))

    doc.build(story)
    return True


def _fallback_txt(assessment, path):
    lines = [
        "TECHNICAL DEBT ASSESSMENT REPORT",
        "=" * 50,
        f"Dataset : {assessment.get('assessment_name','—')}",
        f"Score   : {assessment.get('debt_score',0):.1f} / 100",
        f"Category: {assessment.get('debt_category','—')}",
        f"Rows    : {assessment.get('total_rows',0):,}",
        f"Columns : {assessment.get('total_columns',0)}",
        f"Potential Duplicates: {assessment.get('duplicate_rows',0)}",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]
    with open(path, 'w') as f:
        f.write('\n'.join(lines))