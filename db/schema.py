import os

from .models import Base, Item, ItemCategory, System, Station, Role, Config


SCHEMA_VERSION = 3


def init_db():
    from .engine import engine
    try:
        Base.metadata.create_all(engine)
        # Force commit DDL for backends with autocommit=False (ODBC)
        with engine.connect() as conn:
            conn.commit()
    except Exception as e:
        print(f"[db] create_all error: {e}", flush=True)
    # Verify tables were created
    from sqlalchemy import inspect
    try:
        inspector = inspect(engine)
        existing = inspector.get_table_names()
        expected = sorted(Base.metadata.tables.keys())
        missing = [t for t in expected if t not in existing]
        if missing:
            print(f"[db] Missing tables after create_all: {missing}", flush=True)
        else:
            print(f"[db] All {len(expected)} tables created OK", flush=True)
    except Exception as e:
        print(f"[db] Table verification error: {e}", flush=True)
    _seed_itemcategory()
    _seed_items()
    _seed_stations()
    _seed_systems()
    _seed_roles()
    _set_schema_version()
    _fix_text_columns()


def _fix_text_columns():
    """Alter TEXT columns to VARCHAR on SQL Server for comparison compatibility."""
    from .engine import engine
    if not engine or "mssql" not in engine.name:
        return
    from sqlalchemy import text, inspect
    fixes = {
        "order_requests": ["status", "item_name"],
        "users": ["role_ids", "display_name"],
        "items": ["code"],
        "stations": ["code"],
        "notifications": ["source", "title"],
        "community_inventory": ["item_name"],
        "sync_log": ["direction", "status"],
    }
    lengths = {"status": 32, "item_name": 255, "role_ids": 255, "display_name": 128,
               "code": 32, "source": 64, "title": 255, "direction": 32}
    with engine.connect() as conn:
        for table, columns in fixes.items():
            for col in columns:
                row = conn.execute(
                    text("SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=:t AND COLUMN_NAME=:c"),
                    {"t": table, "c": col}
                ).first()
                if row and row[0].lower() == "text":
                    length = lengths.get(col, 255)
                    conn.execute(text(f"ALTER TABLE [{table}] ALTER COLUMN [{col}] VARCHAR({length})"))
                    print(f"[db] Fixed {table}.{col}: TEXT -> VARCHAR({length})", flush=True)
        conn.commit()


def _seed_itemcategory():
    from .engine import SessionLocal
    with SessionLocal() as session:
        if session.query(ItemCategory).count() > 0:
            return
        for row in [
            (1, "Commodity", 0), (2, "Ores", 1), (3, "Vehicle Mining", 1),
            (4, "FPS Mining", 1), (5, "Harvestable", 1), (6, "Salvage", 1),
        ]:
            session.add(ItemCategory(id=row[0], name=row[1], parent_id=row[2]))
        session.commit()


def _seed_items():
    from .engine import SessionLocal
    with SessionLocal() as session:
        if session.query(Item).count() > 0:
            return
        seed = [
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
        for item_id, name in seed:
            session.add(Item(id=item_id, name=name))
        session.add(Item(name="Zeta-Prolanite"))

        # Set catid and hasquality
        cat_map = {
            2: [1, 5, 7, 11, 13, 15, 20, 22, 33, 39, 101, 44, 47, 184, 194, 58, 60, 124, 188, 100, 122, 73, 103, 75, 190, 77],
            3: [167, 170, 169, 168],
            4: [8, 179, 178, 28, 36, 171, 46, 200, 172],
            5: [105, 24, 35, 37, 55, 57, 65, 66, 72, 198, 18],
            6: [63, 181, 182, 183],
        }
        for catid, ids in cat_map.items():
            session.query(Item).filter(Item.id.in_(ids)).update({"catid": catid}, synchronize_session=False)
        # hasquality=1 for catid 2,3,4
        session.query(Item).filter(Item.catid.in_([2, 3, 4])).update({"hasquality": True}, synchronize_session=False)
        # Special items
        for item_id, name, catid, code in [(172, "Saldynium", 4, "SALD"), (178, "Carinite Pure", 4, "CARIP")]:
            session.add(Item(id=item_id, name=name, catid=catid, code=code, hasquality=True))
        for name, code in [("Amiant", "AMIA"), ("Flareweed", "FLWD"), ("Fotia", "FTIA"), ("Pingala", "PNGL")]:
            existing = session.query(Item).filter_by(name=name).first()
            if not existing:
                session.add(Item(name=name, catid=4, code=code, hasquality=True))
        session.commit()


def _seed_stations():
    from .engine import SessionLocal
    with SessionLocal() as session:
        if session.query(Station).count() > 0:
            return
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
        for sid, name in stations:
            session.add(Station(id=sid, name=name))
        session.commit()


def _seed_systems():
    from .engine import SessionLocal
    with SessionLocal() as session:
        if session.query(System).count() > 0:
            return
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
            session.add(System(name=name))
        session.commit()


def _seed_roles():
    from .engine import SessionLocal
    with SessionLocal() as session:
        if session.query(Role).count() > 0:
            return
        for name, level in [("Blocked", 0), ("User", 1), ("Mod", 2), ("Admin", 3)]:
            session.add(Role(name=name, level=level))
        session.commit()
        admin_role_id = os.environ.get("DISCORD_ADMIN_ROLE", "")
        if admin_role_id:
            session.query(Role).filter_by(name="Admin").update({"discord_role_id": admin_role_id, "is_env": True})
            session.commit()


def _set_schema_version():
    from .engine import SessionLocal
    with SessionLocal() as session:
        existing = session.query(Config).filter_by(key="schema_version").first()
        ver = int(existing.value) if existing else 0
        if ver < SCHEMA_VERSION:
            if existing:
                existing.value = str(SCHEMA_VERSION)
            else:
                session.add(Config(key="schema_version", value=str(SCHEMA_VERSION)))
            session.commit()
