import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy import func, or_, text
from sqlalchemy.engine import URL

from .engine import get_session, write_db, SessionLocal, engine as _engine, _local_tx
from .models import (
    User, Session, Item, ItemCategory, System, Station,
    CommunityInventory, OrderRequest, Notification, SyncLog,
    Config, ApiKey, ClientToken, Role,
)


# ─── User helpers ────────────────────────────────────────────────────

def ensure_user(discord_id):
    session = get_session()
    user = session.query(User).filter_by(discord_id=discord_id).first()
    if not user:
        session.add(User(discord_id=discord_id, discord_tag=f"Unknown#{discord_id[:4]}"))
        session.commit()


def get_user(discord_id):
    from sqlalchemy.orm import joinedload
    return get_session().query(User).options(joinedload(User.role)).filter_by(discord_id=discord_id).first()


@write_db
def upsert_user(discord_id, discord_tag, username, display_name, avatar,
                access_token, refresh_token, token_expires_in, role_ids, is_admin):
    session = get_session()
    user = session.query(User).filter_by(discord_id=discord_id).first()
    if user:
        user.discord_tag = discord_tag
        user.username = username
        user.display_name = display_name
        user.avatar = avatar
        user.access_token = access_token
        user.refresh_token = refresh_token
        user.token_expires_at = token_expires_in
        user.role_ids = role_ids
        user.is_admin = is_admin
    else:
        session.add(User(
            discord_id=discord_id,
            discord_tag=discord_tag,
            username=username,
            display_name=display_name,
            avatar=avatar,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=token_expires_in,
            role_ids=role_ids,
            is_admin=is_admin,
        ))
    _assign_user_role(discord_id, role_ids)


def _assign_user_role(discord_id, role_ids):
    session = get_session()
    ids = role_ids.split(",") if role_ids else []
    if not ids:
        return
    for role in session.query(Role).filter(Role.discord_role_id.isnot(None)).all():
        if role.discord_role_id in ids:
            user = session.query(User).filter_by(discord_id=discord_id).first()
            if user:
                user.role_id = role.id
                user.is_admin = role.level >= 3
                session.commit()
            break


def get_user_by_session(session_id):
    from sqlalchemy.orm import joinedload
    from .models import Session as Sess
    session = get_session()
    return session.query(User).options(joinedload(User.role)).join(Sess).filter(
        Sess.session_id == session_id,
        or_(Sess.expires_at.is_(None), Sess.expires_at > func.now()),
    ).first()


# ─── Sessions ────────────────────────────────────────────────────────

@write_db
def create_session(session_id, discord_id, ttl):
    session = get_session()
    expires_at = datetime.utcnow() + timedelta(seconds=ttl)
    session.add(Session(session_id=session_id, discord_id=discord_id, expires_at=expires_at))


@write_db
def delete_session(session_id):
    get_session().query(Session).filter_by(session_id=session_id).delete()


@write_db
def delete_user_sessions(discord_id):
    get_session().query(Session).filter_by(discord_id=discord_id).delete()


# ─── API Keys ────────────────────────────────────────────────────────

@write_db
def create_api_key(discord_id, label=""):
    key = secrets.token_hex(32)
    get_session().add(ApiKey(key=key, discord_id=discord_id, label=label))
    return key


@write_db
def revoke_api_key(key, discord_id):
    get_session().query(ApiKey).filter_by(key=key, discord_id=discord_id).delete()


def get_user_by_api_key(key):
    from sqlalchemy.orm import joinedload
    session = get_session()
    user = session.query(User).options(joinedload(User.role)).join(ApiKey).filter(
        ApiKey.key == key,
        or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > func.now()),
    ).first()
    if user:
        session.query(ApiKey).filter_by(key=key).update({"last_used": func.now()})
        session.commit()
    return user


def get_api_keys(discord_id):
    session = get_session()
    return session.query(ApiKey).filter_by(discord_id=discord_id).order_by(ApiKey.created_at.desc()).all()


