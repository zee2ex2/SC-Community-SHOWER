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


def handle_connection(sock, headers, client_addr):
    """Handle a WebSocket connection from an HTTP upgrade request (same port)."""
    import struct, hashlib, base64

    key = headers.get("Sec-WebSocket-Key", "")
    guid = "258EAFA5-E914-47DA-95CA-5AB5DC11B735"
    accept = base64.b64encode(hashlib.sha1((key + guid).encode()).digest()).decode()

    sock.sendall((
        "HTTP/1.1 101 Switching Protocols\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Accept: {accept}\r\n"
        "\r\n"
    ).encode())

    sock.settimeout(None)
    discord_id = None
    buf = b""
    try:
        while True:
            # Read frame header (2 bytes)
            while len(buf) < 2:
                buf += sock.recv(2 - len(buf))
            b1, b2 = buf[0], buf[1]
            buf = buf[2:]
            opcode = b1 & 0x0f
            masked = (b2 & 0x80) != 0
            length = b2 & 0x7f

            if length == 126:
                while len(buf) < 2:
                    buf += sock.recv(2 - len(buf))
                length = struct.unpack("!H", buf[:2])[0]
                buf = buf[2:]
            elif length == 127:
                while len(buf) < 8:
                    buf += sock.recv(8 - len(buf))
                length = struct.unpack("!Q", buf[:8])[0]
                buf = buf[8:]

            mask_key = b""
            if masked:
                while len(buf) < 4:
                    buf += sock.recv(4 - len(buf))
                mask_key = buf[:4]
                buf = buf[4:]

            while len(buf) < length:
                buf += sock.recv(length - len(buf))
            payload = buf[:length]
            buf = buf[length:]

            if masked:
                payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

            if opcode == 0x8:  # Close
                break
            elif opcode == 0x9:  # Ping
                sock.sendall(b'\x8a\x00')  # Pong empty frame
            elif opcode == 0xa:  # Pong
                pass
            elif opcode == 0x1:  # Text
                msg = payload.decode("utf-8")
                data = json.loads(msg)
                msg_type = data.get("type", "")
                if msg_type == "auth_code":
                    code = data.get("code", "")
                    with _auth_codes_lock:
                        discord_id = _auth_codes.pop(code, None)
                    if discord_id:
                        with _connections_lock:
                            _connections[discord_id] = sock
                        user = db.get_db().execute(
                            "SELECT discord_id, discord_tag, username, display_name FROM users WHERE discord_id=?",
                            (discord_id,)
                        ).fetchone()
                        info = dict(user) if user else {}
                        _send_ws(sock, json.dumps({"type": "auth_ok", "user": info}))
                        print(f"[ws] Client auth_code: {discord_id}", flush=True)
                    else:
                        _send_ws(sock, json.dumps({"type": "auth_error", "error": "Invalid code"}))
                        return
                elif msg_type == "sync_inventory" and discord_id:
                    action = data.get("action", "")
                    item_name = data.get("item_name", "")
                    itemid = data.get("itemid", "")
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
                    _send_ws(sock, json.dumps({"type": "pong"}))
                elif msg_type == "disconnect":
                    return
    except Exception:
        pass
    finally:
        if discord_id:
            with _connections_lock:
                _connections.pop(discord_id, None)
            print(f"[ws] Client disconnected: {discord_id}", flush=True)


def _send_ws(sock, text):
    """Send a text WebSocket frame (unmasked, server -> client)."""
    import struct
    data = text.encode("utf-8")
    frame = bytearray()
    frame.append(0x81)  # fin + text opcode
    if len(data) < 126:
        frame.append(len(data))
    elif len(data) < 65536:
        frame.append(126)
        frame.extend(struct.pack("!H", len(data)))
    else:
        frame.append(127)
        frame.extend(struct.pack("!Q", len(data)))
    frame.extend(data)
    sock.sendall(bytes(frame))


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
        sock = _connections.get(discord_id)
    if sock:
        try:
            _send_ws(sock, json.dumps(message))
        except Exception:
            pass
        return True
    return False


def close(discord_id):
    with _connections_lock:
        sock = _connections.pop(discord_id, None)
    if sock:
        try:
            _send_ws(sock, json.dumps({"type": "disconnect"}))
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass


def add_auth_code(code, discord_id):
    with _auth_codes_lock:
        _auth_codes[code] = discord_id
