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
        display_name TEXT,
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

    CREATE TABLE IF NOT EXISTS pits_connections (
        discord_id TEXT PRIMARY KEY,
        pits_url TEXT NOT NULL,
        client_token TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (discord_id) REFERENCES users(discord_id)
    );

    CREATE TABLE IF NOT EXISTS client_tokens (
        token TEXT PRIMARY KEY,
        discord_id TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        expires_at TEXT NOT NULL,
        FOREIGN KEY (discord_id) REFERENCES users(discord_id)
    );

    CREATE TABLE IF NOT EXISTS roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        level INTEGER NOT NULL DEFAULT 1,
        discord_role_id TEXT,
        is_env INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY,
        value TEXT
    );
    """)
    db.commit()
    _migrate()
    _seed_defaults()


def _migrate():
    db = get_db()
    cols_n = [row[1] for row in db.execute("PRAGMA table_info(notifications)").fetchall()]
    if "dm_sent" not in cols_n:
        db.execute("ALTER TABLE notifications ADD COLUMN dm_sent INTEGER DEFAULT 0")
        db.commit()
    cols_u = [row[1] for row in db.execute("PRAGMA table_info(users)").fetchall()]
    if "display_name" not in cols_u:
        db.execute("ALTER TABLE users ADD COLUMN display_name TEXT")
        db.commit()
    if "role_id" not in cols_u:
        db.execute("ALTER TABLE users ADD COLUMN role_id INTEGER REFERENCES roles(id)")
        db.commit()
    if "banned" not in cols_u:
        db.execute("ALTER TABLE users ADD COLUMN banned INTEGER DEFAULT 0")
        db.commit()
    if "last_seen" not in cols_u:
        db.execute("ALTER TABLE users ADD COLUMN last_seen TEXT")
        db.commit()
    if db.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0:
        for row in [
            (1, "Agricium"), (3, "Agricultural Supplies"), (4, "Altruciatoxin"),
            (5, "Aluminum"), (7, "Amioshi Plague"), (8, "Aphorite"), (9, "Astatine"),
            (10, "Audio Visual Equipment"), (11, "Beryl"), (13, "Bexalite"),
            (15, "Borase"), (17, "Chlorine"), (18, "Compboard"),
            (19, "Construction Materials"), (20, "Copper"), (22, "Corundum"),
            (24, "Degnous Root"), (25, "Diamond"), (27, "Distilled Spirits"),
            (28, "Dolivine"), (29, "E'tam"), (30, "Fireworks"), (31, "Fluorine"),
            (32, "Gasping Weevil Eggs"), (33, "Gold"), (35, "Golden Medmon"),
            (36, "Hadanite"), (37, "Heart of the Woods"), (38, "Helium"),
            (39, "Hephaestanite"), (41, "Hydrogen"), (42, "Inert Materials"),
            (43, "Iodine"), (44, "Iron"), (46, "Janalite"), (47, "Laranite"),
            (49, "Luminalia Gift"), (50, "Maze"), (51, "Medical Supplies"),
            (52, "Neon"), (53, "Osoian Hides"), (54, "Party Favors"),
            (55, "Pitambu"), (56, "Processed Food"), (57, "Prota"),
            (58, "Quantainium"), (60, "Quartz"), (62, "Ranta Dung"),
            (63, "Recycled Material Composite"), (64, "Year of the Monkey Envelope"),
            (65, "Revenant Pod"), (66, "Revenant Tree Pollen"), (67, "Scrap"),
            (68, "SLAM"), (69, "Souvenirs"), (70, "Stims"),
            (71, "Stone Bug Shell"), (72, "Sunset Berries"), (73, "Taranite"),
            (75, "Titanium"), (77, "Tungsten"), (79, "Waste"), (80, "WiDoW"),
            (81, "Year of the Rooster Envelope"), (82, "AcryliPlex Composite"),
            (83, "Diluthermex"), (84, "Zeta-Prolanide"), (85, "Ammonia"),
            (87, "Quantum Fuel"), (88, "Year of the Dog Envelope"),
            (91, "Marok Gem"), (92, "Kopion Horn"), (93, "DynaFlex"),
            (95, "Redfin Energy Modulators"), (96, "Lifecure Medsticks"),
            (97, "Human Food Bars"), (98, "DCSR2"), (100, "Silicon"),
            (101, "Pressurized Ice"), (102, "Carbon"), (103, "Tin"),
            (104, "Hydrogen Fuel"), (105, "Decari Pod"), (106, "Nitrogen"),
            (108, "Apoxygenite"), (109, "Steel"), (110, "Cobalt"), (111, "Argon"),
            (112, "Bioplastic"), (114, "Methane"), (115, "Omnapoxy"),
            (116, "Potassium"), (118, "Xa'Pyen"), (119, "Diamond Laminate"),
            (120, "Fresh Food"), (121, "Partillium"), (122, "Stileron"),
            (123, "Mercury"), (124, "Riccite"), (125, "Raw Ice"),
            (126, "CK13-GID Seed Blend"), (127, "Dymantium"),
            (128, "Ship Ammunition"), (129, "HexaPolyMesh Coating"),
            (130, "Atlasium"), (132, "Thermalfoam"), (133, "Neograph"),
            (134, "Sarilus"), (135, "Silnex"), (136, "Lycara"),
            (137, "Lastaphrene"), (138, "Elespo"), (139, "Cadmium Allinide"),
            (140, "Krypton"), (141, "Anti-Hydrogen"), (142, "Jahlium"),
            (143, "Magnesium"), (144, "Jumping Limes"), (145, "Lunes"),
            (148, "Coal"), (150, "Phosphorus"), (151, "Selenium"),
            (152, "Tellurium"), (153, "Tritium"), (154, "Xenon"), (156, "Freeze"),
            (157, "Glow"), (158, "Mala"), (160, "Zip"),
            (164, "Year of the Pig Envelope"), (167, "Beradom"),
            (168, "Glacosite"), (169, "Feynmaline"), (170, "Carinite"),
            (171, "Jaclium"), (174, "Cave Kopion Horn"),
            (175, "Tundra Kopion Horn"), (179, "Atacamite"),
            (180, "Irradiated Kopion Horn"), (181, "Construction Material Rubble"),
            (182, "Construction Material Pebbles"),
            (183, "Construction Material Salvage"), (184, "Lindinium"),
            (186, "Organics"), (187, "Savrilium Ore"), (188, "Savrilium"),
            (190, "Torite"), (191, "CryoPod"), (192, "Year of the Rat Envelope"),
            (193, "Aslarite"), (194, "Ouratite"), (195, "Molina Mold Treatment"),
            (196, "Molina Ventilation Filters"), (197, "Molina Mold Samples"),
            (198, "Wuotan Seed"), (200, "Sadaryx"),
            (201, "Ship Ammunition - Size 1"), (202, "Ship Ammunition - Size 2"),
            (203, "Ship Ammunition - Size 3"), (204, "Ship Ammunition - Size 4"),
            (205, "Ship Ammunition - Size 5"), (206, "Ship Ammunition - Size 6"),
            (207, "Ship Ammunition - Size 7"), (208, "Ship Decoy Countermeasures"),
            (209, "Ship Noise Countermeasures"),
        ]:
            db.execute("INSERT OR IGNORE INTO items (id, name) VALUES (?, ?)", row)
        db.execute("INSERT OR IGNORE INTO items (name) VALUES ('Zeta-Prolanite')")
        db.commit()

    if db.execute("SELECT COUNT(*) FROM stations").fetchone()[0] == 0:
        for r in db.execute("SELECT DISTINCT station FROM community_inventory WHERE station IS NOT NULL AND station != ''"):
            db.execute("INSERT OR IGNORE INTO stations (name) VALUES (?)", (r["station"],))
        for row in [
            (1, "ARC-L1 Wide Forest Station"), (2, "ARC-L2 Lively Pathway Station"),
            (3, "ARC-L3 Modern Express Station"), (4, "ARC-L4 Faint Glen Station"),
            (5, "ARC-L5 Yellow Core Station"), (6, "Baijini Point"),
            (7, "CRU-L1 Ambitious Dream Station"), (8, "CRU-L4 Shallow Fields Station"),
            (9, "CRU-L5 Beautiful Glen Station"), (10, "Everus Harbor"),
            (11, "Green Imperial Housing Exchange"), (12, "HUR-L1 Green Glade Station"),
            (13, "HUR-L2 Faithful Dream Station"), (14, "HUR-L3 Thundering Express Station"),
            (15, "HUR-L4 Melodic Fields Station"), (16, "HUR-L5 High Course Station"),
            (17, "MIC-L1 Shallow Frontier Station"), (18, "MIC-L2 Long Forest Station"),
            (19, "MIC-L3 Endless Odyssey Station"), (20, "MIC-L4 Red Crossroads Station"),
            (21, "MIC-L5 Modern Icarus Station"), (22, "Port Olisar"),
            (23, "Port Tressler"), (24, "Pyro Gateway"), (25, "Nyx Gateway"),
            (26, "Terra Gateway"), (27, "Seraphim Station"), (31, "Checkmate Station"),
            (32, "Orbituary"), (33, "Starlight Service Station"), (34, "Patch City"),
            (38, "Rod's Fuel 'N Supplies"), (39, "Rat's Nest"), (41, "Endgame"),
            (42, "Dudley & Daughters"), (43, "Megumi Refueling"), (44, "INS Jericho"),
            (45, "Ruin Station"), (46, "Gaslight"), (50, "Stanton Gateway"),
            (51, "Wikelo Emporium Kinga Station"), (52, "Wikelo Emporium Dasi Station"),
            (53, "Wikelo Emporium Selo Station"), (58, "People's Service Station Delta"),
            (59, "People's Service Station Alpha"), (60, "People's Service Station Theta"),
            (61, "People's Service Station Lambda"), (62, "Levksi"),
            (63, "TestStationRenamed"),
        ]:
            db.execute("INSERT OR IGNORE INTO stations (id, name) VALUES (?, ?)", row)
        db.commit()

    if db.execute("SELECT COUNT(*) FROM systems").fetchone()[0] == 0:
        for name in [
            "78 Leonis", "Ail'ka", "Bacchus", "Baker", "Banshee", "Branaugh",
            "Bremen", "Caliban", "Cano", "Castra", "Cathcart", "Centauri",
            "Charon", "Chronos", "Corel", "Croshaw", "Davien", "Eealus",
            "Ellis", "Elsin", "Elysium", "Ferron", "Fora", "GJ-667",
            "Garron", "Geddon", "Genesis", "Gliese", "Goss", "Gurzil",
            "Hades", "Hadrian", "Helios", "Horus", "Hyoton", "Idris",
            "Kabal", "Kai'pua", "Kallis", "Kellog", "Khabari", "Kiel",
            "Kilian", "Kins", "Krell", "Kyuk'ya", "La'uo", "Leir",
            "Magnus", "Markahil", "Min", "Nemo", "Nexus", "Nul", "Nyx",
            "Oberon", "Odin", "Ophos", "Oretani", "Orion", "Osiris",
            "Oso", "Oya", "Pyro", "Rhetor", "Rihlah", "Sol", "Stanton",
            "Tal", "Tamsa", "Tanga", "Taranis", "Tayac", "Terra",
            "Th.us'ūng", "Tiber", "Tohil", "Trise", "Tyrol",
            "UDS-2943-01-22", "Vagabond", "Vanguard", "Vector", "Vega",
            "Vendetta", "Veritas", "Vermilion", "Vesper", "Viking",
            "Virgil", "Virgo", "Volt", "Voodoo", "Vulture", "Yulin",
            "Yā'mon",
        ]:
            db.execute("INSERT OR IGNORE INTO systems (name) VALUES (?)", (name,))
        db.commit()


# --- User helpers ---

def ensure_user(discord_id):
    db = get_db()
    row = db.execute("SELECT discord_id FROM users WHERE discord_id=?", (discord_id,)).fetchone()
    if not row:
        db.execute("INSERT INTO users (discord_id, discord_tag) VALUES (?, ?)",
                   (discord_id, f"Unknown#{discord_id[:4]}"))


@write_db
def upsert_user(discord_id, discord_tag, username, display_name, avatar, access_token, refresh_token,
                token_expires_in, role_ids, is_admin):
    db = get_db()
    db.execute("""INSERT INTO users (discord_id, discord_tag, username, display_name, avatar,
                access_token, refresh_token, token_expires_at, role_ids, is_admin)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(discord_id) DO UPDATE SET
                discord_tag=excluded.discord_tag, username=excluded.username,
                display_name=excluded.display_name,
                avatar=excluded.avatar, access_token=excluded.access_token,
                refresh_token=excluded.refresh_token, token_expires_at=excluded.token_expires_at,
                role_ids=excluded.role_ids, is_admin=excluded.is_admin""",
               (discord_id, discord_tag, username, display_name, avatar, access_token,
                refresh_token, token_expires_in, role_ids, is_admin))
    _assign_user_role(discord_id, role_ids)


def _assign_user_role(discord_id, role_ids):
    db = get_db()
    ids = role_ids.split(",") if role_ids else []
    if not ids:
        return
    best = None
    best_level = -1
    for r in db.execute("SELECT * FROM roles WHERE discord_role_id IS NOT NULL").fetchall():
        if r["discord_role_id"] in ids and r["level"] > best_level:
            best = r["id"]
            best_level = r["level"]
    if best:
        db.execute("UPDATE users SET role_id=?, is_admin=? WHERE discord_id=?",
                   (best, 1 if best_level >= 3 else 0, discord_id))
        db.commit()


def get_user_by_session(session_id):
    db = get_db()
    return db.execute("""SELECT u.*, COALESCE(r.level, 1) AS role_level FROM users u
        JOIN sessions s ON u.discord_id = s.discord_id
        LEFT JOIN roles r ON u.role_id = r.id
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


