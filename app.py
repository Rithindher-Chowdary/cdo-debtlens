"""
app.py — Flask Application Entry Point
CDO Technical Debt Assessment Tool
"""

import os
import json
import uuid
import random
import string
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import traceback
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash

import pandas as pd
from flask import (Flask, render_template, request, jsonify, session,
                   redirect, url_for, send_from_directory, flash, abort)

from config   import Config
from analyzer import analyse
import db
import report_gen

app = Flask(__name__)
app.config.from_object(Config)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['REPORTS_FOLDER'], exist_ok=True)


# ─── Auth Decorators ────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('role') != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ─── Email Helpers (Brevo SMTP) ─────────────────────────────

def _send_email(to_email, subject, html_body):
    """Core email sender using Brevo SMTP."""
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = f"CDO DebtLens <{app.config['BREVO_SENDER_EMAIL']}>"
        msg['To']      = to_email
        msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(app.config['BREVO_SMTP_HOST'],
                          int(app.config['BREVO_SMTP_PORT'])) as server:
            server.ehlo()
            server.starttls()
            server.login(app.config['BREVO_SMTP_USER'],
                         app.config['BREVO_SMTP_PASSWORD'])
            server.sendmail(app.config['BREVO_SMTP_USER'], to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Mail error: {e}")
        return False


def send_otp_email(to_email, otp, purpose='signup'):
    subject = 'CDO DebtLens — Your OTP Code'
    body = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto;padding:32px;
                background:#0f172a;color:#f0f4ff;border-radius:12px">
      <h2 style="color:#4f8ef7;margin-bottom:8px">CDO DebtLens</h2>
      <p style="color:#94a3b8">{"Verify your email to complete signup" if purpose == "signup" else "Your login verification code"}</p>
      <div style="background:#1a2237;border-radius:10px;padding:24px;
                  text-align:center;margin:24px 0">
        <p style="color:#94a3b8;margin-bottom:8px;font-size:13px">Your OTP Code</p>
        <div style="font-size:36px;font-weight:800;letter-spacing:12px;color:#4f8ef7">{otp}</div>
        <p style="color:#64748b;font-size:12px;margin-top:12px">Expires in 10 minutes</p>
      </div>
      <p style="color:#64748b;font-size:12px">If you didn't request this, ignore this email.</p>
    </div>
    """
    return _send_email(to_email, subject, body)


def send_admin_notification(user_name, user_email):
    body = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto;padding:32px;
                background:#0f172a;color:#f0f4ff;border-radius:12px">
      <h2 style="color:#4f8ef7">New User Pending Approval</h2>
      <div style="background:#1a2237;border-radius:10px;padding:20px;margin:20px 0">
        <p><strong>Name:</strong> {user_name}</p>
        <p><strong>Email:</strong> {user_email}</p>
        <p><strong>Time:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
      </div>
      <p style="color:#94a3b8">Login to the admin panel to approve or reject.</p>
    </div>
    """
    _send_email(app.config['ADMIN_EMAIL'],
                f"CDO DebtLens — New User Pending: {user_name}", body)


def send_approval_email(to_email, user_name, approved=True):
    body = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:auto;padding:32px;
                background:#0f172a;color:#f0f4ff;border-radius:12px">
      <h2 style="color:{'#22c55e' if approved else '#ef4444'}">
        {"Account Approved!" if approved else "Account Not Approved"}
      </h2>
      <p style="color:#94a3b8">Hi {user_name},
        {"your account has been approved. You can now login."
         if approved else
         "your account request was not approved. Contact the administrator."}
      </p>
    </div>
    """
    _send_email(to_email,
                "CDO DebtLens — Account Approved!" if approved else "CDO DebtLens — Account Update",
                body)


def generate_otp():
    return ''.join(random.choices(string.digits, k=6))


# ─── Utilities ──────────────────────────────────────────────

def allowed_file(filename):
    return ('.' in filename and
            filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS'])

def load_dataframe(filepath):
    ext = filepath.rsplit('.', 1)[1].lower()
    if ext == 'csv':
        try:
            return pd.read_csv(filepath, encoding='utf-8')
        except UnicodeDecodeError:
            return pd.read_csv(filepath, encoding='latin-1')
    else:
        return pd.read_excel(filepath)


# ─── Auth Page Routes ────────────────────────────────────────

@app.route('/login', methods=['GET'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/signup', methods=['GET'])
def signup():
    if 'user_id' in session:
        return redirect(url_for('index'))
    return render_template('signup.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/admin')
@admin_required
def admin():
    return render_template('admin.html')


# ─── Auth API Routes ─────────────────────────────────────────

@app.route('/api/auth/signup', methods=['POST'])
def api_signup():
    data      = request.get_json()
    full_name = data.get('full_name', '').strip()
    email     = data.get('email', '').strip().lower()
    password  = data.get('password', '')

    if not full_name or not email or not password:
        return jsonify({"error": "All fields are required"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    existing = db.fetchone("SELECT id FROM users WHERE email=%s", (email,))
    if existing:
        return jsonify({"error": "Email already registered"}), 400

    otp        = generate_otp()
    expires_at = datetime.now() + timedelta(minutes=app.config['OTP_EXPIRY_MINUTES'])

    session['signup_pending'] = {
        'full_name':     full_name,
        'email':         email,
        'password_hash': generate_password_hash(password),
    }

    db.execute(
        "INSERT INTO otp_codes (email, otp, purpose, expires_at) VALUES (%s,%s,'signup',%s)",
        (email, otp, expires_at)
    )

    sent = send_otp_email(email, otp, purpose='signup')
    if not sent:
        return jsonify({"error": "Failed to send OTP. Check RESEND_API_KEY."}), 500

    return jsonify({"success": True, "message": "OTP sent to your email"})


@app.route('/api/auth/verify-otp', methods=['POST'])
def api_verify_otp():
    data    = request.get_json()
    email   = data.get('email', '').strip().lower()
    otp     = data.get('otp', '').strip()
    purpose = data.get('purpose', 'signup')

    record = db.fetchone(
        """SELECT * FROM otp_codes
           WHERE email=%s AND otp=%s AND purpose=%s AND used=0
           ORDER BY created_at DESC LIMIT 1""",
        (email, otp, purpose)
    )

    if not record:
        return jsonify({"error": "Invalid OTP"}), 400

    if datetime.now() > record['expires_at']:
        return jsonify({"error": "OTP has expired. Please request a new one."}), 400

    db.execute("UPDATE otp_codes SET used=1 WHERE id=%s", (record['id'],))

    if purpose == 'signup':
        pending = session.get('signup_pending')
        if not pending or pending['email'] != email:
            return jsonify({"error": "Session expired. Please sign up again."}), 400

        db.execute(
            "INSERT INTO users (full_name, email, password_hash, role, status) VALUES (%s,%s,%s,'user','pending')",
            (pending['full_name'], pending['email'], pending['password_hash'])
        )
        session.pop('signup_pending', None)
        send_admin_notification(pending['full_name'], pending['email'])

        return jsonify({
            "success": True,
            "message": "Email verified! Your account is pending admin approval."
        })

    elif purpose == 'login':
        pending = session.get('login_pending')
        if not pending or pending['email'] != email:
            return jsonify({"error": "Session expired. Please login again."}), 400

        user = db.fetchone("SELECT * FROM users WHERE email=%s", (email,))
        session.clear()
        session['user_id']   = user['id']
        session['full_name'] = user['full_name']
        session['email']     = user['email']
        session['role']      = user['role']
        session.permanent    = True

        return jsonify({"success": True, "role": user['role']})


@app.route('/api/auth/login', methods=['POST'])
def api_login():
    data     = request.get_json()
    email    = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    user = db.fetchone("SELECT * FROM users WHERE email=%s", (email,))

    if not user or not check_password_hash(user['password_hash'], password):
        return jsonify({"error": "Invalid email or password"}), 401

    if user['status'] == 'pending':
        return jsonify({"error": "Your account is pending admin approval."}), 403

    if user['status'] == 'rejected':
        return jsonify({"error": "Your account has been rejected. Contact administrator."}), 403

    otp        = generate_otp()
    expires_at = datetime.now() + timedelta(minutes=app.config['OTP_EXPIRY_MINUTES'])

    db.execute(
        "INSERT INTO otp_codes (email, otp, purpose, expires_at) VALUES (%s,%s,'login',%s)",
        (email, otp, expires_at)
    )

    session['login_pending'] = {'email': email}

    sent = send_otp_email(email, otp, purpose='login')
    if not sent:
        return jsonify({"error": "Failed to send OTP. Check RESEND_API_KEY."}), 500

    return jsonify({"success": True, "message": "OTP sent to your email"})


@app.route('/api/auth/resend-otp', methods=['POST'])
def api_resend_otp():
    data    = request.get_json()
    email   = data.get('email', '').strip().lower()
    purpose = data.get('purpose', 'signup')

    otp        = generate_otp()
    expires_at = datetime.now() + timedelta(minutes=app.config['OTP_EXPIRY_MINUTES'])

    db.execute(
        "INSERT INTO otp_codes (email, otp, purpose, expires_at) VALUES (%s,%s,%s,%s)",
        (email, otp, purpose, expires_at)
    )

    sent = send_otp_email(email, otp, purpose=purpose)
    if not sent:
        return jsonify({"error": "Failed to resend OTP"}), 500

    return jsonify({"success": True, "message": "OTP resent successfully"})


# ─── Admin API Routes ────────────────────────────────────────

@app.route('/api/admin/users')
@admin_required
def api_admin_users():
    status = request.args.get('status', 'pending')
    users  = db.fetchall(
        "SELECT id, full_name, email, status, role, created_at FROM users WHERE status=%s ORDER BY created_at DESC",
        (status,)
    )
    return jsonify({"users": [_serial(u) for u in users]})


@app.route('/api/admin/users/<int:user_id>/approve', methods=['POST'])
@admin_required
def api_approve_user(user_id):
    user = db.fetchone("SELECT * FROM users WHERE id=%s", (user_id,))
    if not user:
        return jsonify({"error": "User not found"}), 404
    db.execute(
        "UPDATE users SET status='approved', approved_at=%s, approved_by=%s WHERE id=%s",
        (datetime.now(), session['user_id'], user_id)
    )
    send_approval_email(user['email'], user['full_name'], approved=True)
    return jsonify({"success": True})


@app.route('/api/admin/users/<int:user_id>/reject', methods=['POST'])
@admin_required
def api_reject_user(user_id):
    user = db.fetchone("SELECT * FROM users WHERE id=%s", (user_id,))
    if not user:
        return jsonify({"error": "User not found"}), 404
    db.execute("UPDATE users SET status='rejected' WHERE id=%s", (user_id,))
    send_approval_email(user['email'], user['full_name'], approved=False)
    return jsonify({"success": True})


@app.route('/api/admin/users/<int:user_id>/delete', methods=['DELETE'])
@admin_required
def api_delete_user(user_id):
    if user_id == session['user_id']:
        return jsonify({"error": "Cannot delete your own account"}), 400
    db.execute("DELETE FROM users WHERE id=%s", (user_id,))
    return jsonify({"success": True})


@app.route('/api/admin/stats')
@admin_required
def api_admin_stats():
    stats = {
        "pending":  db.fetchone("SELECT COUNT(*) AS cnt FROM users WHERE status='pending'")['cnt'],
        "approved": db.fetchone("SELECT COUNT(*) AS cnt FROM users WHERE status='approved'")['cnt'],
        "rejected": db.fetchone("SELECT COUNT(*) AS cnt FROM users WHERE status='rejected'")['cnt'],
        "total":    db.fetchone("SELECT COUNT(*) AS cnt FROM users")['cnt'],
    }
    return jsonify(stats)


# ─── Page Routes (all protected) ────────────────────────────

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/dashboard/<int:assessment_id>')
@login_required
def dashboard(assessment_id):
    assessment = db.fetchone("SELECT * FROM assessments WHERE id=%s", (assessment_id,))
    if not assessment:
        abort(404)
    return render_template('dashboard.html', assessment=assessment)

@app.route('/history')
@login_required
def history():
    return render_template('history.html')

@app.route('/report/<int:assessment_id>')
@login_required
def report_page(assessment_id):
    assessment = db.fetchone("SELECT * FROM assessments WHERE id=%s", (assessment_id,))
    if not assessment:
        abort(404)
    return render_template('report.html', assessment=assessment)


# ─── API Routes ─────────────────────────────────────────────

@app.route('/api/upload', methods=['POST'])
@login_required
def api_upload():
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

    file_size   = os.path.getsize(save_path)
    assess_name = (request.form.get('assessment_name') or original_name.rsplit('.', 1)[0])

    assessment_id = db.execute(
        """INSERT INTO assessments
           (assessment_name, filename, original_filename, file_size, file_type, status)
           VALUES (%s,%s,%s,%s,%s,'processing')""",
        (assess_name, unique_name, original_name, file_size, ext)
    )

    try:
        df     = load_dataframe(save_path)
        result = analyse(df)

        db.execute(
            """UPDATE assessments
               SET total_rows=%s, total_columns=%s, duplicate_rows=%s,
                   debt_score=%s, debt_category=%s, status='completed'
               WHERE id=%s""",
            (result['total_rows'], result['total_columns'],
             result['potential_duplicates'],
             result['debt_score'], result['debt_category'], assessment_id)
        )

        cm_rows = [(
            assessment_id,
            m['column_name'], m['data_type'], m['total_values'],
            m['missing_count'], m['missing_pct'], m['duplicate_count'],
            m['empty_string_count'], m['invalid_format_count'],
            m['unique_count'], m.get('min_value'), m.get('max_value'),
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

        db.execute_many(
            "INSERT INTO debt_breakdown (assessment_id,category,score,weight,affected_columns) VALUES (%s,%s,%s,%s,%s)",
            [(assessment_id, b['category'], b['score'], b['weight'], b['affected_columns'])
             for b in result['breakdown']]
        )

        db.execute_many(
            """INSERT INTO recommendations
               (assessment_id,priority,category,title,description,effort,impact,column_ref)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            [(assessment_id, r['priority'], r['category'], r['title'],
              r['description'], r['effort'], r['impact'], r.get('column_ref',''))
             for r in result['recommendations']]
        )

        db.execute(
            "INSERT INTO dataset_samples (assessment_id,sample_data,column_headers) VALUES (%s,%s,%s)",
            (assessment_id, json.dumps(result['sample_data']), json.dumps(result['column_headers']))
        )

        return jsonify({
            "success":              True,
            "assessment_id":        assessment_id,
            "debt_score":           result['debt_score'],
            "debt_category":        result['debt_category'],
            "exact_duplicates":     result['exact_duplicates'],
            "potential_duplicates": result['potential_duplicates'],
        })

    except Exception as e:
        traceback.print_exc()
        db.execute("UPDATE assessments SET status='failed' WHERE id=%s", (assessment_id,))
        return jsonify({"error": str(e)}), 500


