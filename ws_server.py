import asyncio
import json
import threading
import time
import websockets

import db

_connections = {}
_connections_lock = threading.Lock()
_loop = None
_auth_codes = {}
_auth_codes_lock = threading.Lock()


async def _handler(websocket):
    global _loop
    _loop = asyncio.get_running_loop()
    discord_id = None
    try:
        async for message in websocket:
            data = json.loads(message)
            msg_type = data.get("type", "")

            if msg_type == "auth":
                token = data.get("token", "")
                user = db.get_user_by_client_token(token)
                if user:
                    discord_id = user["discord_id"]
                    with _connections_lock:
                        _connections[discord_id] = websocket
                    await websocket.send(json.dumps({"type": "auth_ok"}))
                    print(f"[ws] Client authenticated: {discord_id}", flush=True)
                else:
                    await websocket.send(json.dumps({"type": "auth_error", "error": "Invalid token"}))
                    return

            elif msg_type == "auth_code":
                code = data.get("code", "")
                with _auth_codes_lock:
                    discord_id = _auth_codes.pop(code, None)
                if discord_id:
                    with _connections_lock:
                        _connections[discord_id] = websocket
                    user = db.get_db().execute(
                        "SELECT discord_id, discord_tag, username, display_name FROM users WHERE discord_id=?",
                        (discord_id,)
                    ).fetchone()
                    info = dict(user) if user else {}
                    await websocket.send(json.dumps({"type": "auth_ok", "user": info}))
                    print(f"[ws] Client auth_code: {discord_id}", flush=True)
                else:
                    await websocket.send(json.dumps({"type": "auth_error", "error": "Invalid code"}))
                    return

            elif msg_type == "sync_inventory" and discord_id:
                action = data.get("action", "")
                itemid = data.get("itemid", "")
                item_name = data.get("item_name", "")
                if not item_name and itemid:
                    row = db.get_db().execute("SELECT name FROM items WHERE id=?", (int(itemid),)).fetchone()
                    item_name = row["name"] if row else ""
                if not item_name:
                    continue
                quality = int(data.get("quality", 100))
                quantity_scu = float(data.get("quantity_scu", 1.0))
                station = data.get("station", "")
                stationid = data.get("stationid", "")
                if not station and stationid:
                    row = db.get_db().execute("SELECT name FROM stations WHERE id=?", (int(stationid),)).fetchone()
                    station = row["name"] if row else ""
                if action == "add":
                    db.sync_inventory(discord_id, item_name, quality, quantity_scu, station)
                    db.log_sync(discord_id, "push", "ok", f"WS synced {item_name}")
                elif action == "delete":
                    row = db.get_db().execute(
                        "SELECT id FROM community_inventory WHERE discord_id=? AND item_name=? AND quality=? AND station=?",
                        (discord_id, item_name, quality, station)
                    ).fetchone()
                    if row:
                        db.delete_inventory_item(discord_id, row["id"])
                        db.log_sync(discord_id, "push", "ok", f"WS deleted {item_name}")

            elif msg_type == "ping":
                await websocket.send(json.dumps({"type": "pong"}))

    except (websockets.exceptions.ConnectionClosed, json.JSONDecodeError) as e:
        print(f"[ws] Connection error: {e}", flush=True)
    finally:
        if discord_id:
            with _connections_lock:
                _connections.pop(discord_id, None)
            print(f"[ws] Client disconnected: {discord_id}", flush=True)


async def _serve(port):
    print(f"[ws] WebSocket server on port {port}", flush=True)
    async with websockets.serve(_handler, "0.0.0.0", port):
        await asyncio.Future()


def _run_server(port):
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    _loop.run_until_complete(_serve(port))


def start(port):
    t = threading.Thread(target=_run_server, args=(port,), daemon=True)
    t.start()
    while _loop is None:
        time.sleep(0.01)


def send(discord_id, message):
    with _connections_lock:
        ws = _connections.get(discord_id)
    if ws and _loop:
        asyncio.run_coroutine_threadsafe(ws.send(json.dumps(message)), _loop)
        return True
    return False


def close(discord_id):
    with _connections_lock:
        ws = _connections.pop(discord_id, None)
    if ws and _loop:
        async def _close():
            try:
                await ws.send(json.dumps({"type": "disconnect"}))
            except Exception:
                pass
            await ws.close()
        asyncio.run_coroutine_threadsafe(_close(), _loop)


def add_auth_code(code, discord_id):
    with _auth_codes_lock:
        _auth_codes[code] = discord_id