@write_db
def delete_user_sessions(discord_id):
    get_db().execute("DELETE FROM sessions WHERE discord_id=?", (discord_id,))


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


# --- Client Tokens ---

@write_db
def create_client_token(discord_id, expires_in_days=30):
    from datetime import datetime, timedelta
    import secrets
    token = secrets.token_hex(32)
    expires_at = (datetime.utcnow() + timedelta(days=expires_in_days)).strftime("%Y-%m-%dT%H:%M:%S")
    db = get_db()
    db.execute("INSERT INTO client_tokens (token, discord_id, expires_at) VALUES (?, ?, ?)",
               (token, discord_id, expires_at))
    return token, expires_at


def get_user_by_client_token(token):
    db = get_db()
    return db.execute("""SELECT u.* FROM users u
        JOIN client_tokens t ON u.discord_id = t.discord_id
        WHERE t.token=? AND t.expires_at > datetime('now')""",
        (token,)).fetchone()


def get_client_tokens(discord_id):
    return get_db().execute(
        "SELECT token, created_at, expires_at FROM client_tokens WHERE discord_id=? ORDER BY created_at DESC",
        (discord_id,)).fetchall()


@write_db
def revoke_client_token(token):
    get_db().execute("DELETE FROM client_tokens WHERE token=?", (token,))


