import os
import secrets
import sqlite3
import threading
from pathlib import Path

DB_PATH = Path(os.environ.get("SHOWER_DB", str(Path(__file__).resolve().parent / "shower_data" / "shower.db")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_local = threading.local()
_write_lock = threading.RLock()


def get_db():
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def write_db(func):
    def wrapper(*args, **kwargs):
        with _write_lock:
            result = func(*args, **kwargs)
            get_db().commit()
            return result
    return wrapper


def init_db():
    db = get_db()
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        discord_id TEXT PRIMARY KEY,
        discord_tag TEXT,
        username TEXT,
        avatar TEXT,
        access_token TEXT,
        refresh_token TEXT,
        token_expires_at INTEGER DEFAULT 0,
        role_ids TEXT DEFAULT '',
        is_admin INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY,
        discord_id TEXT NOT NULL,
        expires_at TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (discord_id) REFERENCES users(discord_id)
    );

    CREATE TABLE IF NOT EXISTS items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        category TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS systems (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL
    );

    CREATE TABLE IF NOT EXISTS stations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        system_id INTEGER,
        FOREIGN KEY (system_id) REFERENCES systems(id)
    );

    CREATE TABLE IF NOT EXISTS community_inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        discord_id TEXT NOT NULL,
        item_name TEXT NOT NULL,
        quality INTEGER DEFAULT 100,
        quantity_scu REAL DEFAULT 1.0,
        station TEXT DEFAULT '',
        synced_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (discord_id) REFERENCES users(discord_id)
    );

    CREATE TABLE IF NOT EXISTS order_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        discord_id TEXT NOT NULL,
        item_name TEXT NOT NULL,
        min_quality INTEGER DEFAULT 1,
        quantity INTEGER DEFAULT 1,
        notes TEXT DEFAULT '',
        status TEXT DEFAULT 'open',
        assigned_discord_id TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        fulfilled_at TEXT,
        FOREIGN KEY (discord_id) REFERENCES users(discord_id)
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        discord_id TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT DEFAULT '',
        source TEXT DEFAULT 'system',
        read INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (discord_id) REFERENCES users(discord_id)
    );

    CREATE TABLE IF NOT EXISTS sync_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        discord_id TEXT,
        direction TEXT,
        status TEXT,
        message TEXT,
        synced_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY,
        value TEXT
    );

    CREATE TABLE IF NOT EXISTS api_keys (
        key TEXT PRIMARY KEY,
        discord_id TEXT NOT NULL,
        label TEXT DEFAULT '',
        last_used TEXT,
        expires_at TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (discord_id) REFERENCES users(discord_id)
    );
    """)
    db.commit()
    _migrate()


def _migrate():
    db = get_db()
    cols = [row[1] for row in db.execute("PRAGMA table_info(notifications)").fetchall()]
    if "dm_sent" not in cols:
        db.execute("ALTER TABLE notifications ADD COLUMN dm_sent INTEGER DEFAULT 0")
        db.commit()


# --- User helpers ---

def ensure_user(discord_id):
    db = get_db()
    row = db.execute("SELECT discord_id FROM users WHERE discord_id=?", (discord_id,)).fetchone()
    if not row:
        db.execute("INSERT INTO users (discord_id, discord_tag) VALUES (?, ?)",
                   (discord_id, f"Unknown#{discord_id[:4]}"))


@write_db
def upsert_user(discord_id, discord_tag, username, avatar, access_token, refresh_token,
                token_expires_in, role_ids, is_admin):
    db = get_db()
    db.execute("""INSERT INTO users (discord_id, discord_tag, username, avatar,
                access_token, refresh_token, token_expires_at, role_ids, is_admin)
                VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(discord_id) DO UPDATE SET
                discord_tag=excluded.discord_tag, username=excluded.username,
                avatar=excluded.avatar, access_token=excluded.access_token,
                refresh_token=excluded.refresh_token, token_expires_at=excluded.token_expires_at,
                role_ids=excluded.role_ids, is_admin=excluded.is_admin""",
               (discord_id, discord_tag, username, avatar, access_token,
                refresh_token, token_expires_in, role_ids, is_admin))


def get_user_by_session(session_id):
    db = get_db()
    return db.execute("""SELECT u.* FROM users u
        JOIN sessions s ON u.discord_id = s.discord_id
        WHERE s.session_id=? AND (s.expires_at IS NULL OR s.expires_at > datetime('now'))""",
        (session_id,)).fetchone()


# --- Sessions ---

@write_db
def create_session(session_id, discord_id, ttl):
    db = get_db()
    db.execute("INSERT INTO sessions (session_id, discord_id, expires_at) VALUES (?, ?, datetime('now', '+{} seconds'))".format(ttl),
               (session_id, discord_id))


@write_db
def delete_session(session_id):
    get_db().execute("DELETE FROM sessions WHERE session_id=?", (session_id,))


# --- API Keys ---

@write_db
def create_api_key(discord_id, label=""):
    key = secrets.token_hex(32)
    db = get_db()
    db.execute("INSERT INTO api_keys (key, discord_id, label) VALUES (?, ?, ?)",
               (key, discord_id, label))
    return key


@write_db
def revoke_api_key(key, discord_id):
    get_db().execute("DELETE FROM api_keys WHERE key=? AND discord_id=?", (key, discord_id))


def get_user_by_api_key(key):
    db = get_db()
    row = db.execute("""SELECT u.* FROM users u
        JOIN api_keys k ON u.discord_id = k.discord_id
        WHERE k.key=? AND (k.expires_at IS NULL OR k.expires_at > datetime('now'))""",
        (key,)).fetchone()
    if row:
        db.execute("UPDATE api_keys SET last_used=datetime('now') WHERE key=?", (key,))
        db.commit()
    return row


def get_api_keys(discord_id):
    return get_db().execute(
        "SELECT key, label, last_used, expires_at, created_at FROM api_keys WHERE discord_id=? ORDER BY created_at DESC",
        (discord_id,)).fetchall()


# --- Inventory ---

@write_db
def sync_inventory(discord_id, item_name, quality, quantity_scu, station):
    ensure_user(discord_id)
    db = get_db()
    existing = db.execute(
        "SELECT id FROM community_inventory WHERE discord_id=? AND item_name=? AND quality=? AND station=?",
        (discord_id, item_name, quality, station)).fetchone()
    if existing:
        db.execute("UPDATE community_inventory SET quantity_scu=?, synced_at=datetime('now') WHERE id=?",
                   (quantity_scu, existing["id"]))
    else:
        db.execute("""INSERT INTO community_inventory (discord_id, item_name, quality, quantity_scu, station)
                   VALUES (?,?,?,?,?)""", (discord_id, item_name, quality, quantity_scu, station))


@write_db
def delete_inventory_item(discord_id, inventory_id):
    ensure_user(discord_id)
    get_db().execute("DELETE FROM community_inventory WHERE id=? AND discord_id=?",
                     (inventory_id, discord_id))


def get_user_inventory(discord_id, limit=None):
    q = "SELECT * FROM community_inventory WHERE discord_id=? ORDER BY synced_at DESC"
    params = [discord_id]
    if limit:
        q += " LIMIT ?"
        params.append(limit)
    return get_db().execute(q, params).fetchall()


def all_inventory(limit=200):
    return get_db().execute(
        """SELECT ci.*, u.discord_tag FROM community_inventory ci
        LEFT JOIN users u ON ci.discord_id = u.discord_id
        ORDER BY ci.synced_at DESC LIMIT ?""", (limit,)).fetchall()


# --- Orders ---

@write_db
def create_order(discord_id, item_name, min_quality, quantity, notes=""):
    ensure_user(discord_id)
    db = get_db()
    cur = db.execute("""INSERT INTO order_requests (discord_id, item_name, min_quality, quantity, notes)
                     VALUES (?,?,?,?,?)""", (discord_id, item_name, min_quality, quantity, notes))
    order_id = cur.lastrowid
    _notify_all(f"New Order: {item_name}", f"{item_name} (Q{min_quality}+, x{quantity}) requested.")
    return order_id


@write_db
def fulfill_order(order_id, fulfiller_discord_id):
    ensure_user(fulfiller_discord_id)
    db = get_db()
    order = db.execute("SELECT * FROM order_requests WHERE id=?", (order_id,)).fetchone()
    if not order:
        return None, "Order not found"
    if order["status"] != "open":
        return None, "Order already fulfilled"
    db.execute("""UPDATE order_requests SET status='fulfilled', assigned_discord_id=?,
                fulfilled_at=datetime('now') WHERE id=?""", (fulfiller_discord_id, order_id))
    _add_notification(order["discord_id"], "Order Fulfilled",
                      f"Your request for {order['item_name']} has been fulfilled.", "order")
    return order, None


def get_open_orders():
    return get_db().execute(
        "SELECT * FROM order_requests WHERE status='open' ORDER BY created_at DESC").fetchall()


def get_user_orders(discord_id, limit=None):
    q = "SELECT * FROM order_requests WHERE discord_id=? ORDER BY created_at DESC"
    params = [discord_id]
    if limit:
        q += " LIMIT ?"
        params.append(limit)
    return get_db().execute(q, params).fetchall()


# --- Notifications ---

@write_db
def _add_notification(discord_id, title, body, source="system"):
    ensure_user(discord_id)
    get_db().execute("""INSERT INTO notifications (discord_id, title, body, source)
                     VALUES (?,?,?,?)""", (discord_id, title, body, source))


@write_db
def _notify_all(title, body, source="system"):
    users = get_db().execute("SELECT discord_id FROM users").fetchall()
    for u in users:
        _add_notification(u["discord_id"], title, body, source)


def get_notifications(discord_id, limit=None):
    q = "SELECT * FROM notifications WHERE discord_id=? ORDER BY created_at DESC"
    params = [discord_id]
    if limit:
        q += " LIMIT ?"
        params.append(limit)
    return get_db().execute(q, params).fetchall()


def get_pending_dm_notifications(limit=20):
    return get_db().execute(
        "SELECT * FROM notifications WHERE dm_sent=0 ORDER BY created_at ASC LIMIT ?",
        (limit,)
    ).fetchall()


@write_db
def mark_notification_dm_sent(notif_id):
    get_db().execute("UPDATE notifications SET dm_sent=1 WHERE id=?", (notif_id,))


# --- Sync log ---

@write_db
def log_sync(discord_id, direction, status, message):
    get_db().execute("INSERT INTO sync_log (discord_id, direction, status, message) VALUES (?,?,?,?)",
                     (discord_id, direction, status, message[:500]))
