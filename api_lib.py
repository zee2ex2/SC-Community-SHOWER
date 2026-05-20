"""
API Library for SHOWER.
All inventory operations trigger the same events as webapp actions
(JOCKstrap push, order matching, sync log).
"""

import db
import ws_server
from db import Q


def add_inventory(user, item_name, quality, quantity_scu, station):
    """
    Add inventory item for the authenticated user.
    Merges quantity if identical row exists.
    Triggers: JOCKstrap push, order match notification, sync log.
    Returns: (row_id, None) on success, (None, error_msg) on failure.
    """
    discord_id = user["discord_id"]
    row_id, err = db.add_my_inventory(discord_id, item_name, quality, quantity_scu, station)
    if err:
        return None, err
    _push_to_pits(user, "add", item_name, quality, quantity_scu, station)
    _check_order_match(discord_id, item_name, quality)
    db.log_sync(discord_id, "push", "ok", f"Synced {item_name} Q{quality} x{quantity_scu}")
    return row_id, None


def delete_inventory(user, inv_id):
    """
    Delete an inventory entry by its ID.
    Triggers: JOCKstrap push, sync log.
    Returns: (True, None) or (False, error_msg).
    """
    discord_id = user["discord_id"]
    item = db.get_inventory_item(discord_id, inv_id)
    if not item:
        return False, "Inventory entry not found"
    _push_to_pits(user, "delete", item["item_name"], item["quality"],
                  item["quantity_scu"], item["station"] or "")
    db.delete_inventory_item(discord_id, inv_id)
    db.log_sync(discord_id, "push", "ok", f"Deleted {item['item_name']}")
    return True, None


def get_inventory(user, limit=None):
    """
    Get all inventory entries for the user.
    Returns list of dicts.
    """
    return db.get_user_inventory(user["discord_id"], limit)


# ─── Internal helpers ─────────────────────────────────────────────────


def _push_to_pits(user, action, item_name, quality, quantity_scu, station):
    """Resolve names to IDs and push inventory change to JOCKstrap."""
    itemid = ""
    stationid = ""
    if item_name:
        row = db.get_db().execute(f"SELECT id FROM items WHERE name={Q}", (item_name,)).fetchone()
        if row:
            itemid = str(row["id"])
    if station:
        row = db.get_db().execute(f"SELECT id FROM stations WHERE name={Q}", (station,)).fetchone()
        if row:
            stationid = str(row["id"])
    msg = {
        "type": "push_inventory", "action": action,
        "itemid": itemid, "item_name": item_name,
        "quality": str(quality), "quantity_scu": str(quantity_scu),
        "stationid": stationid, "station": station,
    }
    sent = ws_server.send(user["discord_id"], msg)
    if not sent:
        print(f"[push] No WS connection for {user['discord_id']}", flush=True)


def _check_order_match(discord_id, item_name, quality):
    """Check if item matches any open orders and notify the order creator."""
    orders = db.get_open_orders()
    for o in orders:
        if o["item_name"].lower() == item_name.lower() and quality >= o["min_quality"]:
            if o["discord_id"] != discord_id:
                db._add_notification(
                    o["discord_id"],
                    "Item Available",
                    f"Someone added {item_name} (Q{quality}) to their inventory, matching your order request.",
                    "order",
                )