# --- My Inventory (user-managed CRUD) ---

@write_db
def add_my_inventory(discord_id, item_name, quality, quantity_scu, station):
    if not _item_exists(item_name):
        return None, f"Item '{item_name}' does not exist. Only items in the local database can be added."
    if station and not _station_exists(station):
        return None, f"Station '{station}' does not exist. Only stations in the local database can be added."
    db = get_db()
    existing = db.execute(
        "SELECT id FROM community_inventory WHERE discord_id=? AND item_name=? AND quality=? AND station=?",
        (discord_id, item_name, quality, station)).fetchone()
    if existing:
        db.execute("UPDATE community_inventory SET quantity_scu=quantity_scu+?, synced_at=datetime('now') WHERE id=?",
                   (quantity_scu, existing["id"]))
        return existing["id"], None
    db.execute("INSERT INTO community_inventory (discord_id, item_name, quality, quantity_scu, station) VALUES (?,?,?,?,?)",
               (discord_id, item_name, quality, quantity_scu, station))
    return db.execute("SELECT last_insert_rowid()").fetchone()[0], None


@write_db
def update_my_inventory(inv_id, discord_id, item_name, quality, quantity_scu, station):
    if not _item_exists(item_name):
        return f"Item '{item_name}' does not exist. Only items in the local database can be added."
    if station and not _station_exists(station):
        return f"Station '{station}' does not exist. Only stations in the local database can be added."
    db = get_db()
    db.execute("UPDATE community_inventory SET item_name=?, quality=?, quantity_scu=?, station=?, synced_at=datetime('now') WHERE id=? AND discord_id=?",
               (item_name, quality, quantity_scu, station, inv_id, discord_id))
    return None


