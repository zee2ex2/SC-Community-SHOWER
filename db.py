import os
import secrets
import threading
import sqlite3
import queue
from pathlib import Path

_DSN = os.environ.get("SHOWER_DB", str(Path(__file__).resolve().parent / "shower_data" / "shower.db"))
_IS_MYSQL = _DSN.startswith("mysql://")
_IS_ODBC = not _IS_MYSQL and ("Driver=" in _DSN or "driver=" in _DSN)
_local = threading.local()
_local_tx = threading.local()
_write_lock = threading.RLock()

# Connection pools (lazy-initialized)
_pool = None
_pool_lock = None

if _IS_MYSQL:
    import pymysql
    _pool = queue.Queue(maxsize=20)
    _pool_lock = threading.Lock()
elif _IS_ODBC:
    _pool = None
    _pool_lock = None

def _new_conn():
    if _IS_MYSQL:
        import pymysql
        import urllib.parse
        p = urllib.parse.urlparse(_DSN)
        return pymysql.connect(
            host=p.hostname or "localhost", port=p.port or 3306,
            user=p.username or "root", password=p.password or "",
            database=p.path.lstrip("/") or "shower",
            charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor, autocommit=False,
        )
    if _IS_ODBC:
        import pyodbc
        import time as _time
        # Patch pyodbc rows to support dict-style access
        if not hasattr(pyodbc, '_dict_patched'):
            pyodbc._dict_patched = True
            _orig_fetchone = pyodbc.Cursor.fetchone
            _orig_fetchall = pyodbc.Cursor.fetchall
            def _dict_fetchone(self):
                row = _orig_fetchone(self)
                return dict(row) if row else None
            def _dict_fetchall(self):
                rows = _orig_fetchall(self)
                return [dict(r) for r in rows]
            pyodbc.Cursor.fetchone = _dict_fetchone
            pyodbc.Cursor.fetchall = _dict_fetchall
        try:
            return pyodbc.connect(_DSN, autocommit=False, timeout=10)
        except pyodbc.InterfaceError as e:
            import sys
            print(f"[db] ODBC connection failed: {e}", flush=True)
            try:
                drivers = pyodbc.drivers()
                print(f"[db] Available ODBC drivers: {drivers}", flush=True)
            except Exception:
                pass
            raise
        except pyodbc.OperationalError as e:
            print(f"[db] ODBC connection timeout/refused. Check that the Azure SQL firewall allows App Service traffic. Error: {e}", flush=True)
            raise