@app.route('/api/assessment/<int:assessment_id>')
@login_required
def api_assessment(assessment_id):
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

    return jsonify({
        "assessment":      _serial(a),
        "col_metrics":     [_serial(m) for m in col_metrics],
        "breakdown":       [_serial(b) for b in breakdown],
        "recommendations": [_serial(r) for r in recommendations],
        "sample_data":     json.loads(sample['sample_data'])    if sample else [],
        "column_headers":  json.loads(sample['column_headers']) if sample else [],
    })


@app.route('/api/history')
@login_required
def api_history():
    page     = max(1, int(request.args.get('page', 1)))
    per_page = 12
    offset   = (page - 1) * per_page

    rows = db.fetchall(
        """SELECT id, assessment_name, original_filename, debt_score,
                  debt_category, total_rows, total_columns, created_at, status
           FROM assessments WHERE status='completed'
           ORDER BY created_at DESC LIMIT %s OFFSET %s""",
        (per_page, offset))

    total = db.fetchone(
        "SELECT COUNT(*) AS cnt FROM assessments WHERE status='completed'")['cnt']

    trend = db.fetchall(
        """SELECT debt_score, debt_category, created_at
           FROM assessments WHERE status='completed'
           ORDER BY created_at DESC LIMIT 30""")

    dist = db.fetchall(
        """SELECT debt_category, COUNT(*) AS cnt
           FROM assessments WHERE status='completed'
           GROUP BY debt_category""")

    return jsonify({
        "assessments":  [_serial(r) for r in rows],
        "total":        total,
        "page":         page,
        "per_page":     per_page,
        "trend":        [_serial(t) for t in reversed(trend)],
        "distribution": [_serial(d) for d in dist],
    })