def _ensure_item(name):
    if not name:
        return
    db = get_db()
    existing = db.execute("SELECT id FROM items WHERE name=?", (name,)).fetchone()
    if not existing:
        db.execute("INSERT INTO items (name) VALUES (?)", (name,))
        db.commit()


def _ensure_station(name):
    if not name:
        return
    db = get_db()
    existing = db.execute("SELECT id FROM stations WHERE name=?", (name,)).fetchone()
    if not existing:
        db.execute("INSERT INTO stations (name) VALUES (?)", (name,))
        db.commit()


def _station_exists(name):
    if not name:
        return True
    db = get_db()
    return db.execute("SELECT 1 FROM stations WHERE name=?", (name,)).fetchone() is not None


def get_item_autocomplete(prefix, limit=10):
    db = get_db()
    names = set()
    for r in db.execute(
            "SELECT DISTINCT name FROM items WHERE name LIKE ? ORDER BY name LIMIT ?",
            (f"%{prefix}%", limit)):
        names.add(r["name"])
    if len(names) < limit:
        for r in db.execute(
                "SELECT DISTINCT item_name FROM community_inventory WHERE item_name LIKE ? ORDER BY item_name LIMIT ?",
                (f"%{prefix}%", limit)):
            names.add(r["item_name"])
    return sorted(names)[:limit]


