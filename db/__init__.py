from .engine import engine, get_session, write_db, _DSN, _set_engine
from .models import Base, User, Session, Item, ItemCategory, System, Station, CommunityInventory, OrderRequest, Notification, SyncLog, Config, ApiKey, ClientToken, Role
from .schema import init_db, SCHEMA_VERSION
from .message import push_message, push_event, pop_messages
from .crud import (
    ensure_user, get_user, upsert_user, get_user_by_session,
    create_session, delete_session, delete_user_sessions,
    create_api_key, revoke_api_key, get_user_by_api_key, get_api_keys,
    create_client_token, get_user_by_client_token, revoke_client_token,
    add_my_inventory, sync_inventory, get_inventory_item, get_inventory_by_content,
    delete_inventory_item, get_user_inventory, all_inventory,
    get_item_autocomplete, get_station_autocomplete,
    create_order, fulfill_order, get_open_orders, get_user_orders,
    get_active_users_count, get_total_scu, get_latest_action_time,
    _add_notification, _notify_all, get_notifications,
    get_pending_dm_notifications, mark_notification_dm_sent,
    log_sync,
    get_roles, add_role, update_role, delete_role,
    get_user_role_level, is_banned,
    get_all_users, set_user_role, set_user_banned,
    clear_user_token, clear_user_api_keys, delete_user_record,
    update_last_seen,
    get_all_items, get_itemcategories, add_custom_item,
    delete_custom_item, get_all_stations, add_custom_station,
    delete_custom_station,
    get_config, set_config, delete_config, get_schema_version,
    _close_all_connections,
    reset_database, set_dsn,
)

from .message import _event_queue, _event_cond

SHOWER_VERSION = "0.2.0"
DB_PATH = _DSN

# Backward compat: Q is always "?" with SQLAlchemy (handles paramstyle per dialect)
Q = "?"
