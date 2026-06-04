"""
app.py — Flask Application Entry Point
CDO Technical Debt Assessment Tool
"""

import os
import json
import uuid
import traceback
from datetime import datetime
from werkzeug.utils import secure_filename

import pandas as pd
from flask import (Flask, render_template, request, jsonify,
                   redirect, url_for, send_from_directory, flash, abort)

from config   import Config
from analyzer import analyse
import db
import report_gen

app = Flask(__name__)
app.config.from_object(Config)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['REPORTS_FOLDER'], exist_ok=True)


# ─── Utilities ──────────────────────────────────────────────

def allowed_file(filename):
    return ('.' in filename and
            filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS'])


def load_dataframe(filepath: str) -> pd.DataFrame:
    ext = filepath.rsplit('.', 1)[1].lower()
    if ext == 'csv':
        try:
            return pd.read_csv(filepath, encoding='utf-8')
        except UnicodeDecodeError:
            return pd.read_csv(filepath, encoding='latin-1')
    else:
        return pd.read_excel(filepath)


# ─── Page Routes ────────────────────────────────────────────

@app.route('/')
def index():
    """Landing / upload page."""
    return render_template('index.html')


@app.route('/dashboard/<int:assessment_id>')
def dashboard(assessment_id):
    """Main results dashboard for a specific assessment."""
    assessment = db.fetchone(
        "SELECT * FROM assessments WHERE id = %s", (assessment_id,))
    if not assessment:
        abort(404)
    return render_template('dashboard.html', assessment=assessment)


@app.route('/history')
def history():
    """Assessment history & trends page."""
    return render_template('history.html')


@app.route('/report/<int:assessment_id>')
def report_page(assessment_id):
    """Detailed report page."""
    assessment = db.fetchone(
        "SELECT * FROM assessments WHERE id = %s", (assessment_id,))
    if not assessment:
        abort(404)
    return render_template('report.html', assessment=assessment)


# ─── API Routes ─────────────────────────────────────────────

@app.route('/api/upload', methods=['POST'])
def api_upload():
    """
    POST /api/upload
    Accepts multipart/form-data with:
        file           — CSV / XLSX / XLS
        assessment_name — (optional) human label
    Returns JSON with assessment_id on success.
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file part in request"}), 400

    f = request.files['file']
    if not f or f.filename == '':
        return jsonify({"error": "No file selected"}), 400

    if not allowed_file(f.filename):
        return jsonify({"error": "Only CSV, XLSX, and XLS files are supported"}), 400

    original_name = secure_filename(f.filename)
    ext           = original_name.rsplit('.', 1)[1].lower()
    unique_name   = f"{uuid.uuid4().hex}.{ext}"
    save_path     = os.path.join(app.config['UPLOAD_FOLDER'], unique_name)
    f.save(save_path)

    file_size     = os.path.getsize(save_path)
    assess_name   = (request.form.get('assessment_name') or
                     original_name.rsplit('.', 1)[0])

    # Create a pending record
    assessment_id = db.execute(
        """INSERT INTO assessments
           (assessment_name, filename, original_filename, file_size, file_type, status)
           VALUES (%s, %s, %s, %s, %s, 'processing')""",
        (assess_name, unique_name, original_name, file_size, ext)
    )

    # Run analysis
    try:
        df     = load_dataframe(save_path)
        result = analyse(df)

        # Update master record with both duplicate types
        # Note: duplicate_rows column stores potential_duplicates (business duplicates)
        db.execute(
            """UPDATE assessments
               SET total_rows=%s, total_columns=%s, duplicate_rows=%s, debt_score=%s,
                   debt_category=%s, status='completed'
               WHERE id=%s""",
            (result['total_rows'], result['total_columns'], result['potential_duplicates'],
             result['debt_score'], result['debt_category'], assessment_id)
        )

        # Insert column metrics
        cm_rows = [(
            assessment_id,
            m['column_name'], m['data_type'], m['total_values'],
            m['missing_count'], m['missing_pct'], m['duplicate_count'],
            m['empty_string_count'], m['invalid_format_count'],
            m['unique_count'],
            m.get('min_value'), m.get('max_value'),
            m.get('mean_value'), m.get('std_dev'),
            m['outlier_count'], m['column_debt_score']
        ) for m in result['col_metrics']]

        db.execute_many(
            """INSERT INTO quality_metrics
               (assessment_id, column_name, data_type, total_values,
                missing_count, missing_pct, duplicate_count,
                empty_string_count, invalid_format_count,
                unique_count, min_value, max_value,
                mean_value, std_dev, outlier_count, column_debt_score)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            cm_rows
        )

        # Insert breakdown
        bd_rows = [(
            assessment_id,
            b['category'], b['score'], b['weight'], b['affected_columns']
        ) for b in result['breakdown']]
        db.execute_many(
            """INSERT INTO debt_breakdown
               (assessment_id, category, score, weight, affected_columns)
               VALUES (%s,%s,%s,%s,%s)""",
            bd_rows
        )

        # Insert recommendations
        rec_rows = [(
            assessment_id,
            r['priority'], r['category'], r['title'],
            r['description'], r['effort'], r['impact'],
            r.get('column_ref', '')
        ) for r in result['recommendations']]
        db.execute_many(
            """INSERT INTO recommendations
               (assessment_id, priority, category, title,
                description, effort, impact, column_ref)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            rec_rows
        )

        # Insert sample
        db.execute(
            """INSERT INTO dataset_samples (assessment_id, sample_data, column_headers)
               VALUES (%s, %s, %s)""",
            (assessment_id,
             json.dumps(result['sample_data']),
             json.dumps(result['column_headers']))
        )

        return jsonify({
            "success": True,
            "assessment_id": assessment_id,
            "debt_score":    result['debt_score'],
            "debt_category": result['debt_category'],
            "exact_duplicates": result['exact_duplicates'],
            "potential_duplicates": result['potential_duplicates'],
        })

    except Exception as e:
        traceback.print_exc()
        db.execute(
            "UPDATE assessments SET status='failed' WHERE id=%s",
            (assessment_id,)
        )
        return jsonify({"error": str(e)}), 500


@app.route('/api/assessment/<int:assessment_id>')
def api_assessment(assessment_id):
    """Full assessment detail for dashboard rendering."""
    a = db.fetchone("SELECT * FROM assessments WHERE id=%s", (assessment_id,))
    if not a:
        return jsonify({"error": "Not found"}), 404

    col_metrics     = db.fetchall(
        "SELECT * FROM quality_metrics WHERE assessment_id=%s ORDER BY column_debt_score DESC",
        (assessment_id,))
    breakdown       = db.fetchall(
        "SELECT * FROM debt_breakdown WHERE assessment_id=%s", (assessment_id,))
    recommendations = db.fetchall(
        """SELECT * FROM recommendations WHERE assessment_id=%s
           ORDER BY FIELD(priority,'Critical','High','Medium','Low')""",
        (assessment_id,))
    sample          = db.fetchone(
        "SELECT * FROM dataset_samples WHERE assessment_id=%s", (assessment_id,))

    # Create a copy with dup_rows from the assessments table
    assessment_dict = _serial(a)
    # duplicate_rows is now stored in the assessments table

    return jsonify({
        "assessment":       assessment_dict,
        "col_metrics":      [_serial(m) for m in col_metrics],
        "breakdown":        [_serial(b) for b in breakdown],
        "recommendations":  [_serial(r) for r in recommendations],
        "sample_data":      json.loads(sample['sample_data'])    if sample else [],
        "column_headers":   json.loads(sample['column_headers']) if sample else [],
    })


@app.route('/api/history')
def api_history():
    """Paginated list for history page + trend data."""
    page     = max(1, int(request.args.get('page', 1)))
    per_page = 12
    offset   = (page - 1) * per_page

    rows = db.fetchall(
        """SELECT id, assessment_name, original_filename, debt_score,
                  debt_category, total_rows, total_columns, created_at, status
           FROM assessments
           WHERE status='completed'
           ORDER BY created_at DESC
           LIMIT %s OFFSET %s""",
        (per_page, offset))

    total = db.fetchone(
        "SELECT COUNT(*) AS cnt FROM assessments WHERE status='completed'")['cnt']

    # Trend data: last 30 assessments for sparkline
    trend = db.fetchall(
        """SELECT debt_score, debt_category, created_at
           FROM assessments WHERE status='completed'
           ORDER BY created_at DESC LIMIT 30""")

    # Category distribution
    dist = db.fetchall(
        """SELECT debt_category, COUNT(*) AS cnt
           FROM assessments WHERE status='completed'
           GROUP BY debt_category""")

    return jsonify({
        "assessments": [_serial(r) for r in rows],
        "total":       total,
        "page":        page,
        "per_page":    per_page,
        "trend":       [_serial(t) for t in reversed(trend)],
        "distribution":[_serial(d) for d in dist],
    })


@app.route('/api/assessment/<int:assessment_id>/download')
def api_download_report(assessment_id):
    """Generate and serve PDF report."""
    a = db.fetchone("SELECT * FROM assessments WHERE id=%s", (assessment_id,))
    if not a:
        return jsonify({"error": "Not found"}), 404

    col_metrics     = db.fetchall(
        "SELECT * FROM quality_metrics WHERE assessment_id=%s", (assessment_id,))
    breakdown       = db.fetchall(
        "SELECT * FROM debt_breakdown WHERE assessment_id=%s", (assessment_id,))
    recommendations = db.fetchall(
        "SELECT * FROM recommendations WHERE assessment_id=%s", (assessment_id,))

    filename   = f"debt_report_{assessment_id}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    out_path   = os.path.join(app.config['REPORTS_FOLDER'], filename)

    ok = report_gen.generate_pdf(
        assessment    = _serial(a),
        col_metrics   = [_serial(m) for m in col_metrics],
        breakdown     = [_serial(b) for b in breakdown],
        recommendations = [_serial(r) for r in recommendations],
        output_path   = out_path,
    )

    if ok:
        return send_from_directory(app.config['REPORTS_FOLDER'], filename,
                                   as_attachment=True,
                                   download_name=f"TechDebt_Report_{a['assessment_name']}.pdf")
    else:
        txt_file = filename.replace('.pdf', '.txt')
        return send_from_directory(app.config['REPORTS_FOLDER'], txt_file,
                                   as_attachment=True)


@app.route('/api/assessment/<int:assessment_id>', methods=['DELETE'])
def api_delete_assessment(assessment_id):
    """Delete assessment and all related data."""
    a = db.fetchone(
        "SELECT filename FROM assessments WHERE id=%s", (assessment_id,))
    if not a:
        return jsonify({"error": "Not found"}), 404

    try:
        # Delete child rows first to avoid FK constraint errors
        for table in ['quality_metrics', 'debt_breakdown', 'recommendations', 'dataset_samples']:
            db.execute(f"DELETE FROM {table} WHERE assessment_id=%s", (assessment_id,))

        # Remove uploaded file
        fp = os.path.join(app.config['UPLOAD_FOLDER'], a['filename'])
        if os.path.exists(fp):
            os.remove(fp)

        db.execute("DELETE FROM assessments WHERE id=%s", (assessment_id,))
        return jsonify({"success": True})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/stats')
def api_stats():
    """Summary stats for header widgets."""
    stats = db.fetchone(
        """SELECT
               COUNT(*) AS total_assessments,
               AVG(debt_score) AS avg_score,
               SUM(total_rows) AS total_rows_analysed,
               MAX(created_at) AS last_run
           FROM assessments WHERE status='completed'""")
    return jsonify(_serial(stats) if stats else {})


# ─── Helpers ────────────────────────────────────────────────

def _serial(obj):
    """Make a dict JSON-serialisable (handles datetime, Decimal, etc.)."""
    if obj is None:
        return {}
    out = {}
    for k, v in obj.items():
        if isinstance(v, datetime):
            out[k] = v.strftime('%Y-%m-%d %H:%M:%S')
        elif hasattr(v, '__float__'):
            out[k] = float(v)
        else:
            out[k] = v
    return out


# ─── Error Handlers ─────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('500.html'), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)