def get_station_autocomplete(prefix, limit=10):
    db = get_db()
    names = set()
    for r in db.execute("SELECT DISTINCT name FROM stations WHERE name LIKE ? ORDER BY name LIMIT ?",
                        (f"%{prefix}%", limit)):
        names.add(r["name"])
    if len(names) < limit:
        for r in db.execute("SELECT DISTINCT station FROM community_inventory WHERE station LIKE ? ORDER BY station LIMIT ?",
                            (f"%{prefix}%", limit)):
            if r["station"]:
                names.add(r["station"])
    return sorted(names)[:limit]


# --- Inventory ---

def _item_exists(name):
    db = get_db()
    return db.execute("SELECT 1 FROM items WHERE name=?", (name,)).fetchone() is not None


@write_db
def sync_inventory(discord_id, item_name, quality, quantity_scu, station):
    if not _item_exists(item_name):
        return {"ok": False, "error": f"Item '{item_name}' does not exist on this SHOWER server. Custom items must be added locally first."}
    if station and not _station_exists(station):
        return {"ok": False, "error": f"Station '{station}' does not exist on this SHOWER server. Custom stations must be added locally first."}
    ensure_user(discord_id)
    db = get_db()
    existing = db.execute(
        "SELECT id, quantity_scu FROM community_inventory WHERE discord_id=? AND item_name=? AND quality=? AND station=?",
        (discord_id, item_name, quality, station)).fetchone()
    if existing:
        db.execute("UPDATE community_inventory SET quantity_scu=quantity_scu+?, synced_at=datetime('now') WHERE id=?",
                   (quantity_scu, existing["id"]))
    else:
        db.execute("""INSERT INTO community_inventory (discord_id, item_name, quality, quantity_scu, station)
                   VALUES (?,?,?,?,?)""", (discord_id, item_name, quality, quantity_scu, station))
    return {"ok": True}


