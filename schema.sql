-- =============================================================
-- CDO Technical Debt Assessment — Complete MySQL Schema
-- Run once to initialise the database
-- =============================================================

CREATE DATABASE IF NOT EXISTS cdo_debt_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE cdo_debt_db;

CREATE TABLE IF NOT EXISTS assessments (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    assessment_name     VARCHAR(255) NOT NULL,
    filename            VARCHAR(255) NOT NULL,
    original_filename   VARCHAR(255) NOT NULL,
    file_size           BIGINT DEFAULT 0,
    file_type           VARCHAR(20) DEFAULT 'csv',
    total_rows          INT DEFAULT 0,
    total_columns       INT DEFAULT 0,
    duplicate_rows      INT DEFAULT 0,
    debt_score          DECIMAL(5,2) DEFAULT 0.00,
    debt_category       ENUM('Low','Medium','High') DEFAULT 'Low',
    status              ENUM('processing','completed','failed') DEFAULT 'processing',
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    notes               TEXT,
    INDEX idx_created   (created_at),
    INDEX idx_category  (debt_category),
    INDEX idx_status    (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS quality_metrics (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    assessment_id        INT NOT NULL,
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
    column_debt_score    DECIMAL(5,2) DEFAULT 0.00,
    FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE,
    INDEX idx_assessment (assessment_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS debt_breakdown (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    assessment_id    INT NOT NULL,
    category         VARCHAR(100) NOT NULL,
    score            DECIMAL(5,2) DEFAULT 0.00,
    weight           DECIMAL(4,2) DEFAULT 1.00,
    affected_columns INT DEFAULT 0,
    description      TEXT,
    FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE,
    INDEX idx_assessment (assessment_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS recommendations (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    assessment_id INT NOT NULL,
    priority      ENUM('Critical','High','Medium','Low') DEFAULT 'Medium',
    category      VARCHAR(100),
    title         VARCHAR(500) NOT NULL,
    description   TEXT,
    effort        ENUM('Quick Win','Medium Effort','Long Term') DEFAULT 'Medium Effort',
    impact        ENUM('High','Medium','Low') DEFAULT 'Medium',
    column_ref    VARCHAR(255),
    FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE,
    INDEX idx_assessment (assessment_id),
    INDEX idx_priority   (priority)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS dataset_samples (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    assessment_id INT NOT NULL,
    sample_data   LONGTEXT,
    column_headers TEXT,
    FOREIGN KEY (assessment_id) REFERENCES assessments(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS users (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    full_name     VARCHAR(255) NOT NULL,
    email         VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role          ENUM('admin','user') DEFAULT 'user',
    status        ENUM('pending','approved','rejected') DEFAULT 'pending',
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    approved_at   DATETIME,
    approved_by   INT,
    INDEX idx_email  (email),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS otp_codes (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    email      VARCHAR(255) NOT NULL,
    otp        VARCHAR(6) NOT NULL,
    purpose    ENUM('signup','login') DEFAULT 'signup',
    used       TINYINT DEFAULT 0,
    expires_at DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;