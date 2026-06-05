-- =============================================================
-- CDO Technical Debt Assessment — PostgreSQL Schema
-- =============================================================

CREATE TABLE IF NOT EXISTS assessments (
    id                  SERIAL PRIMARY KEY,
    assessment_name     VARCHAR(255) NOT NULL,
    filename            VARCHAR(255) NOT NULL,
    original_filename   VARCHAR(255) NOT NULL,
    file_size           BIGINT DEFAULT 0,
    file_type           VARCHAR(20) DEFAULT 'csv',
    total_rows          INT DEFAULT 0,
    total_columns       INT DEFAULT 0,
    duplicate_rows      INT DEFAULT 0,
    debt_score          DECIMAL(5,2) DEFAULT 0.00,
    debt_category       VARCHAR(20) DEFAULT 'Low',
    status              VARCHAR(20) DEFAULT 'processing',
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes               TEXT
);

CREATE TABLE IF NOT EXISTS quality_metrics (
    id                   SERIAL PRIMARY KEY,
    assessment_id        INT NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    column_name          VARCHAR(255) NOT NULL,
    data_type            VARCHAR(50),
    total_values         INT DEFAULT 0,
    missing_count        INT DEFAULT 0,
    missing_pct          DECIMAL(5,2) DEFAULT 0.00,
    duplicate_count      INT DEFAULT 0,
    empty_string_count   INT DEFAULT 0,
    invalid_format_count INT DEFAULT 0,
    unique_count         INT DEFAULT 0,
    min_value            VARCHAR(255),
    max_value            VARCHAR(255),
    mean_value           DECIMAL(15,4),
    std_dev              DECIMAL(15,4),
    outlier_count        INT DEFAULT 0,
    column_debt_score    DECIMAL(5,2) DEFAULT 0.00
);

CREATE TABLE IF NOT EXISTS debt_breakdown (
    id               SERIAL PRIMARY KEY,
    assessment_id    INT NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    category         VARCHAR(100) NOT NULL,
    score            DECIMAL(5,2) DEFAULT 0.00,
    weight           DECIMAL(4,2) DEFAULT 1.00,
    affected_columns INT DEFAULT 0,
    description      TEXT
);

CREATE TABLE IF NOT EXISTS recommendations (
    id            SERIAL PRIMARY KEY,
    assessment_id INT NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    priority      VARCHAR(20) DEFAULT 'Medium',
    category      VARCHAR(100),
    title         VARCHAR(500) NOT NULL,
    description   TEXT,
    effort        VARCHAR(50) DEFAULT 'Medium Effort',
    impact        VARCHAR(20) DEFAULT 'Medium',
    column_ref    VARCHAR(255)
);

CREATE TABLE IF NOT EXISTS dataset_samples (
    id             SERIAL PRIMARY KEY,
    assessment_id  INT NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
    sample_data    TEXT,
    column_headers TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    full_name     VARCHAR(255) NOT NULL,
    email         VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role          VARCHAR(20) DEFAULT 'user',
    status        VARCHAR(20) DEFAULT 'pending',
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    approved_at   TIMESTAMP,
    approved_by   INT
);

CREATE TABLE IF NOT EXISTS otp_codes (
    id         SERIAL PRIMARY KEY,
    email      VARCHAR(255) NOT NULL,
    otp        VARCHAR(6) NOT NULL,
    purpose    VARCHAR(20) DEFAULT 'signup',
    used       SMALLINT DEFAULT 0,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);