def get_inventory_item(discord_id, inventory_id):
    return get_db().execute(
        "SELECT * FROM community_inventory WHERE id=? AND discord_id=?",
        (inventory_id, discord_id)
    ).fetchone()


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


def all_inventory(limit=200, search=None, qual_min=None, qual_max=None, qty_min=None):
    db = get_db()
    clauses = []
    params = []
    if search:
        clauses.append("ci.item_name LIKE ?")
        params.append(f"%{search}%")
    if qual_min is not None:
        clauses.append("ci.quality >= ?")
        params.append(qual_min)
    if qual_max is not None:
        clauses.append("ci.quality <= ?")
        params.append(qual_max)
    if qty_min is not None:
        clauses.append("ci.quantity_scu >= ?")
        params.append(qty_min)
    where = ""
    if clauses:
        where = "WHERE " + " AND ".join(clauses)
    params.append(limit)
    return db.execute(
        f"""SELECT ci.*, COALESCE(u.display_name, u.discord_tag) AS display_name FROM community_inventory ci
        LEFT JOIN users u ON ci.discord_id = u.discord_id
        {where} ORDER BY ci.synced_at DESC LIMIT ?""",
        params).fetchall()


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


# --- Stats ---

def get_active_users_count():
    db = get_db()
    row = db.execute("""SELECT COUNT(DISTINCT discord_id) FROM (
        SELECT discord_id FROM community_inventory WHERE synced_at > datetime('now', '-30 days')
        UNION
        SELECT discord_id FROM order_requests WHERE created_at > datetime('now', '-30 days')
    )""").fetchone()
    return row[0] or 0


def get_total_scu():
    row = get_db().execute("SELECT COALESCE(SUM(quantity_scu), 0) FROM community_inventory").fetchone()
    return row[0] or 0


def get_latest_action_time():
    db = get_db()
    row = db.execute("""SELECT MAX(ts) FROM (
        SELECT MAX(synced_at) AS ts FROM community_inventory
        UNION
        SELECT MAX(created_at) AS ts FROM order_requests
        UNION
        SELECT MAX(fulfilled_at) AS ts FROM order_requests
    )""").fetchone()
    return row[0] or ""


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


# --- Roles ---

def _seed_defaults():
    db = get_db()
    defaults = [("Blocked", 0), ("User", 1), ("Mod", 2), ("Admin", 3)]
    for name, level in defaults:
        db.execute("INSERT OR IGNORE INTO roles (name, level) VALUES (?, ?)", (name, level))
    db.commit()
    admin_role_id = os.environ.get("DISCORD_ADMIN_ROLE", "")
    if admin_role_id:
        db.execute("UPDATE roles SET discord_role_id=?, is_env=1 WHERE name='Admin'", (admin_role_id,))
        db.commit()


def get_roles():
    return get_db().execute("SELECT * FROM roles ORDER BY is_env ASC, level ASC").fetchall()


