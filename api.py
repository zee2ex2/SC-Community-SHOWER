import db


def auth_token(token):
    user = db.get_user_by_client_token(token)
    if not user:
        return None
    return {"discord_id": user["discord_id"]}


def auth_code(code):
    from ws_server import _auth_codes, _auth_codes_lock
    with _auth_codes_lock:
        discord_id = _auth_codes.pop(code, None)
    if not discord_id:
        return None
    user = db.get_db().execute(
        "SELECT discord_id, discord_tag, username, display_name FROM users WHERE discord_id=?",
        (discord_id,)
    ).fetchone()
    if not user:
        return None
    return {"discord_id": user["discord_id"],
            "discord_tag": user["discord_tag"],
            "username": user["username"],
            "display_name": user["display_name"]}


def resolve_item(itemid=None, item_name=None):
    if itemid:
        row = db.get_db().execute("SELECT name FROM items WHERE id=?", (int(itemid),)).fetchone()
        if row:
            return row["name"], int(itemid)
    if item_name:
        row = db.get_db().execute("SELECT id FROM items WHERE name=?", (item_name,)).fetchone()
        if row:
            return item_name, row["id"]
    if item_name:
        return item_name, None
    return None, None


def resolve_station(stationid=None, station=None):
    if stationid:
        row = db.get_db().execute("SELECT name FROM stations WHERE id=?", (int(stationid),)).fetchone()
        if row:
            return row["name"], int(stationid)
    if station:
        row = db.get_db().execute("SELECT id FROM stations WHERE name=?", (station,)).fetchone()
        if row:
            return station, row["id"]
    if station:
        return station, None
    return None, None


def sync_inventory(discord_id, item_name, quality, quantity_scu, station):
    result = db.sync_inventory(discord_id, item_name, quality, quantity_scu, station)
    if result.get("ok"):
        db.log_sync(discord_id, "push", "ok", f"Synced {item_name}")
    return result


def delete_inventory(discord_id, item_name, quality, station):
    row = db.get_db().execute(
        "SELECT id FROM community_inventory WHERE discord_id=? AND item_name=? AND quality=? AND station=?",
        (discord_id, item_name, quality, station)
    ).fetchone()
    if row:
        db.delete_inventory_item(discord_id, row["id"])
        db.log_sync(discord_id, "push", "ok", f"Deleted {item_name}")
        return True
    return False
