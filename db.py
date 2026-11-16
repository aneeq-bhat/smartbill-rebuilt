import mysql.connector
from flask import current_app, g

def get_db():
    if "db" not in g:
        cfg = current_app.config
        options = dict(
            host=cfg["DB_HOST"], port=cfg["DB_PORT"],
            user=cfg["DB_USER"], password=cfg["DB_PASSWORD"],
            database=cfg["DB_NAME"], autocommit=False,
            connection_timeout=10,
        )
        if cfg.get("DB_SSL_CA"):
            options["ssl_ca"] = cfg["DB_SSL_CA"]
            options["ssl_verify_cert"] = True
        g.db = mysql.connector.connect(**options)
    return g.db

def close_db(_error=None):
    conn = g.pop("db", None)
    if conn is not None and conn.is_connected():
        conn.close()

def query_one(sql, params=()):
    cur = get_db().cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    finally:
        cur.close()

def query_all(sql, params=()):
    cur = get_db().cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close()

def execute(sql, params=()):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