# ─── Client Tokens ───────────────────────────────────────────────────

@write_db
def create_client_token(discord_id, expires_in_days=30):
    token = secrets.token_hex(32)
    expires_at = datetime.utcnow() + timedelta(days=expires_in_days)
    get_session().add(ClientToken(token=token, discord_id=discord_id, expires_at=expires_at))
    return token, expires_at


def get_user_by_client_token(token):
    from sqlalchemy.orm import joinedload
    return get_session().query(User).options(joinedload(User.role)).join(ClientToken).filter(
        ClientToken.token == token,
        ClientToken.expires_at > func.now(),
    ).first()


@write_db
def revoke_client_token(token):
    get_session().query(ClientToken).filter_by(token=token).delete()


# ─── My Inventory ────────────────────────────────────────────────────

@write_db
def add_my_inventory(discord_id, item_name, quality, quantity_scu, station):
    if not _item_exists(item_name):
        return None, f"Item '{item_name}' does not exist."
    if station and not _station_exists(station):
        return None, f"Station '{station}' does not exist."
    session = get_session()
    existing = session.query(CommunityInventory).filter_by(
        discord_id=discord_id, item_name=item_name, quality=quality, station=station,
    ).first()
    if existing:
        existing.quantity_scu += quantity_scu
        existing.synced_at = func.now()
        return existing.id, None
    inv = CommunityInventory(
        discord_id=discord_id, item_name=item_name,
        quality=quality, quantity_scu=quantity_scu, station=station,
    )
    session.add(inv)
    session.flush()
    return inv.id, None


def _ensure_item(name):
    if not name:
        return
    session = get_session()
    if not session.query(Item).filter_by(name=name).first():
        session.add(Item(name=name))
        session.commit()


def _ensure_station(name):
    if not name:
        return
    session = get_session()
    if not session.query(Station).filter_by(name=name).first():
        session.add(Station(name=name))
        session.commit()


def _station_exists(name):
    if not name:
        return True
    return get_session().query(Station).filter_by(name=name).first() is not None


def _item_exists(name):
    return get_session().query(Item).filter_by(name=name).first() is not None


def get_item_autocomplete(prefix, limit=10):
    session = get_session()
    names = set()
    like = f"%{prefix}%"
    for r in session.query(Item.name).filter(Item.name.like(like)).distinct().order_by(Item.name).limit(limit):
        names.add(r.name)
    if len(names) < limit:
        for r in session.query(CommunityInventory.item_name).filter(
                CommunityInventory.item_name.like(like)
        ).distinct().order_by(CommunityInventory.item_name).limit(limit):
            names.add(r.item_name)
    return sorted(names)[:limit]


def get_station_autocomplete(prefix, limit=10):
    session = get_session()
    names = set()
    like = f"%{prefix}%"
    for r in session.query(Station.name).filter(Station.name.like(like)).distinct().order_by(Station.name).limit(limit):
        names.add(r.name)
    if len(names) < limit:
        for r in session.query(CommunityInventory.station).filter(
                CommunityInventory.station.like(like), CommunityInventory.station.isnot(None)
        ).distinct().order_by(CommunityInventory.station).limit(limit):
            if r.station:
                names.add(r.station)
    return sorted(names)[:limit]


# ─── Inventory Sync ──────────────────────────────────────────────────

@write_db
def sync_inventory(discord_id, item_name, quality, quantity_scu, station):
    if not _item_exists(item_name):
        return {"ok": False, "error": f"Item '{item_name}' does not exist."}
    if station and not _station_exists(station):
        return {"ok": False, "error": f"Station '{station}' does not exist."}
    ensure_user(discord_id)
    session = get_session()
    existing = session.query(CommunityInventory).filter_by(
        discord_id=discord_id, item_name=item_name, quality=quality, station=station,
    ).first()
    if existing:
        existing.quantity_scu += quantity_scu
        existing.synced_at = func.now()
    else:
        session.add(CommunityInventory(
            discord_id=discord_id, item_name=item_name,
            quality=quality, quantity_scu=quantity_scu, station=station,
        ))
    return {"ok": True}


