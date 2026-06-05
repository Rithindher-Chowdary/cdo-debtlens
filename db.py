import psycopg2
import psycopg2.pool
import psycopg2.extras
import os

_pool = None

def get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=5,
            dsn=os.environ.get('DATABASE_URL', ''),
            cursor_factory=psycopg2.extras.RealDictCursor
        )
    return _pool

def get_conn():
    return get_pool().getconn()

def release_conn(conn):
    get_pool().putconn(conn)

# ─── helpers ────────────────────────────────────────────────

def fetchall(query, params=None):
    # Convert %s MySQL style — psycopg2 uses %s too, but handle None params
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(query, params or ())
        return cur.fetchall()
    finally:
        release_conn(conn)

def fetchone(query, params=None):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(query, params or ())
        return cur.fetchone()
    finally:
        release_conn(conn)

def execute(query, params=None):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(query, params or ())
        conn.commit()
        # Return lastrowid equivalent for INSERT
        if query.strip().upper().startswith('INSERT'):
            cur.execute('SELECT LASTVAL()')
            row = cur.fetchone()
            return row['lastval'] if row else None
        return None
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)

def execute_many(query, data):
    conn = get_conn()
    try:
        cur = conn.cursor()
        psycopg2.extras.execute_batch(cur, query, data)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        release_conn(conn)