def get_db():
    # If inside a write_db transaction, return that connection
    if hasattr(_local_tx, "conn") and _local_tx.conn is not None:
        return _local_tx.conn
    if _IS_MYSQL:
        try:
            return _pool.get_nowait()
        except queue.Empty:
            return _new_conn()
    if _IS_ODBC:
        return _new_conn()
    if not hasattr(_local, "conn") or _local.conn is None:
        if not _DSN.startswith("/"):
            Path(_DSN).parent.mkdir(parents=True, exist_ok=True)
        _local.conn = sqlite3.connect(_DSN, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn

def _put_db(conn):
    # Don't close connections owned by an active transaction
    if hasattr(_local_tx, "conn") and _local_tx.conn is conn:
        return
    if _IS_MYSQL:
        _pool.put(conn)
    elif _IS_ODBC:
        conn.close()

if _IS_MYSQL:
    Q = "%s"
    NOW = "NOW()"
    NOW_N = lambda s: f"(NOW() + INTERVAL {s} SECOND)"
    NOW_M = lambda d: f"(NOW() - INTERVAL {d} DAY)"
    IGNORE = "INSERT IGNORE"
    LASTID = "LAST_INSERT_ID()"
    COLINFO = lambda t: f"SHOW COLUMNS FROM `{t}`"
    UPSERT = lambda t, p: "ON DUPLICATE KEY UPDATE"
    EXCLUDED = lambda col: f"VALUES({col})"
    LIMIT_CLAUSE = lambda p: f"LIMIT {p}"
elif _IS_ODBC:
    Q = "?"
    NOW = "GETDATE()"
    NOW_N = lambda s: f"DATEADD(SECOND, {s}, GETDATE())"
    NOW_M = lambda d: f"DATEADD(DAY, -{d}, GETDATE())"
    IGNORE = "INSERT"  # SQL Server: bare INSERT (no IGNORE); gated by existence checks
    LASTID = "CAST(COALESCE(SCOPE_IDENTITY(), @@IDENTITY) AS BIGINT)"
    COLINFO = lambda t: f"SELECT c.name FROM sys.columns c JOIN sys.tables t ON c.object_id=t.object_id WHERE t.name='{t}'"
    UPSERT = lambda t, p: ""  # Not used in ODBC path
    EXCLUDED = lambda col: f"EXCLUDED.{col}"
    LIMIT_CLAUSE = lambda p: f"OFFSET 0 ROWS FETCH NEXT {p} ROWS ONLY"
else:
    Q = "?"
    NOW = "datetime('now')"
    NOW_N = lambda s: f"datetime('now', '+{s} seconds')"
    NOW_M = lambda d: f"datetime('now', '-{d} days')"
    IGNORE = "INSERT OR IGNORE"
    LASTID = "last_insert_rowid()"
    COLINFO = lambda t: f"PRAGMA table_info({t})"
    UPSERT = lambda t, p: f"ON CONFLICT({p}) DO UPDATE SET"
    EXCLUDED = lambda col: f"excluded.{col}"
    LIMIT_CLAUSE = lambda p: f"LIMIT {p}"

DB_PATH = _DSN
SHOWER_VERSION = "0.2.0"
SCHEMA_VERSION = 3


def write_db(func):
    def wrapper(*args, **kwargs):
        db = get_db()
        _local_tx.conn = db
        try:
            result = func(*args, **kwargs)
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise
        finally:
            _local_tx.conn = None
            _put_db(db)
    return wrapper


def _cols(table):
    db = get_db()
    data = db.execute(COLINFO(table)).fetchall()
    _put_db(db)
    if _IS_MYSQL:
        return [r["Field"] for r in data]
    if _IS_ODBC:
        names = [r[0] for r in data]
        print(f"[db] _cols({table}): {names}", flush=True)
        return names
    return [r[1] for r in data]


# ─── Schema ──────────────────────────────────────────────────────────

def init_db():
    db = get_db()
    if _IS_ODBC:
        AI = "IDENTITY(1,1)"
        PKI = "INT IDENTITY(1,1) PRIMARY KEY"
        CT = "GETDATE()"
        TS = "DATETIME2"
        CTIF = "CREATE TABLE"
        QID = lambda x: f"[{x}]"
    elif _IS_MYSQL:
        AI = "AUTO_INCREMENT"
        PKI = f"INTEGER PRIMARY KEY {AI}"
        CT = "CURRENT_TIMESTAMP"
        TS = "TIMESTAMP"
        CTIF = "CREATE TABLE IF NOT EXISTS"
        QID = lambda x: f"`{x}`"
    else:
        AI = "AUTOINCREMENT"
        PKI = f"INTEGER PRIMARY KEY {AI}"
        CT = "CURRENT_TIMESTAMP"
        TS = "TIMESTAMP"
        CTIF = "CREATE TABLE IF NOT EXISTS"
        QID = lambda x: x
    schema = f"""
    {CTIF} users (
        discord_id VARCHAR(64) PRIMARY KEY,
        discord_tag VARCHAR(128),
        username VARCHAR(128),
        display_name VARCHAR(128),
        avatar TEXT,
        access_token TEXT,
        refresh_token TEXT,
        token_expires_at INTEGER DEFAULT 0,
        role_ids TEXT DEFAULT '',
        role_id INTEGER,
        is_admin INTEGER DEFAULT 0,
        banned INTEGER DEFAULT 0,
        last_seen {TS},
        created_at {TS} DEFAULT {CT}
    );
    {CTIF} sessions (
        session_id VARCHAR(64) PRIMARY KEY,
        discord_id VARCHAR(64) NOT NULL,
        expires_at {TS},
        created_at {TS} DEFAULT {CT}
    );
    {CTIF} items (
        id {PKI},
        name VARCHAR(255) UNIQUE NOT NULL,
        category TEXT DEFAULT ''
    );
    {CTIF} systems (
        id {PKI},
        name VARCHAR(255) UNIQUE NOT NULL
    );
    {CTIF} stations (
        id {PKI},
        name VARCHAR(255) UNIQUE NOT NULL,
        system_id INTEGER
    );
    {CTIF} community_inventory (
        id {PKI},
        discord_id VARCHAR(64) NOT NULL,
        item_name VARCHAR(255) NOT NULL,
        quality INTEGER DEFAULT 100,
        quantity_scu REAL DEFAULT 1.0,
        station TEXT DEFAULT '',
        synced_at {TS} DEFAULT {CT}
    );
    {CTIF} order_requests (
        id {PKI},
        discord_id VARCHAR(64) NOT NULL,
        item_name VARCHAR(255) NOT NULL,
        min_quality INTEGER DEFAULT 1,
        quantity INTEGER DEFAULT 1,
        notes TEXT DEFAULT '',
        status TEXT DEFAULT 'open',
        assigned_discord_id VARCHAR(64),
        created_at {TS} DEFAULT {CT},
        fulfilled_at {TS}
    );
    {CTIF} notifications (
        id {PKI},
        discord_id VARCHAR(64) NOT NULL,
        title TEXT NOT NULL,
        body TEXT DEFAULT '',
        source TEXT DEFAULT 'system',
        {QID('read')} INTEGER DEFAULT 0,
        created_at {TS} DEFAULT {CT}
    );
    {CTIF} sync_log (
        id {PKI},
        discord_id VARCHAR(64),
        direction TEXT,
        status TEXT,
        message TEXT,
        synced_at {TS} DEFAULT {CT}
    );
    {CTIF} config (
        {QID('key')} VARCHAR(255) PRIMARY KEY,
        value TEXT
    );
    {CTIF} api_keys (
        {QID('key')} VARCHAR(64) PRIMARY KEY,
        discord_id VARCHAR(64) NOT NULL,
        label TEXT DEFAULT '',
        last_used {TS},
        expires_at {TS},
        created_at {TS} DEFAULT {CT}
    );
    {CTIF} client_tokens (
        token VARCHAR(64) PRIMARY KEY,
        discord_id VARCHAR(64) NOT NULL,
        created_at {TS} DEFAULT {CT},
        expires_at {TS} NOT NULL
    );
    {CTIF} roles (
        id {PKI},
        name VARCHAR(255) UNIQUE NOT NULL,
        level INTEGER NOT NULL DEFAULT 1,
        discord_role_id VARCHAR(64),
        is_env INTEGER DEFAULT 0,
        created_at {TS} DEFAULT {CT}
    );
    {CTIF} itemcategory (
        id {PKI},
        name VARCHAR(255) NOT NULL,
        parent_id INTEGER DEFAULT 0
    );
    """
    for stmt in schema.split(";"):
        s = stmt.strip()
        if s:
            try:
                db.execute(s)
            except Exception as e:
                if _IS_ODBC:
                    print(f"[db] DDL error: {e}", flush=True)
    db.commit()
    _put_db(db)
    import time
    time.sleep(1)
    _migrate()
    _seed_defaults()
    existing_ver = int(get_config("schema_version", "0"))
    if existing_ver < SCHEMA_VERSION:
        set_config("schema_version", str(SCHEMA_VERSION))


def _migrate():
    AC = "ADD" if _IS_ODBC else "ADD COLUMN"
    cols_i = _cols("items")
    if "hasquality" not in cols_i:
        db = get_db()
        try:
            db.execute(f"ALTER TABLE items {AC} hasquality INTEGER DEFAULT 0")
            db.commit()
        except Exception as e:
            print(f"[db] migrate items.hasquality: {e}", flush=True)
        _put_db(db)
    if "code" not in cols_i:
        db = get_db()
        try:
            db.execute(f"ALTER TABLE items {AC} code TEXT DEFAULT ''")
            db.commit()
        except Exception as e:
            print(f"[db] migrate items.code: {e}", flush=True)
        _put_db(db)
    if "catid" not in cols_i:
        db = get_db()
        try:
            db.execute(f"ALTER TABLE items {AC} catid INTEGER DEFAULT 1")
            db.commit()
        except Exception as e:
            print(f"[db] migrate items.catid: {e}", flush=True)
        _put_db(db)

    cols_u = _cols("users")
    ts_type = "DATETIME2" if _IS_ODBC else "TIMESTAMP"
    for col, dtype in [("display_name", "TEXT"), ("role_id", "INTEGER"), ("banned", "INTEGER DEFAULT 0"), ("last_seen", ts_type)]:
        if col not in cols_u:
            db = get_db()
            try:
                db.execute(f"ALTER TABLE users {AC} {col} {dtype}")
                db.commit()
            except Exception as e:
                print(f"[db] migrate users.{col}: {e}", flush=True)
            _put_db(db)

    cols_n = _cols("notifications")
    if cols_n and "dm_sent" not in cols_n:
        db = get_db()
        try:
            db.execute(f"ALTER TABLE notifications {AC} dm_sent INTEGER DEFAULT 0")
            db.commit()
        except Exception as e:
            print(f"[db] migrate notifications.dm_sent: {e}", flush=True)
        _put_db(db)

    # Fix sessions table for ODBC: ensure DATETIME2, not ROWVERSION
    if _IS_ODBC:
        db = get_db()
        try:
            db.execute("DROP TABLE IF EXISTS sessions")
            db.execute(f"""CREATE TABLE sessions (
                session_id VARCHAR(64) PRIMARY KEY,
                discord_id VARCHAR(64) NOT NULL,
                expires_at DATETIME2,
                created_at DATETIME2 DEFAULT GETDATE()
            )""")
            db.commit()
            print(f"[db] Sessions table created with DATETIME2", flush=True)
        except Exception as e:
            print(f"[db] recreate sessions: {e}", flush=True)
        _put_db(db)

    # Seed itemcategory
    db = get_db()
    row = db.execute(f"SELECT COUNT(*) AS cnt FROM itemcategory").fetchone()
    if row and row["cnt"] == 0:
        for ic in [(1, "Commodity", 0), (2, "Ores", 1), (3, "Vehicle Mining", 1),
                   (4, "FPS Mining", 1), (5, "Harvestable", 1), (6, "Salvage", 1)]:
            db.execute(f"{IGNORE} INTO itemcategory (id, name, parent_id) VALUES ({Q},{Q},{Q})", ic)
    db.commit()
    _put_db(db)

    # Seed items if empty
    db = get_db()
    row = db.execute(f"SELECT COUNT(*) AS cnt FROM items").fetchone()
    if row and row["cnt"] == 0:
        seed_items = [
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
        ]
        for row in seed_items:
            db.execute(f"{IGNORE} INTO items (id, name) VALUES ({Q},{Q})", row)
        db.execute(f"{IGNORE} INTO items (name) VALUES ('Zeta-Prolanite')")
    db.commit()

    # Set catid and hasquality
    db.execute(f"UPDATE items SET hasquality=1 WHERE catid IN (2,3,4)")
    cat_map = {
        2: [1, 5, 7, 11, 13, 15, 20, 22, 33, 39, 101, 44, 47, 184, 194, 58, 60, 124, 188, 100, 122, 73, 103, 75, 190, 77],
        3: [167, 170, 169, 168],
        4: [8, 179, 178, 28, 36, 171, 46, 200, 172],
        5: [105, 24, 35, 37, 55, 57, 65, 66, 72, 198, 18],
        6: [63, 181, 182, 183],
    }
    for catid, ids in cat_map.items():
        for iid in ids:
            db.execute(f"UPDATE items SET catid={Q} WHERE id={Q}", (catid, iid))
    for row in [(172, "Saldynium", 4, "SALD"), (178, "Carinite Pure", 4, "CARIP")]:
        db.execute(f"{IGNORE} INTO items (id, name, catid, code, hasquality) VALUES ({Q},{Q},{Q},{Q},1)", row)
    for name, code in [("Amiant", "AMIA"), ("Flareweed", "FLWD"), ("Fotia", "FTIA"), ("Pingala", "PNGL")]:
        existing = db.execute(f"SELECT id FROM items WHERE name={Q}", (name,)).fetchone()
        if not existing:
            db.execute(f"INSERT INTO items (name, catid, code, hasquality) VALUES ({Q}, 4, {Q}, 1)", (name, code))
    db.commit()
    _put_db(db)

    # Stations
    db = get_db()
    row = db.execute(f"SELECT COUNT(*) AS cnt FROM stations").fetchone()
    if row and row["cnt"] == 0:
        stations = [
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
        ]
        for row in stations:
            db.execute(f"{IGNORE} INTO stations (id, name) VALUES ({Q},{Q})", row)
    db.commit()
    _put_db(db)

    # Systems
    db = get_db()
    row = db.execute(f"SELECT COUNT(*) AS cnt FROM systems").fetchone()
    if row and row["cnt"] == 0:
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
            db.execute(f"{IGNORE} INTO systems (name) VALUES ({Q})", (name,))
    db.commit()
    _put_db(db)


# ─── User helpers ────────────────────────────────────────────────────

def ensure_user(discord_id):
    db = get_db()
    row = db.execute(f"SELECT discord_id FROM users WHERE discord_id={Q}", (discord_id,)).fetchone()
    if not row:
        db.execute(f"INSERT INTO users (discord_id, discord_tag) VALUES ({Q},{Q})",
                   (discord_id, f"Unknown#{discord_id[:4]}"))
    _put_db(db)


@write_db
def upsert_user(discord_id, discord_tag, username, display_name, avatar, access_token, refresh_token,
                token_expires_in, role_ids, is_admin):
    db = get_db()
    existing = db.execute(f"SELECT discord_id FROM users WHERE discord_id={Q}", (discord_id,)).fetchone()
    if existing:
        db.execute(f"""UPDATE users SET discord_tag={Q}, username={Q}, display_name={Q}, avatar={Q},
                    access_token={Q}, refresh_token={Q}, token_expires_at={Q}, role_ids={Q}, is_admin={Q}
                    WHERE discord_id={Q}""",
                   (discord_tag, username, display_name, avatar, access_token,
                    refresh_token, token_expires_in, role_ids, is_admin, discord_id))
    else:
        db.execute(f"""INSERT INTO users (discord_id, discord_tag, username, display_name, avatar,
                    access_token, refresh_token, token_expires_at, role_ids, is_admin)
                    VALUES ({Q},{Q},{Q},{Q},{Q},{Q},{Q},{Q},{Q},{Q})""",
                   (discord_id, discord_tag, username, display_name, avatar, access_token,
                    refresh_token, token_expires_in, role_ids, is_admin))
    _assign_user_role(discord_id, role_ids)


def _assign_user_role(discord_id, role_ids):
    db = get_db()
    ids = role_ids.split(",") if role_ids else []
    if not ids:
        _put_db(db)
        return
    for r in db.execute("SELECT * FROM roles WHERE discord_role_id IS NOT NULL").fetchall():
        if r["discord_role_id"] in ids:
            best_level = r["level"]
            db.execute(f"UPDATE users SET role_id={Q}, is_admin={Q} WHERE discord_id={Q}",
                       (r["id"], 1 if best_level >= 3 else 0, discord_id))
            db.commit()
            break
    _put_db(db)


def get_user_by_session(session_id):
    db = get_db()
    try:
        if _IS_ODBC:
            # Check session directly without JOIN
            s_row = db.execute(f"SELECT session_id, discord_id, expires_at FROM sessions WHERE session_id={Q}", (session_id,)).fetchone()
            if s_row:
                print(f"[db] session found: discord_id={s_row[1][:16] if len(s_row)>1 else '?'}...", flush=True)
                # Check if user exists
                u_row = db.execute(f"SELECT discord_id, role_id FROM users WHERE discord_id={Q}", (s_row[1],)).fetchone()
                print(f"[db] user found: {bool(u_row)}, role_id={u_row[1] if u_row else 'N/A'}", flush=True)
            else:
                print(f"[db] session NOT FOUND in direct query", flush=True)
        sql = f"""SELECT u.*, COALESCE(r.level, 1) AS role_level FROM users u
            JOIN sessions s ON u.discord_id = s.discord_id
            LEFT JOIN roles r ON u.role_id = r.id
            WHERE s.session_id={Q} AND (s.expires_at IS NULL OR s.expires_at > {NOW})"""
        row = db.execute(sql, (session_id,)).fetchone()
        if _IS_ODBC:
            print(f"[db] get_user_by_session join: {'found' if row else 'NOT FOUND'}", flush=True)
    except Exception as e:
        print(f"[db] get_user_by_session error: {e}", flush=True)
        row = None
    _put_db(db)
    return row


# ─── Sessions ────────────────────────────────────────────────────────

@write_db
def create_session(session_id, discord_id, ttl):
    db = get_db()
    sql = f"INSERT INTO sessions (session_id, discord_id, expires_at) VALUES ({Q}, {Q}, {NOW_N(ttl)})"
    print(f"[db] create_session: {session_id[:16]}... discord={discord_id[:16]}... ttl={ttl}", flush=True)
    if _IS_ODBC:
        print(f"[db] create_session SQL: {sql}", flush=True)
    db.execute(sql, (session_id, discord_id))


@write_db
def delete_session(session_id):
    get_db().execute(f"DELETE FROM sessions WHERE session_id={Q}", (session_id,))


@write_db
def delete_user_sessions(discord_id):
    get_db().execute(f"DELETE FROM sessions WHERE discord_id={Q}", (discord_id,))


# ─── API Keys ────────────────────────────────────────────────────────

@write_db
def create_api_key(discord_id, label=""):
    key = secrets.token_hex(32)
    db = get_db()
    db.execute(f"INSERT INTO api_keys (key, discord_id, label) VALUES ({Q},{Q},{Q})",
               (key, discord_id, label))
    return key


@write_db
def revoke_api_key(key, discord_id):
    get_db().execute(f"DELETE FROM api_keys WHERE key={Q} AND discord_id={Q}", (key, discord_id))


def get_user_by_api_key(key):
    db = get_db()
    row = db.execute(f"""SELECT u.* FROM users u
        JOIN api_keys k ON u.discord_id = k.discord_id
        WHERE k.key={Q} AND (k.expires_at IS NULL OR k.expires_at > {NOW})""",
        (key,)).fetchone()
    if row:
        db.execute(f"UPDATE api_keys SET last_used={NOW} WHERE key={Q}", (key,))
        db.commit()
    _put_db(db)
    return row


def get_api_keys(discord_id):
    db = get_db()
    rows = db.execute(f"SELECT * FROM api_keys WHERE discord_id={Q} ORDER BY created_at DESC", (discord_id,)).fetchall()
    _put_db(db)
    return rows


# ─── Client Tokens ───────────────────────────────────────────────────

@write_db
def create_client_token(discord_id, expires_in_days=30):
    from datetime import datetime, timedelta
    token = secrets.token_hex(32)
    expires_at = (datetime.utcnow() + timedelta(days=expires_in_days)).strftime("%Y-%m-%dT%H:%M:%S")
    db = get_db()
    db.execute(f"INSERT INTO client_tokens (token, discord_id, expires_at) VALUES ({Q},{Q},{Q})",
               (token, discord_id, expires_at))
    return token, expires_at


def get_user_by_client_token(token):
    db = get_db()
    row = db.execute(f"""SELECT u.* FROM users u
        JOIN client_tokens t ON u.discord_id = t.discord_id
        WHERE t.token={Q} AND t.expires_at > {NOW}""",
        (token,)).fetchone()
    _put_db(db)
    return row


@write_db
def revoke_client_token(token):
    get_db().execute(f"DELETE FROM client_tokens WHERE token={Q}", (token,))


# ─── My Inventory ────────────────────────────────────────────────────

@write_db
def add_my_inventory(discord_id, item_name, quality, quantity_scu, station):
    if not _item_exists(item_name):
        return None, f"Item '{item_name}' does not exist."
    if station and not _station_exists(station):
        return None, f"Station '{station}' does not exist."
    db = get_db()
    existing = db.execute(
        f"SELECT id FROM community_inventory WHERE discord_id={Q} AND item_name={Q} AND quality={Q} AND station={Q}",
        (discord_id, item_name, quality, station)).fetchone()
    if existing:
        db.execute(f"UPDATE community_inventory SET quantity_scu=quantity_scu+{Q}, synced_at={NOW} WHERE id={Q}",
                   (quantity_scu, existing["id"]))
        return existing["id"], None
    db.execute(f"INSERT INTO community_inventory (discord_id, item_name, quality, quantity_scu, station) VALUES ({Q},{Q},{Q},{Q},{Q})",
               (discord_id, item_name, quality, quantity_scu, station))
    row = db.execute(f"SELECT {LASTID} AS id").fetchone()
    return row["id"], None


def _ensure_item(name):
    if not name:
        return
    db = get_db()
    existing = db.execute(f"SELECT id FROM items WHERE name={Q}", (name,)).fetchone()
    if not existing:
        db.execute(f"INSERT INTO items (name) VALUES ({Q})", (name,))
        db.commit()
    _put_db(db)


def _ensure_station(name):
    if not name:
        return
    db = get_db()
    existing = db.execute(f"SELECT id FROM stations WHERE name={Q}", (name,)).fetchone()
    if not existing:
        db.execute(f"INSERT INTO stations (name) VALUES ({Q})", (name,))
        db.commit()
    _put_db(db)


def _station_exists(name):
    if not name:
        return True
    db = get_db()
    r = db.execute(f"SELECT 1 AS ok FROM stations WHERE name={Q}", (name,)).fetchone()
    _put_db(db)
    return r is not None


def _item_exists(name):
    db = get_db()
    r = db.execute(f"SELECT 1 AS ok FROM items WHERE name={Q}", (name,)).fetchone()
    _put_db(db)
    return r is not None


def get_item_autocomplete(prefix, limit=10):
    db = get_db()
    names = set()
    for r in db.execute(f"SELECT DISTINCT name FROM items WHERE name LIKE {Q} ORDER BY name {LIMIT_CLAUSE(Q)}",
                        (f"%{prefix}%", limit)):
        names.add(r["name"])
    if len(names) < limit:
        for r in db.execute(f"SELECT DISTINCT item_name FROM community_inventory WHERE item_name LIKE {Q} ORDER BY item_name {LIMIT_CLAUSE(Q)}",
                            (f"%{prefix}%", limit)):
            names.add(r["item_name"])
    _put_db(db)
    return sorted(names)[:limit]


def get_station_autocomplete(prefix, limit=10):
    db = get_db()
    names = set()
    for r in db.execute(f"SELECT DISTINCT name FROM stations WHERE name LIKE {Q} ORDER BY name {LIMIT_CLAUSE(Q)}",
                        (f"%{prefix}%", limit)):
        names.add(r["name"])
    if len(names) < limit:
        for r in db.execute(f"SELECT DISTINCT station FROM community_inventory WHERE station LIKE {Q} ORDER BY station {LIMIT_CLAUSE(Q)}",
                            (f"%{prefix}%", limit)):
            if r["station"]:
                names.add(r["station"])
    _put_db(db)
    return sorted(names)[:limit]


# ─── Inventory Sync ──────────────────────────────────────────────────

@write_db
def sync_inventory(discord_id, item_name, quality, quantity_scu, station):
    if not _item_exists(item_name):
        return {"ok": False, "error": f"Item '{item_name}' does not exist."}
    if station and not _station_exists(station):
        return {"ok": False, "error": f"Station '{station}' does not exist."}
    ensure_user(discord_id)
    db = get_db()
    existing = db.execute(
        f"SELECT id, quantity_scu FROM community_inventory WHERE discord_id={Q} AND item_name={Q} AND quality={Q} AND station={Q}",
        (discord_id, item_name, quality, station)).fetchone()
    if existing:
        db.execute(f"UPDATE community_inventory SET quantity_scu=quantity_scu+{Q}, synced_at={NOW} WHERE id={Q}",
                   (quantity_scu, existing["id"]))
    else:
        db.execute(f"INSERT INTO community_inventory (discord_id, item_name, quality, quantity_scu, station) VALUES ({Q},{Q},{Q},{Q},{Q})",
                   (discord_id, item_name, quality, quantity_scu, station))
    return {"ok": True}


def get_inventory_item(discord_id, inventory_id):
    db = get_db()
    row = db.execute(f"SELECT * FROM community_inventory WHERE id={Q} AND discord_id={Q}",
                     (inventory_id, discord_id)).fetchone()
    _put_db(db)
    return row


@write_db
def delete_inventory_item(discord_id, inventory_id):
    ensure_user(discord_id)
    get_db().execute(f"DELETE FROM community_inventory WHERE id={Q} AND discord_id={Q}",
                     (inventory_id, discord_id))


def get_user_inventory(discord_id, limit=None):
    db = get_db()
    q = f"SELECT * FROM community_inventory WHERE discord_id={Q} ORDER BY synced_at DESC"
    params = [discord_id]
    if limit:
        q += f" {LIMIT_CLAUSE(Q)}"
        params.append(limit)
    rows = db.execute(q, params).fetchall()
    _put_db(db)
    return rows


def all_inventory(limit=200, search=None, qual_min=None, qual_max=None, qty_min=None):
    db = get_db()
    clauses = []
    params = []
    if search:
        clauses.append(f"ci.item_name LIKE {Q}")
        params.append(f"%{search}%")
    if qual_min is not None:
        clauses.append(f"ci.quality >= {Q}")
        params.append(qual_min)
    if qual_max is not None:
        clauses.append(f"ci.quality <= {Q}")
        params.append(qual_max)
    if qty_min is not None:
        clauses.append(f"ci.quantity_scu >= {Q}")
        params.append(qty_min)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(limit)
    rows = db.execute(
        f"""SELECT ci.*, COALESCE(u.display_name, u.discord_tag) AS display_name FROM community_inventory ci
        LEFT JOIN users u ON ci.discord_id = u.discord_id
        {where} ORDER BY ci.synced_at DESC {LIMIT_CLAUSE(Q)}""",
        params).fetchall()
    _put_db(db)
    return rows


# ─── Orders ──────────────────────────────────────────────────────────

@write_db
def create_order(discord_id, item_name, min_quality, quantity, notes=""):
    ensure_user(discord_id)
    db = get_db()
    db.execute(f"INSERT INTO order_requests (discord_id, item_name, min_quality, quantity, notes) VALUES ({Q},{Q},{Q},{Q},{Q})",
               (discord_id, item_name, min_quality, quantity, notes))
    order_id = db.execute(f"SELECT {LASTID} AS id").fetchone()["id"]
    _notify_all(f"New Order: {item_name}", f"{item_name} (Q{min_quality}+, x{quantity}) requested.")
    return order_id


@write_db
def fulfill_order(order_id, fulfiller_discord_id):
    ensure_user(fulfiller_discord_id)
    db = get_db()
    order = db.execute(f"SELECT * FROM order_requests WHERE id={Q}", (order_id,)).fetchone()
    if not order:
        return None, "Order not found"
    if order["status"] != "open":
        return None, "Order already fulfilled"
    db.execute(f"UPDATE order_requests SET status='fulfilled', assigned_discord_id={Q}, fulfilled_at={NOW} WHERE id={Q}",
               (fulfiller_discord_id, order_id))
    _add_notification(order["discord_id"], "Order Fulfilled",
                      f"Your request for {order['item_name']} has been fulfilled.", "order")
    return order, None


def get_open_orders():
    db = get_db()
    rows = db.execute("SELECT * FROM order_requests WHERE status='open' ORDER BY created_at DESC").fetchall()
    _put_db(db)
    return rows


def get_user_orders(discord_id, limit=None):
    db = get_db()
    q = f"SELECT * FROM order_requests WHERE discord_id={Q} ORDER BY created_at DESC"
    params = [discord_id]
    if limit:
        q += f" {LIMIT_CLAUSE(Q)}"
        params.append(limit)
    rows = db.execute(q, params).fetchall()
    _put_db(db)
    return rows


# ─── Stats ───────────────────────────────────────────────────────────

def get_active_users_count():
    db = get_db()
    row = db.execute(f"""SELECT COUNT(DISTINCT discord_id) AS cnt FROM (
        SELECT discord_id FROM community_inventory WHERE synced_at > {NOW_M(30)}
        UNION
        SELECT discord_id FROM order_requests WHERE created_at > {NOW_M(30)}
    ) AS t""").fetchone()
    _put_db(db)
    return row["cnt"] or 0


def get_total_scu():
    db = get_db()
    row = db.execute("SELECT COALESCE(SUM(quantity_scu), 0) AS total FROM community_inventory").fetchone()
    _put_db(db)
    return row["total"] or 0


def get_latest_action_time():
    db = get_db()
    row = db.execute(f"""SELECT MAX(ts) AS max_ts FROM (
        SELECT MAX(synced_at) AS ts FROM community_inventory
        UNION
        SELECT MAX(created_at) AS ts FROM order_requests
        UNION
        SELECT MAX(fulfilled_at) AS ts FROM order_requests
    ) AS t""").fetchone()
    _put_db(db)
    return row["max_ts"] or ""


# ─── Notifications ───────────────────────────────────────────────────

@write_db
def _add_notification(discord_id, title, body, source="system"):
    ensure_user(discord_id)
    get_db().execute(f"INSERT INTO notifications (discord_id, title, body, source) VALUES ({Q},{Q},{Q},{Q})",
                     (discord_id, title, body, source))


@write_db
def _notify_all(title, body, source="system"):
    db = get_db()
    users = db.execute("SELECT discord_id FROM users").fetchall()
    for u in users:
        _add_notification(u["discord_id"], title, body, source)


def get_notifications(discord_id, limit=None):
    db = get_db()
    q = f"SELECT * FROM notifications WHERE discord_id={Q} ORDER BY created_at DESC"
    params = [discord_id]
    if limit:
        q += f" {LIMIT_CLAUSE(Q)}"
        params.append(limit)
    rows = db.execute(q, params).fetchall()
    _put_db(db)
    return rows


def get_pending_dm_notifications(limit=20):
    db = get_db()
    rows = db.execute(f"SELECT * FROM notifications WHERE dm_sent=0 ORDER BY created_at ASC {LIMIT_CLAUSE(Q)}",
                      (limit,)).fetchall()
    _put_db(db)
    return rows


@write_db
def mark_notification_dm_sent(notif_id):
    get_db().execute(f"UPDATE notifications SET dm_sent=1 WHERE id={Q}", (notif_id,))


# ─── Sync log ────────────────────────────────────────────────────────

@write_db
def log_sync(discord_id, direction, status, message):
    get_db().execute(f"INSERT INTO sync_log (discord_id, direction, status, message) VALUES ({Q},{Q},{Q},{Q})",
                     (discord_id, direction, status, message[:500]))


# ─── Roles ───────────────────────────────────────────────────────────

def _seed_defaults():
    db = get_db()
    for name, level in [("Blocked", 0), ("User", 1), ("Mod", 2), ("Admin", 3)]:
        row = db.execute(f"SELECT 1 AS ok FROM roles WHERE name={Q}", (name,)).fetchone()
        if not row:
            db.execute(f"INSERT INTO roles (name, level) VALUES ({Q},{Q})", (name, level))
    admin_role_id = os.environ.get("DISCORD_ADMIN_ROLE", "")
    if admin_role_id:
        db.execute(f"UPDATE roles SET discord_role_id={Q}, is_env=1 WHERE name='Admin'", (admin_role_id,))
    db.commit()
    _put_db(db)


def _close_all_connections():
    global _pool
    if _IS_MYSQL:
        while _pool and not _pool.empty():
            try:
                conn = _pool.get_nowait()
                conn.close()
            except:
                pass
        _pool = queue.Queue(maxsize=20)
    elif _IS_ODBC:
        pass
    else:
        if hasattr(_local, "conn") and _local.conn:
            try:
                _local.conn.close()
            except:
                pass
            _local.conn = None


def reset_database():
    conn = get_db()
    tables = ["community_inventory", "order_requests", "notifications", "sync_log",
              "client_tokens", "api_keys", "sessions", "items", "stations",
              "systems", "itemcategory", "roles", "users", "config"]
    if _IS_MYSQL:
        conn.execute("SET FOREIGN_KEY_CHECKS=0")
    elif _IS_ODBC:
        for t in tables:
            conn.execute(f"DROP TABLE IF EXISTS {t}")
        conn.commit()
        _put_db(conn)
        init_db()
        return
    else:
        pass
    for t in tables:
        conn.execute(f"DROP TABLE IF EXISTS {t}")
    if _IS_MYSQL:
        conn.execute("SET FOREIGN_KEY_CHECKS=1")
    conn.commit()
    _put_db(conn)
    if not _IS_MYSQL and not _IS_ODBC:
        if hasattr(_local, "conn") and _local.conn:
            try:
                _local.conn.close()
            except:
                pass
            _local.conn = None
    init_db()


def set_dsn(dsn):
    global _DSN, _IS_MYSQL, _IS_ODBC, DB_PATH, _pool, _pool_lock
    global Q, NOW, NOW_N, NOW_M, IGNORE, LASTID, COLINFO, UPSERT, EXCLUDED, LIMIT_CLAUSE
    is_mysql = dsn.startswith("mysql://")
    is_odbc = not is_mysql and ("Driver=" in dsn or "driver=" in dsn)
    print(f"[db] Testing DSN: {'MySQL' if is_mysql else 'ODBC' if is_odbc else 'SQLite'}", flush=True)

    # Test connection before switching
    if is_odbc:
        import pyodbc
        test = pyodbc.connect(dsn, autocommit=False, timeout=10)
        test.close()

    # Test passed — apply new settings
    _close_all_connections()
    _DSN = dsn
    DB_PATH = dsn
    _IS_MYSQL = is_mysql
    _IS_ODBC = is_odbc
    if _IS_MYSQL:
        import pymysql
        _pool = queue.Queue(maxsize=20)
        _pool_lock = threading.Lock()
        Q = "%s"
        NOW = "NOW()"
        NOW_N = lambda s: f"(NOW() + INTERVAL {s} SECOND)"
        NOW_M = lambda d: f"(NOW() - INTERVAL {d} DAY)"
        IGNORE = "INSERT IGNORE"
        LASTID = "LAST_INSERT_ID()"
        COLINFO = lambda t: f"SHOW COLUMNS FROM `{t}`"
        UPSERT = lambda t, p: "ON DUPLICATE KEY UPDATE"
        EXCLUDED = lambda col: f"VALUES({col})"
        LIMIT_CLAUSE = lambda p: f"LIMIT {p}"
    elif _IS_ODBC:
        import pyodbc
        _pool = None
        _pool_lock = None
        Q = "?"
        NOW = "GETDATE()"
        NOW_N = lambda s: f"DATEADD(SECOND, {s}, GETDATE())"
        NOW_M = lambda d: f"DATEADD(DAY, -{d}, GETDATE())"
        IGNORE = "INSERT"
        LASTID = "CAST(COALESCE(SCOPE_IDENTITY(), @@IDENTITY) AS BIGINT)"
        COLINFO = lambda t: f"SELECT c.name FROM sys.columns c JOIN sys.tables t ON c.object_id=t.object_id WHERE t.name='{t}'"
        UPSERT = lambda t, p: ""
        EXCLUDED = lambda col: f"EXCLUDED.{col}"
        LIMIT_CLAUSE = lambda p: f"OFFSET 0 ROWS FETCH NEXT {p} ROWS ONLY"
    else:
        _pool = None
        _pool_lock = None
        Q = "?"
        NOW = "datetime('now')"
        NOW_N = lambda s: f"datetime('now', '+{s} seconds')"
        NOW_M = lambda d: f"datetime('now', '-{d} days')"
        IGNORE = "INSERT OR IGNORE"
        LASTID = "last_insert_rowid()"
        COLINFO = lambda t: f"PRAGMA table_info({t})"
        UPSERT = lambda t, p: f"ON CONFLICT({p}) DO UPDATE SET"
        EXCLUDED = lambda col: f"excluded.{col}"
        LIMIT_CLAUSE = lambda p: f"LIMIT {p}"
    init_db()


def get_roles():
    db = get_db()
    rows = db.execute("SELECT * FROM roles ORDER BY is_env ASC, level ASC").fetchall()
    _put_db(db)
    return rows


@write_db
def add_role(name, level, discord_role_id=None):
    get_db().execute(f"INSERT INTO roles (name, level, discord_role_id) VALUES ({Q},{Q},{Q})",
                     (name, level, discord_role_id))


@write_db
def update_role(role_id, name, level, discord_role_id=None):
    get_db().execute(f"UPDATE roles SET name={Q}, level={Q}, discord_role_id={Q} WHERE id={Q} AND is_env=0",
                     (name, level, discord_role_id, role_id))


@write_db
def delete_role(role_id):
    get_db().execute(f"DELETE FROM roles WHERE id={Q} AND is_env=0", (role_id,))


def get_user_role_level(discord_id):
    db = get_db()
    row = db.execute(f"SELECT r.level FROM users u JOIN roles r ON u.role_id=r.id WHERE u.discord_id={Q}",
                     (discord_id,)).fetchone()
    _put_db(db)
    return row["level"] if row else 1


def is_banned(discord_id):
    db = get_db()
    row = db.execute(f"SELECT banned FROM users WHERE discord_id={Q}", (discord_id,)).fetchone()
    _put_db(db)
    return bool(row and row["banned"])


# ─── User Management ─────────────────────────────────────────────────

def get_all_users():
    db = get_db()
    rows = db.execute("""SELECT u.*, r.name AS role_name, r.level AS role_level
        FROM users u LEFT JOIN roles r ON u.role_id=r.id
        ORDER BY u.created_at DESC""").fetchall()
    _put_db(db)
    return rows


@write_db
def set_user_role(discord_id, role_id):
    ensure_user(discord_id)
    get_db().execute(f"UPDATE users SET role_id={Q} WHERE discord_id={Q}", (role_id, discord_id))


@write_db
def set_user_banned(discord_id, banned):
    get_db().execute(f"UPDATE users SET banned={Q} WHERE discord_id={Q}", (1 if banned else 0, discord_id))


@write_db
def clear_user_token(discord_id):
    get_db().execute(f"UPDATE users SET access_token='', refresh_token='' WHERE discord_id={Q}", (discord_id,))
    get_db().execute(f"DELETE FROM client_tokens WHERE discord_id={Q}", (discord_id,))
    get_db().execute(f"DELETE FROM sessions WHERE discord_id={Q}", (discord_id,))


@write_db
def clear_user_api_keys(discord_id):
    get_db().execute(f"DELETE FROM api_keys WHERE discord_id={Q}", (discord_id,))


@write_db
def delete_user_record(discord_id):
    for table in ("notifications", "sessions", "client_tokens", "api_keys", "community_inventory", "order_requests", "users"):
        get_db().execute(f"DELETE FROM {table} WHERE discord_id={Q}", (discord_id,))


@write_db
def update_last_seen(discord_id):
    get_db().execute(f"UPDATE users SET last_seen={NOW} WHERE discord_id={Q}", (discord_id,))


# ─── Custom Fields ───────────────────────────────────────────────────

def get_all_items():
    db = get_db()
    rows = db.execute("SELECT * FROM items ORDER BY name").fetchall()
    _put_db(db)
    return rows


def get_itemcategories():
    db = get_db()
    rows = db.execute("SELECT * FROM itemcategory ORDER BY id").fetchall()
    _put_db(db)
    return rows


@write_db
def add_custom_item(name, item_id=None, hasquality=0, code="", catid=1):
    if item_id:
        get_db().execute(f"{IGNORE} INTO items (id, name, hasquality, code, catid) VALUES ({Q},{Q},{Q},{Q},{Q})",
                         (int(item_id), name, int(hasquality), code, int(catid)))
    else:
        get_db().execute(f"{IGNORE} INTO items (name, hasquality, code, catid) VALUES ({Q},{Q},{Q},{Q})",
                         (name, int(hasquality), code, int(catid)))


@write_db
def delete_custom_item(item_id):
    get_db().execute(f"DELETE FROM items WHERE id={Q}", (item_id,))


def get_all_stations():
    db = get_db()
    rows = db.execute("SELECT * FROM stations ORDER BY name").fetchall()
    _put_db(db)
    return rows


@write_db
def add_custom_station(name):
    get_db().execute(f"{IGNORE} INTO stations (name) VALUES ({Q})", (name,))


@write_db
def delete_custom_station(station_id):
    get_db().execute(f"DELETE FROM stations WHERE id={Q}", (station_id,))


# ─── Config ──────────────────────────────────────────────────────────

def get_config(key, default=""):
    db = get_db()
    row = db.execute(f"SELECT value FROM config WHERE key={Q}", (key,)).fetchone()
    _put_db(db)
    return row["value"] if row else default


@write_db
def set_config(key, value):
    db = get_db()
    existing = db.execute(f"SELECT 1 AS ok FROM config WHERE key={Q}", (key,)).fetchone()
    if existing:
        db.execute(f"UPDATE config SET value={Q} WHERE key={Q}", (value, key))
    else:
        db.execute(f"INSERT INTO config (key, value) VALUES ({Q},{Q})", (key, value))


@write_db
def delete_config(key):
    get_db().execute(f"DELETE FROM config WHERE key={Q}", (key,))


def get_schema_version():
    return int(get_config("schema_version", "0"))