def get_inventory_item(discord_id, inventory_id):
    return get_session().query(CommunityInventory).filter_by(
        id=inventory_id, discord_id=discord_id
    ).first()


def get_inventory_by_content(discord_id, item_name, quality, station):
    return get_session().query(CommunityInventory).filter_by(
        discord_id=discord_id, item_name=item_name, quality=quality, station=station,
    ).first()


@write_db
def delete_inventory_item(discord_id, inventory_id):
    ensure_user(discord_id)
    get_session().query(CommunityInventory).filter_by(
        id=inventory_id, discord_id=discord_id
    ).delete()


def get_user_inventory(discord_id, limit=None):
    session = get_session()
    q = session.query(CommunityInventory).filter_by(discord_id=discord_id).order_by(
        CommunityInventory.synced_at.desc()
    )
    if limit:
        q = q.limit(limit)
    return q.all()


def all_inventory(limit=200, search=None, qual_min=None, qual_max=None, qty_min=None):
    session = get_session()
    q = session.query(CommunityInventory).outerjoin(User).order_by(CommunityInventory.synced_at.desc())
    if search:
        q = q.filter(CommunityInventory.item_name.like(f"%{search}%"))
    if qual_min is not None:
        q = q.filter(CommunityInventory.quality >= qual_min)
    if qual_max is not None:
        q = q.filter(CommunityInventory.quality <= qual_max)
    if qty_min is not None:
        q = q.filter(CommunityInventory.quantity_scu >= qty_min)
    rows = q.limit(limit).all()
    result = []
    for r in rows:
        item = {k: getattr(r, k) for k in r.__table__.columns.keys()}
        u = get_session().query(User).filter_by(discord_id=r.discord_id).first()
        item["display_name"] = (u.display_name or u.discord_tag) if u else ""
        result.append(item)
    return result


# ─── Orders ──────────────────────────────────────────────────────────

@write_db
def create_order(discord_id, item_name, min_quality, quantity, notes=""):
    ensure_user(discord_id)
    session = get_session()
    order = OrderRequest(
        discord_id=discord_id, item_name=item_name,
        min_quality=min_quality, quantity=quantity, notes=notes,
    )
    session.add(order)
    session.flush()
    _notify_all(f"New Order: {item_name}", f"{item_name} (Q{min_quality}+, x{quantity}) requested.")
    return order.id


@write_db
def fulfill_order(order_id, fulfiller_discord_id):
    ensure_user(fulfiller_discord_id)
    session = get_session()
    order = session.query(OrderRequest).filter_by(id=order_id).first()
    if not order:
        return None, "Order not found"
    if order.status != "open":
        return None, "Order already fulfilled"
    order.status = "fulfilled"
    order.assigned_discord_id = fulfiller_discord_id
    order.fulfilled_at = func.now()
    _add_notification(order.discord_id, "Order Fulfilled",
                      f"Your request for {order.item_name} has been fulfilled.", "order")
    return order, None


def get_open_orders():
    return get_session().query(OrderRequest).filter_by(status="open").order_by(
        OrderRequest.created_at.desc()
    ).all()


def get_user_orders(discord_id, limit=None):
    session = get_session()
    q = session.query(OrderRequest).filter_by(discord_id=discord_id).order_by(
        OrderRequest.created_at.desc()
    )
    if limit:
        q = q.limit(limit)
    return q.all()


# ─── Stats ───────────────────────────────────────────────────────────

def get_active_users_count():
    session = get_session()
    cutoff = func.now() - timedelta(days=30)
    discord_ids = set()
    for r in session.query(CommunityInventory.discord_id).filter(
            CommunityInventory.synced_at > cutoff).distinct():
        discord_ids.add(r.discord_id)
    for r in session.query(OrderRequest.discord_id).filter(
            OrderRequest.created_at > cutoff).distinct():
        discord_ids.add(r.discord_id)
    return len(discord_ids)


