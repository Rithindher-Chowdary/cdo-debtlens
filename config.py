import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'cdo-debt-assessment-secret-2024')
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
    REPORTS_FOLDER = os.path.join(os.path.dirname(__file__), 'reports')
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'xls'}

    # MySQL
    MYSQL_HOST     = os.environ.get('MYSQL_HOST', 'localhost')
    MYSQL_USER     = os.environ.get('MYSQL_USER', 'root')
    MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD', 'password')
    MYSQL_DB       = os.environ.get('MYSQL_DB', 'cdo_debt_db')
    MYSQL_PORT     = int(os.environ.get('MYSQL_PORT', 3306))

    # Resend
    RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
    ADMIN_EMAIL    = os.environ.get('ADMIN_EMAIL', '')

    # OTP expiry in minutes
    OTP_EXPIRY_MINUTES = 10