@app.route('/api/assessment/<int:assessment_id>/download')
@login_required
def api_download_report(assessment_id):
    a = db.fetchone("SELECT * FROM assessments WHERE id=%s", (assessment_id,))
    if not a:
        return jsonify({"error": "Not found"}), 404

    col_metrics     = db.fetchall("SELECT * FROM quality_metrics WHERE assessment_id=%s", (assessment_id,))
    breakdown       = db.fetchall("SELECT * FROM debt_breakdown WHERE assessment_id=%s", (assessment_id,))
    recommendations = db.fetchall("SELECT * FROM recommendations WHERE assessment_id=%s", (assessment_id,))

    filename = f"debt_report_{assessment_id}_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    out_path = os.path.join(app.config['REPORTS_FOLDER'], filename)

    ok = report_gen.generate_pdf(
        assessment      = _serial(a),
        col_metrics     = [_serial(m) for m in col_metrics],
        breakdown       = [_serial(b) for b in breakdown],
        recommendations = [_serial(r) for r in recommendations],
        output_path     = out_path,
    )

    if ok:
        return send_from_directory(app.config['REPORTS_FOLDER'], filename,
                                   as_attachment=True,
                                   download_name=f"TechDebt_Report_{a['assessment_name']}.pdf")
    else:
        txt_file = filename.replace('.pdf', '.txt')
        return send_from_directory(app.config['REPORTS_FOLDER'], txt_file, as_attachment=True)