def get_total_scu():
    row = get_session().query(func.coalesce(func.sum(CommunityInventory.quantity_scu), 0)).first()
    return row[0] or 0


def get_latest_action_time():
    session = get_session()
    times = set()
    row = session.query(func.max(CommunityInventory.synced_at)).first()
    if row and row[0]:
        times.add(row[0])
    row = session.query(func.max(OrderRequest.created_at)).first()
    if row and row[0]:
        times.add(row[0])
    row = session.query(func.max(OrderRequest.fulfilled_at)).first()
    if row and row[0]:
        times.add(row[0])
    if not times:
        return ""
    from datetime import datetime as dt
    return max(times).strftime("%Y-%m-%d %H:%M:%S") if isinstance(max(times), dt) else str(max(times))


# ─── Notifications ───────────────────────────────────────────────────

def _add_notification(discord_id, title, body, source="system"):
    ensure_user(discord_id)
    session = get_session()
    session.add(Notification(
        discord_id=discord_id, title=title, body=body, source=source,
    ))
    if not _local_tx.session:
        session.commit()


def _notify_all(title, body, source="system"):
    session = get_session()
    for user_obj in session.query(User).all():
        session.add(Notification(
            discord_id=user_obj.discord_id, title=title, body=body, source=source,
        ))
    if not _local_tx.session:
        session.commit()


def get_notifications(discord_id, limit=None):
    session = get_session()
    q = session.query(Notification).filter_by(discord_id=discord_id).order_by(
        Notification.created_at.desc()
    )
    if limit:
        q = q.limit(limit)
    return q.all()


def get_pending_dm_notifications(limit=20):
    return get_session().query(Notification).filter_by(dm_sent=False).order_by(
        Notification.created_at.asc()
    ).limit(limit).all()


@write_db
def mark_notification_dm_sent(notif_id):
    n = get_session().query(Notification).filter_by(id=notif_id).first()
    if n:
        n.dm_sent = True


# ─── Sync Log ────────────────────────────────────────────────────────

@write_db
def log_sync(discord_id, direction, status, message):
    get_session().add(SyncLog(
        discord_id=discord_id, direction=direction,
        status=status, message=message[:500],
    ))


# ─── Roles ───────────────────────────────────────────────────────────

def get_roles():
    return get_session().query(Role).order_by(Role.is_env.asc(), Role.level.asc()).all()


@write_db
def add_role(name, level, discord_role_id=None):
    get_session().add(Role(name=name, level=level, discord_role_id=discord_role_id))


@write_db
def update_role(role_id, name, level, discord_role_id=None):
    role = get_session().query(Role).filter_by(id=role_id, is_env=False).first()
    if role:
        role.name = name
        role.level = level
        role.discord_role_id = discord_role_id


@write_db
def delete_role(role_id):
    get_session().query(Role).filter_by(id=role_id, is_env=False).delete()


def get_user_role_level(discord_id):
    session = get_session()
    user = session.query(User).join(Role).filter(User.discord_id == discord_id).first()
    return user.role.level if user and user.role else 1


def is_banned(discord_id):
    user = get_session().query(User).filter_by(discord_id=discord_id).first()
    return bool(user and user.banned)


# ─── User Management ─────────────────────────────────────────────────

def get_all_users():
    session = get_session()
    rows = session.query(
        User, Role.name.label("role_name"), Role.level.label("role_level")
    ).outerjoin(Role).order_by(User.created_at.desc()).all()
    result = []
    for user, role_name, role_level in rows:
        u = {k: getattr(user, k) for k in user.__table__.columns.keys()}
        u["role_name"] = role_name
        u["role_level"] = role_level or 1
        result.append(u)
    return result


@write_db
def set_user_role(discord_id, role_id):
    ensure_user(discord_id)
    user = get_session().query(User).filter_by(discord_id=discord_id).first()
    if user:
        user.role_id = role_id