@write_db
def add_role(name, level, discord_role_id=None):
    get_db().execute(
        "INSERT INTO roles (name, level, discord_role_id) VALUES (?, ?, ?)",
        (name, level, discord_role_id),
    )


@write_db
def update_role(role_id, name, level):
    get_db().execute("UPDATE roles SET name=?, level=? WHERE id=? AND is_env=0",
                     (name, level, role_id))


@write_db
def delete_role(role_id):
    get_db().execute("DELETE FROM roles WHERE id=? AND is_env=0", (role_id,))


def get_user_role_level(discord_id):
    db = get_db()
    row = db.execute(
        "SELECT r.level FROM users u JOIN roles r ON u.role_id=r.id WHERE u.discord_id=?",
        (discord_id,),
    ).fetchone()
    if row:
        return row["level"]
    return 1


def is_banned(discord_id):
    row = get_db().execute("SELECT banned FROM users WHERE discord_id=?", (discord_id,)).fetchone()
    return bool(row and row["banned"])


# --- User Management ---

def get_all_users():
    return get_db().execute(
        """SELECT u.*, r.name AS role_name, r.level AS role_level
        FROM users u LEFT JOIN roles r ON u.role_id=r.id
        ORDER BY u.created_at DESC"""
    ).fetchall()


@write_db
def set_user_role(discord_id, role_id):
    ensure_user(discord_id)
    get_db().execute("UPDATE users SET role_id=? WHERE discord_id=?", (role_id, discord_id))


@write_db
def set_user_banned(discord_id, banned):
    get_db().execute("UPDATE users SET banned=? WHERE discord_id=?", (1 if banned else 0, discord_id))


@write_db
def clear_user_token(discord_id):
    get_db().execute("UPDATE users SET access_token='', refresh_token='' WHERE discord_id=?", (discord_id,))
    get_db().execute("DELETE FROM client_tokens WHERE discord_id=?", (discord_id,))
    get_db().execute("DELETE FROM sessions WHERE discord_id=?", (discord_id,))


@write_db
def delete_user_record(discord_id):
    get_db().execute("DELETE FROM notifications WHERE discord_id=?", (discord_id,))
    get_db().execute("DELETE FROM sessions WHERE discord_id=?", (discord_id,))
    get_db().execute("DELETE FROM client_tokens WHERE discord_id=?", (discord_id,))
    get_db().execute("DELETE FROM api_keys WHERE discord_id=?", (discord_id,))
    get_db().execute("DELETE FROM community_inventory WHERE discord_id=?", (discord_id,))
    get_db().execute("DELETE FROM order_requests WHERE discord_id=?", (discord_id,))
    get_db().execute("DELETE FROM users WHERE discord_id=?", (discord_id,))


@write_db
def update_last_seen(discord_id):
    get_db().execute("UPDATE users SET last_seen=datetime('now') WHERE discord_id=?", (discord_id,))


# --- Custom Fields (items & stations) ---

def get_all_items():
    return get_db().execute("SELECT * FROM items ORDER BY name").fetchall()


@write_db
def add_custom_item(name):
    get_db().execute("INSERT OR IGNORE INTO items (name) VALUES (?)", (name,))


@write_db
def delete_custom_item(item_id):
    get_db().execute("DELETE FROM items WHERE id=?", (item_id,))


def get_all_stations():
    return get_db().execute("SELECT * FROM stations ORDER BY name").fetchall()


@write_db
def add_custom_station(name):
    get_db().execute("INSERT OR IGNORE INTO stations (name) VALUES (?)", (name,))


@write_db
def delete_custom_station(station_id):
    get_db().execute("DELETE FROM stations WHERE id=?", (station_id,))


# --- Config ---

def get_config(key, default=""):
    row = get_db().execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


@write_db
def set_config(key, value):
    get_db().execute(
        "INSERT INTO config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


@write_db
def delete_config(key):
    get_db().execute("DELETE FROM config WHERE key=?", (key,))
