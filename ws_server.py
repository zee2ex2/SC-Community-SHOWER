import asyncio
import json
import threading
import time
import websockets

import api
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
                user = api.auth_token(token)
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
                user = api.auth_code(code)
                if user:
                    discord_id = user["discord_id"]
                    with _connections_lock:
                        _connections[discord_id] = websocket
                    await websocket.send(json.dumps({"type": "auth_ok", "user": user}))
                    print(f"[ws] Client auth_code: {discord_id}", flush=True)
                else:
                    await websocket.send(json.dumps({"type": "auth_error", "error": "Invalid code"}))
                    return

            elif msg_type == "sync_inventory" and discord_id:
                action = data.get("action", "")
                itemid = data.get("itemid", "")
                item_name = data.get("item_name", "")
                item_name, _ = api.resolve_item(itemid, item_name)
                if not item_name:
                    continue
                quality = int(data.get("quality", 100))
                quantity_scu = float(data.get("quantity_scu", 1.0))
                station = data.get("station", "")
                stationid = data.get("stationid", "")
                station_name, _ = api.resolve_station(stationid, station)
                if station_name:
                    station = station_name
                if action == "add":
                    api.sync_inventory(discord_id, item_name, quality, quantity_scu, station)
                elif action == "delete":
                    api.delete_inventory(discord_id, item_name, quality, station)

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