@write_db
def set_user_banned(discord_id, banned):
    user = get_session().query(User).filter_by(discord_id=discord_id).first()
    if user:
        user.banned = bool(banned)


@write_db
def clear_user_token(discord_id):
    session = get_session()
    user = session.query(User).filter_by(discord_id=discord_id).first()
    if user:
        user.access_token = ""
        user.refresh_token = ""
    session.query(ClientToken).filter_by(discord_id=discord_id).delete()
    session.query(Session).filter_by(discord_id=discord_id).delete()


@write_db
def clear_user_api_keys(discord_id):
    get_session().query(ApiKey).filter_by(discord_id=discord_id).delete()


@write_db
def delete_user_record(discord_id):
    session = get_session()
    for model in (Notification, Session, ClientToken, ApiKey, CommunityInventory, OrderRequest):
        session.query(model).filter_by(discord_id=discord_id).delete()
    session.query(User).filter_by(discord_id=discord_id).delete()


@write_db
def update_last_seen(discord_id):
    user = get_session().query(User).filter_by(discord_id=discord_id).first()
    if user:
        user.last_seen = func.now()


# ─── Custom Fields ───────────────────────────────────────────────────

def get_all_items():
    return get_session().query(Item).order_by(Item.name).all()


def get_itemcategories():
    return get_session().query(ItemCategory).order_by(ItemCategory.id).all()


@write_db
def add_custom_item(name, item_id=None, hasquality=0, code="", catid=1):
    session = get_session()
    existing = session.query(Item).filter(
        or_(Item.id == item_id, Item.name == name)
    ).first() if item_id else session.query(Item).filter_by(name=name).first()
    if not existing:
        session.add(Item(id=int(item_id), name=name, hasquality=bool(hasquality),
                         code=code, catid=int(catid)) if item_id else
                     Item(name=name, hasquality=bool(hasquality), code=code, catid=int(catid)))


@write_db
def delete_custom_item(item_id):
    get_session().query(Item).filter_by(id=item_id).delete()


def get_all_stations():
    return get_session().query(Station).order_by(Station.name).all()


@write_db
def add_custom_station(name):
    existing = get_session().query(Station).filter_by(name=name).first()
    if not existing:
        get_session().add(Station(name=name))


@write_db
def delete_custom_station(station_id):
    get_session().query(Station).filter_by(id=station_id).delete()


# ─── Config ──────────────────────────────────────────────────────────

def get_config(key, default=""):
    row = get_session().query(Config).filter_by(key=key).first()
    return row.value if row else default


@write_db
def set_config(key, value):
    session = get_session()
    existing = session.query(Config).filter_by(key=key).first()
    if existing:
        existing.value = value
    else:
        session.add(Config(key=key, value=value))


@write_db
def delete_config(key):
    get_session().query(Config).filter_by(key=key).delete()


def get_schema_version():
    return int(get_config("schema_version", "0"))


# ─── Database Admin ──────────────────────────────────────────────────

def reset_database():
    from .models import Base
    from .engine import engine
    Base.metadata.drop_all(engine)
    from .schema import init_db
    init_db()


def _close_all_connections():
    from .engine import engine
    engine.dispose()


def _odbc_to_sa_url(dsn):
    """Return a SQLAlchemy URL that passes the raw ODBC string to pyodbc."""
    import urllib.parse
    return URL.create("mssql+pyodbc", query={"odbc_connect": dsn})


def set_dsn(dsn):
    from sqlalchemy import create_engine
    if dsn.startswith("mysql://"):
        url = dsn.replace("mysql://", "mysql+pymysql://", 1)
    elif "Driver=" in dsn:
        url = _odbc_to_sa_url(dsn)
        import pyodbc
        test = pyodbc.connect(dsn, autocommit=False, timeout=10)
        test.close()
    else:
        url = f"sqlite:///{dsn}"
    new_engine = create_engine(url, pool_pre_ping=True)
    with new_engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    _close_all_connections()
    from .engine import _set_engine
    _set_engine(new_engine)
    from .schema import init_db
    init_db()