@app.route('/api/assessment/<int:assessment_id>', methods=['DELETE'])
@login_required
def api_delete_assessment(assessment_id):
    a = db.fetchone("SELECT filename FROM assessments WHERE id=%s", (assessment_id,))
    if not a:
        return jsonify({"error": "Not found"}), 404

    try:
        for table in ['quality_metrics','debt_breakdown','recommendations','dataset_samples']:
            db.execute(f"DELETE FROM {table} WHERE assessment_id=%s", (assessment_id,))

        fp = os.path.join(app.config['UPLOAD_FOLDER'], a['filename'])
        if os.path.exists(fp):
            os.remove(fp)

        db.execute("DELETE FROM assessments WHERE id=%s", (assessment_id,))
        return jsonify({"success": True})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/api/stats')
@login_required
def api_stats():
    stats = db.fetchone(
        """SELECT COUNT(*) AS total_assessments, AVG(debt_score) AS avg_score,
                  SUM(total_rows) AS total_rows_analysed, MAX(created_at) AS last_run
           FROM assessments WHERE status='completed'""")
    return jsonify(_serial(stats) if stats else {})


# ─── Helpers ────────────────────────────────────────────────

def _serial(obj):
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

@app.errorhandler(403)
def forbidden(e):
    return render_template('404.html'), 403

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('500.html'), 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)