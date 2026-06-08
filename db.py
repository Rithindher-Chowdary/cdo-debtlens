import mysql.connector
from mysql.connector import pooling
import os
import json

_pool = None

def get_pool():
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="cdo_pool",
            pool_size=5,
            host=os.environ.get('MYSQL_HOST', 'localhost'),
            user=os.environ.get('MYSQL_USER', 'root'),
            password=os.environ.get('MYSQL_PASSWORD', 'password'),
            database=os.environ.get('MYSQL_DB', 'cdo_debt_db'),
            port=int(os.environ.get('MYSQL_PORT', 3306)),
            charset='utf8mb4',
            collation='utf8mb4_unicode_ci',
            autocommit=False
        )
    return _pool

def get_conn():
    return get_pool().get_connection()

# ─── helpers ────────────────────────────────────────────────

def fetchall(query, params=None):
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(query, params or ())
        return cur.fetchall()
    finally:
        conn.close()

def fetchone(query, params=None):
    conn = get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(query, params or ())
        return cur.fetchone()
    finally:
        conn.close()

def execute(query, params=None):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(query, params or ())
        conn.commit()
        return cur.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def execute_many(query, data):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.executemany(query, data)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()