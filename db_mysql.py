"""MySQL backend for SHOWER. Imported by db.py when SHOWER_DB starts with 'mysql://'."""

import os
import queue
import threading
import urllib.parse

import pymysql

POOL_SIZE = 10
_pool = None
_pool_lock = threading.Lock()


def _parse_dsn(dsn):
    parsed = urllib.parse.urlparse(dsn)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "user": parsed.username or "root",
        "password": parsed.password or "",
        "database": parsed.path.lstrip("/") or "shower",
        "charset": "utf8mb4",
    }


def init():
    global _pool
    dsn = os.environ.get("SHOWER_DB", "mysql://root:@localhost/shower")
    cfg = _parse_dsn(dsn)
    _pool = queue.Queue(maxsize=POOL_SIZE)
    for _ in range(POOL_SIZE):
        conn = pymysql.connect(
            host=cfg["host"], port=cfg["port"], user=cfg["user"],
            password=cfg["password"], database=cfg["database"],
            charset=cfg["charset"], cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )
        _pool.put(conn)


def get_conn():
    if _pool is None:
        init()
    return _pool.get()


def put_conn(conn):
    _pool.put(conn)


def close_all():
    global _pool
    if _pool:
        while not _pool.empty():
            try:
                _pool.get().close()
            except Exception:
                pass


def now():
    return "NOW()"


def now_plus_interval(seconds):
    return f"(NOW() + INTERVAL {seconds} SECOND)"


def now_minus_interval(days):
    return f"(NOW() - INTERVAL {days} DAY)"


def insert_or_ignore():
    return "INSERT IGNORE"


def last_insert_id():
    return "LAST_INSERT_ID()"


def on_conflict_upsert(table, pk_col):
    """Generate ON DUPLICATE KEY UPDATE clause."""
    return "ON DUPLICATE KEY UPDATE"


def table_info_sql(table):
    return f"SHOW COLUMNS FROM `{table}`"


def placeholder():
    return "%s"
