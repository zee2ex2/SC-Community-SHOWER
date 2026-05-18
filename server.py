import html as html_mod
import json
import os
import secrets
import sys
import urllib.parse
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Load .env file before any module imports that read env vars
env_path = Path(__file__).resolve().parent / '.env'
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, val = line.partition('=')
        os.environ.setdefault(key.strip(), val.strip())

import auth
import bot
import db
import render
import ws_server

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "9200"))
WS_PORT = int(os.environ.get("WS_PORT", str(PORT + 1)))
BASE_DIR = Path(__file__).resolve().parent

_jock_oauth_states = {}


def esc(val):
    if val is None:
        return ""
    return html_mod.escape(str(val), quote=True)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            self._handle("GET")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.respond(f"<h1>Error</h1><pre>{esc(str(e))}</pre>", HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self):
        try:
            self._handle("POST")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.respond(f"<h1>Error</h1><pre>{esc(str(e))}</pre>", HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_DELETE(self):
        self.do_POST()

    def _get_session(self):
        cookie = self.headers.get("Cookie", "")
        if not cookie:
            return None
        c = SimpleCookie()
        c.load(cookie)
        sid = c.get("session_id")
        if not sid:
            return None
        return db.get_user_by_session(sid.value)

    def _get_api_user(self):
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            key = auth_header[7:]
            user = db.get_user_by_api_key(key)
            if user:
                return user
            user = db.get_user_by_client_token(key)
            if user:
                return user
        return None

    def _get_request_user(self):
        user = self._get_api_user()
        if user:
            return user
        return self._get_session()

    def _handle(self, method):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        raw_qs = urllib.parse.parse_qs(parsed.query)
        qs = {k: v[0] for k, v in raw_qs.items() if v[0]}
        data = {}
        if method in ("POST", "DELETE"):
            length = int(self.headers.get("Content-Length", "0"))
            if length > 0:
                body = self.rfile.read(length).decode("utf-8")
                ctype = self.headers.get("Content-Type", "")
                if "application/json" in ctype:
                    try:
                        data = json.loads(body)
                    except json.JSONDecodeError:
                        data = {}
                else:
                    form = urllib.parse.parse_qs(body)
                    data = {k: v[0].strip() for k, v in form.items() if v}

        if path == "/static/styles.css":
            self.serve_static(BASE_DIR / "static" / "styles.css", "text/css; charset=utf-8")
            return

        if path == "/static/shower.js":
            self.serve_static(BASE_DIR / "static" / "shower.js", "application/javascript; charset=utf-8")
            return

        if path.startswith("/api/"):
            self._handle_api(method, path, qs, data)
            return

        user = self._get_session()

        if path == "/auth/login":
            url = auth.auth_url()
            self.redirect(url)
            return

        if path == "/auth/jock-login":
            self._handle_jock_login(qs)
            return

        if path == "/auth/callback":
            self._handle_callback(qs)
            return

        if path == "/auth/logout":
            self._handle_logout(qs)
            return

        if user and (db.is_banned(user["discord_id"]) or db.get_user_role_level(user["discord_id"]) == 0):
            db.delete_user_sessions(user["discord_id"])
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", "session_id=; SameSite=Lax; Path=/; Max-Age=0")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if user:
            db.update_last_seen(user["discord_id"])

        if path == "/" or path == "/dashboard":
            body = render.dashboard(user, db, qs)
            self.respond(body)
            return

        if path == "/api-keys":
            body = render.api_keys_page(user, db)
            self.respond(body)
            return

        if path == "/inventory":
            body = render.inventory_browse(user, db, qs)
            self.respond(body)
            return

        if path == "/my-inventory":
            if not user:
                self.respond("Login required", HTTPStatus.UNAUTHORIZED)
                return
            body = render.my_inventory_page(user, db, qs)
            self.respond(body)
            return

        if path == "/orders":
            body = render.orders_page(user, db, qs)
            self.respond(body)
            return

        if path == "/orders/create":
            if method == "POST":
                self._handle_order_create(user, data)
                return
            body = render.order_create_form(user)
            self.respond(body)
            return

        if path == "/orders/fulfill":
            if method == "POST":
                self._handle_order_fulfill(user, data)
                return
            self.redirect("/orders")
            return

        if path == "/admin":
            if not user:
                self.respond("Login required", HTTPStatus.UNAUTHORIZED)
                return
            level = db.get_user_role_level(user["discord_id"])
            if level < 2:
                self.respond("Access denied", HTTPStatus.FORBIDDEN)
                return
            if method == "POST":
                self._handle_admin_post(user, data)
                return
            body = render.admin_page(user, db, qs)
            self.respond(body)
            return

        if path == "/notifications":
            body = render.notifications_page(user, db)
            self.respond(body)
            return

        if path == "/my-inventory/add" and method == "POST":
            if not user:
                self.respond("<h1>Not logged in</h1>", HTTPStatus.UNAUTHORIZED)
                return
            item_name = data.get("item_name", "").strip()
            quality = int(data.get("quality", 100))
            quantity = float(data.get("quantity_scu", 1.0))
            station = data.get("station", "").strip()
            if not item_name:
                self.redirect("/my-inventory?error=missing_name")
                return
            row_id, err = db.add_my_inventory(user["discord_id"], item_name, quality, quantity, station)
            if err:
                self.redirect(f"/my-inventory?error={urllib.parse.quote(err)}")
                return
            self._push_to_pits(user, "add", {
                "item_name": item_name,
                "quality": quality,
                "quantity_scu": quantity,
                "station": station,
            })
            self.redirect("/my-inventory?created=1")
            return

        if path == "/my-inventory/delete" and method == "POST":
            if not user:
                self.respond("<h1>Not logged in</h1>", HTTPStatus.UNAUTHORIZED)
                return
            inv_id = data.get("inv_id", "")
            if not inv_id:
                self.redirect("/my-inventory?error=missing_id")
                return
            item = db.get_inventory_item(user["discord_id"], inv_id)
            if item:
                self._push_to_pits(user, "delete", {
                    "item_name": item["item_name"],
                    "quality": item["quality"],
                    "quantity_scu": item["quantity_scu"],
                    "station": item["station"] or "",
                })
            db.delete_inventory_item(user["discord_id"], inv_id)
            self.redirect("/my-inventory?deleted=1")
            return

        self.respond("Not found", HTTPStatus.NOT_FOUND)

    def _handle_api(self, method, path, qs, data):
        user = self._get_request_user()

        if path == "/api/inventory/sync" and method == "POST":
            if not user:
                self.respond_json({"error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            discord_id = user["discord_id"]
            item_name = data.get("item_name", "")
            quality = data.get("quality", 100)
            quantity_scu = data.get("quantity_scu", 1.0)
            station = data.get("station", "")
            if not item_name:
                self.respond_json({"error": "Missing item_name"}, HTTPStatus.BAD_REQUEST)
                return
            result = db.sync_inventory(discord_id, item_name, quality, quantity_scu, station)
            if not result.get("ok"):
                self.respond_json({"error": result.get("error", "Sync rejected")}, HTTPStatus.BAD_REQUEST)
                return
            db.log_sync(discord_id, "push", "ok", f"Synced {item_name} Q{quality} x{quantity_scu}")
            self._check_order_match(discord_id, item_name, quality)
            self.respond_json({"status": "ok"})
            return

        if path == "/api/inventory/sync" and method == "DELETE":
            if not user:
                self.respond_json({"error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            discord_id = user["discord_id"]
            item_name = data.get("item_name", "")
            quality = int(data.get("quality", 100))
            quantity_scu = float(data.get("quantity_scu", 0))
            station = data.get("station", "")
            if not item_name:
                self.respond_json({"error": "Missing item_name"}, HTTPStatus.BAD_REQUEST)
                return
            row = db.get_db().execute(
                "SELECT id FROM community_inventory WHERE discord_id=? AND item_name=? AND quality=? AND station=?",
                (discord_id, item_name, quality, station)
            ).fetchone()
            if row:
                db.delete_inventory_item(discord_id, row["id"])
                db.log_sync(discord_id, "push", "ok", f"Deleted {item_name}")
                self.respond_json({"status": "ok"})
            else:
                self.respond_json({"error": "No matching inventory found"}, HTTPStatus.NOT_FOUND)
            return

        if path == "/api/inventory/sync" and method == "GET":
            if not user:
                self.respond_json({"error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            discord_id = user["discord_id"]
            items = db.get_user_inventory(discord_id)
            result = []
            for item in items:
                result.append({
                    "id": item["id"], "item_name": item["item_name"],
                    "quality": item["quality"], "quantity_scu": item["quantity_scu"],
                    "station": item["station"], "synced_at": item["synced_at"],
                })
            self.respond_json(result)
            db.log_sync(discord_id, "pull", "ok", f"Pulled {len(result)} items")
            return

        if path == "/api/notifications" and method == "GET":
            if not user:
                self.respond_json({"error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            discord_id = user["discord_id"]
            notifs = db.get_notifications(discord_id)
            result = []
            for n in notifs:
                result.append({
                    "id": n["id"], "title": n["title"], "body": n["body"],
                    "source": n["source"], "read": n["read"],
                    "created_at": n["created_at"],
                })
            self.respond_json(result)
            return

        if path == "/api/orders" and method == "GET":
            if not user:
                self.respond_json({"error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            status_filter = qs.get("status", "")
            if status_filter == "my":
                orders = db.get_user_orders(user["discord_id"])
            else:
                orders = db.get_open_orders()
            result = []
            for o in orders:
                result.append({
                    "id": o["id"], "item_name": o["item_name"],
                    "min_quality": o["min_quality"], "quantity": o["quantity"],
                    "notes": o["notes"], "status": o["status"],
                    "created_by_discord": o["discord_id"],
                    "assigned_to_discord": o["assigned_discord_id"] or "",
                    "created_at": o["created_at"],
                })
            self.respond_json(result)
            return

        if path == "/api/orders" and method == "POST":
            if not user:
                self.respond_json({"error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            discord_id = user["discord_id"]
            item_name = data.get("item_name", "")
            min_quality = data.get("min_quality", 1)
            quantity = data.get("quantity", 1)
            notes = data.get("notes", "")
            if not item_name:
                self.respond_json({"error": "Missing item_name"}, HTTPStatus.BAD_REQUEST)
                return
            order_id = db.create_order(discord_id, item_name, min_quality, quantity, notes)
            self.respond_json({"status": "ok", "order_id": order_id})
            return

        if path == "/api/orders/fulfill" and method == "POST":
            if not user:
                self.respond_json({"error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            discord_id = user["discord_id"]
            order_id = data.get("order_id", "")
            if not order_id:
                self.respond_json({"error": "Missing order_id"}, HTTPStatus.BAD_REQUEST)
                return
            order, err = db.fulfill_order(order_id, discord_id)
            if err:
                self.respond_json({"error": err}, HTTPStatus.BAD_REQUEST)
                return
            self.respond_json({"status": "ok", "order_id": order_id})
            return

        if path == "/api/keys" and method == "GET":
            if not user:
                self.respond_json({"error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            keys = db.get_api_keys(user["discord_id"])
            result = []
            for k in keys:
                result.append({
                    "key": k["key"], "label": k["label"],
                    "last_used": k["last_used"], "expires_at": k["expires_at"],
                    "created_at": k["created_at"],
                })
            self.respond_json(result)
            return

        if path == "/api/keys/create" and method == "POST":
            if not user:
                self.respond_json({"error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            label = data.get("label", "PITS sync key")
            key = db.create_api_key(user["discord_id"], label)
            self.respond_json({"status": "ok", "key": key})
            return

        if path == "/api/keys/revoke" and method == "POST":
            if not user:
                self.respond_json({"error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            key = data.get("key", "")
            if not key:
                self.respond_json({"error": "Missing key"}, HTTPStatus.BAD_REQUEST)
                return
            db.revoke_api_key(key, user["discord_id"])
            self.respond_json({"status": "ok"})
            return

        if path == "/api/auth/revoke" and method == "POST":
            if not user:
                self.respond_json({"error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            auth_header = self.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                db.revoke_client_token(auth_header[7:])
            self.respond_json({"status": "ok"})
            return

        if path == "/api/autocomplete/items" and method == "GET":
            prefix = qs.get("q", "")
            if not prefix:
                self.respond_json([])
                return
            results = db.get_item_autocomplete(prefix)
            self.respond_json(results)
            return

        if path == "/api/autocomplete/stations" and method == "GET":
            prefix = qs.get("q", "")
            if not prefix:
                self.respond_json([])
                return
            results = db.get_station_autocomplete(prefix)
            self.respond_json(results)
            return

        self.respond_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def _check_order_match(self, discord_id, item_name, quality):
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

    def _push_to_pits(self, user, action, data):
        item_name = data.get("item_name", "")
        station = data.get("station", "")
        itemid = ""
        stationid = ""
        if item_name:
            row = db.get_db().execute("SELECT id FROM items WHERE name=?", (item_name,)).fetchone()
            if row: itemid = str(row["id"])
        if station:
            row = db.get_db().execute("SELECT id FROM stations WHERE name=?", (station,)).fetchone()
            if row: stationid = str(row["id"])
        msg = {"type": "push_inventory", "action": action,
               "itemid": itemid, "item_name": item_name,
               "quality": data.get("quality", ""),
               "quantity_scu": data.get("quantity_scu", ""),
               "stationid": stationid, "station": station}
        sent = ws_server.send(user["discord_id"], msg)
        if not sent:
            print(f"[push] No WS connection for {user['discord_id']}", flush=True)

    def _handle_jock_login(self, qs):
        redirect_uri = qs.get("redirect_uri", "")
        if not redirect_uri:
            self.respond("Missing redirect_uri", HTTPStatus.BAD_REQUEST)
            return
        state = secrets.token_hex(16)
        pu = urllib.parse.urlparse(redirect_uri)
        pits_url = f"{pu.scheme}://{pu.netloc}"
        _jock_oauth_states[state] = {"redirect_uri": redirect_uri, "pits_url": pits_url}
        oauth_params = {
            "client_id": auth.CLIENT_ID,
            "redirect_uri": auth.REDIRECT_URI,
            "response_type": "code",
            "scope": "identify",
            "state": state,
        }
        self.redirect(f"https://discord.com/api/oauth2/authorize?{urllib.parse.urlencode(oauth_params)}")

    def _handle_callback(self, qs):
        code = qs.get("code", "")
        error = qs.get("error", "")
        state = qs.get("state", "")
        if error or not code:
            self.respond(f"<h1>Auth Error</h1><p>{esc(error)}</p>")
            return
        token_data, err = auth.exchange_code(code)
        if err or not token_data:
            self.respond(f"<h1>Token Error</h1><p>{esc(err)}</p>")
            return
        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")
        user_data, err = auth.get_discord_user(access_token)
        if err or not user_data:
            self.respond(f"<h1>User Error</h1><p>{esc(err)}</p>")
            return
        member_data, m_err = auth.get_guild_member(access_token)
        if m_err:
            print(f"[server] guild member lookup failed: {m_err}", flush=True)
        role_ids = ""
        is_admin = False
        display_name = None
        if member_data:
            role_ids = ",".join(member_data.get("roles", []))
            admin_role = os.environ.get("DISCORD_ADMIN_ROLE", "")
            if admin_role:
                is_admin = admin_role in role_ids
            nick = member_data.get("nick")
            if nick:
                display_name = nick
        discord_id = user_data["id"]
        discord_tag = f"{user_data['username']}#{user_data.get('discriminator', '0')}"
        username = user_data.get("username", "")
        if not display_name:
            display_name = username
        avatar = user_data.get("avatar", "")
        db.upsert_user(discord_id, discord_tag, username, display_name, avatar, access_token, refresh_token,
                       token_data.get("expires_in", 0), role_ids, is_admin)

        if db.is_banned(discord_id) or db.get_user_role_level(discord_id) == 0:
            self.respond("<h1>Access Denied</h1><p>Your account has been banned from this SHOWER server.</p>", HTTPStatus.FORBIDDEN)
            return

        if state in _jock_oauth_states:
            state_data = _jock_oauth_states.pop(state)
            redirect_uri = state_data["redirect_uri"]
            pits_url = state_data.get("pits_url", "")
            auth_code = secrets.token_hex(8)
            ws_server.add_auth_code(auth_code, discord_id)
            params = urllib.parse.urlencode({
                "code": auth_code,
                "ws_port": WS_PORT,
            })
            sep = "&" if "?" in redirect_uri else "?"
            location = f"{redirect_uri}{sep}{params}"
            session_id = secrets.token_hex(32)
            db.create_session(session_id, discord_id, auth.SESSION_TTL)
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", location)
            self.send_header("Set-Cookie", f"session_id={session_id}; SameSite=Lax; Path=/; Max-Age={auth.SESSION_TTL}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        session_id = secrets.token_hex(32)
        db.create_session(session_id, discord_id, auth.SESSION_TTL)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/dashboard")
        self.send_header("Set-Cookie", f"session_id={session_id}; SameSite=Lax; Path=/; Max-Age={auth.SESSION_TTL}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_logout(self, qs):
        cookie = self.headers.get("Cookie", "")
        if not cookie:
            self.redirect("/")
            return
        c = SimpleCookie()
        c.load(cookie)
        sid = c.get("session_id")
        if not sid:
            self.redirect("/")
            return
        user = db.get_user_by_session(sid.value)
        if user:
            db.get_db().execute("DELETE FROM client_tokens WHERE discord_id=?", (user["discord_id"],))
            db.get_db().commit()
            ws_server.close(user["discord_id"])
        db.delete_session(sid.value)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie", "session_id=; SameSite=Lax; Path=/; Max-Age=0")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _handle_order_create(self, user, data):
        if not user:
            self.respond("<h1>Not logged in</h1>", HTTPStatus.UNAUTHORIZED)
            return
        item_name = data.get("item_name", "")
        min_quality = data.get("min_quality", 1)
        quantity = data.get("quantity", 1)
        notes = data.get("notes", "")
        if not item_name:
            self.redirect("/orders/create?error=missing_name")
            return
        db.create_order(user["discord_id"], item_name, int(min_quality), int(quantity), notes)
        self.redirect("/orders?created=1")

    def _handle_order_fulfill(self, user, data):
        if not user:
            self.respond("<h1>Not logged in</h1>", HTTPStatus.UNAUTHORIZED)
            return
        order_id = data.get("order_id", "")
        if not order_id:
            self.redirect("/orders?error=missing_id")
            return
        order, err = db.fulfill_order(order_id, user["discord_id"])
        if err:
            self.redirect(f"/orders?error={urllib.parse.quote(err)}")
            return
        self.redirect("/orders?fulfilled=1")

    def _handle_admin_post(self, user, data):
        action = data.get("action", "")
        level = db.get_user_role_level(user["discord_id"])

        if action == "add_role":
            if level < 3:
                self.respond_json({"error": "Access denied"}, HTTPStatus.FORBIDDEN)
                return
            name = data.get("name", "").strip()
            lvl = int(data.get("level", 1))
            discord_role_id = data.get("discord_role_id", "") or None
            if not name:
                self.redirect("/admin?error=missing_name")
                return
            db.add_role(name, lvl, discord_role_id)
            self.redirect("/admin?saved=1")

        elif action == "update_role":
            if level < 3:
                self.respond_json({"error": "Access denied"}, HTTPStatus.FORBIDDEN)
                return
            role_id = data.get("role_id", "")
            name = data.get("name", "").strip()
            lvl = int(data.get("level", 1))
            if not role_id or not name:
                self.redirect("/admin?error=missing_fields")
                return
            db.update_role(role_id, name, lvl)
            self.redirect("/admin?saved=1")

        elif action == "delete_role":
            if level < 3:
                self.respond_json({"error": "Access denied"}, HTTPStatus.FORBIDDEN)
                return
            role_id = data.get("role_id", "")
            if not role_id:
                self.redirect("/admin?error=missing_id")
                return
            db.delete_role(role_id)
            self.redirect("/admin?saved=1")

        elif action == "set_user_role":
            if level < 2:
                self.respond_json({"error": "Access denied"}, HTTPStatus.FORBIDDEN)
                return
            target_id = data.get("discord_id", "")
            role_id = data.get("role_id", "")
            if not target_id or not role_id:
                self.redirect("/admin?error=missing_fields")
                return
            target = db.get_db().execute("SELECT * FROM users WHERE discord_id=?", (target_id,)).fetchone()
            if not target:
                self.redirect("/admin?error=user_not_found")
                return
            target_level = db.get_user_role_level(target_id)
            if level < 3 and target_level >= 2:
                self.redirect("/admin?error=cannot_modify_mod_admin")
                return
            db.set_user_role(target_id, role_id)
            self.redirect("/admin?saved=1")

        elif action == "set_user_banned":
            if level < 2:
                self.respond_json({"error": "Access denied"}, HTTPStatus.FORBIDDEN)
                return
            target_id = data.get("discord_id", "")
            banned = data.get("banned", "0") == "1"
            if not target_id:
                self.redirect("/admin?error=missing_id")
                return
            target_level = db.get_user_role_level(target_id)
            if level < 3 and target_level >= 2:
                self.redirect("/admin?error=cannot_modify_mod_admin")
                return
            db.set_user_banned(target_id, banned)
            self.redirect("/admin?saved=1")

        elif action == "clear_user_token":
            if level < 2:
                self.respond_json({"error": "Access denied"}, HTTPStatus.FORBIDDEN)
                return
            target_id = data.get("discord_id", "")
            if not target_id:
                self.redirect("/admin?error=missing_id")
                return
            db.clear_user_token(target_id)
            self.redirect("/admin?saved=1")

        elif action == "delete_user":
            if level < 3:
                self.respond_json({"error": "Access denied"}, HTTPStatus.FORBIDDEN)
                return
            target_id = data.get("discord_id", "")
            if not target_id:
                self.redirect("/admin?error=missing_id")
                return
            db.delete_user_record(target_id)
            self.redirect("/admin?saved=1")

        elif action == "add_item":
            if level < 3:
                self.respond_json({"error": "Access denied"}, HTTPStatus.FORBIDDEN)
                return
            name = data.get("name", "").strip()
            item_id = data.get("item_id", "").strip()
            if not name or not item_id:
                self.redirect("/admin?error=missing_fields")
                return
            existing = db.get_db().execute("SELECT id FROM items WHERE id=? OR name=?", (item_id, name)).fetchone()
            if existing:
                self.redirect("/admin?error=id_or_name_taken")
                return
            db.get_db().execute("INSERT INTO items (id, name) VALUES (?, ?)", (int(item_id), name))
            db.get_db().commit()
            self.redirect("/admin?saved=1")

        elif action == "delete_item":
            if level < 3:
                self.respond_json({"error": "Access denied"}, HTTPStatus.FORBIDDEN)
                return
            item_id = data.get("item_id", "")
            if not item_id:
                self.redirect("/admin?error=missing_id")
                return
            db.delete_custom_item(item_id)
            self.redirect("/admin?saved=1")

        elif action == "add_station":
            if level < 3:
                self.respond_json({"error": "Access denied"}, HTTPStatus.FORBIDDEN)
                return
            name = data.get("name", "").strip()
            station_id = data.get("station_id", "").strip()
            if not name or not station_id:
                self.redirect("/admin?error=missing_fields")
                return
            existing = db.get_db().execute("SELECT id FROM stations WHERE id=? OR name=?", (station_id, name)).fetchone()
            if existing:
                self.redirect("/admin?error=id_or_name_taken")
                return
            db.get_db().execute("INSERT INTO stations (id, name) VALUES (?, ?)", (int(station_id), name))
            db.get_db().commit()
            self.redirect("/admin?saved=1")

        elif action == "delete_station":
            if level < 3:
                self.respond_json({"error": "Access denied"}, HTTPStatus.FORBIDDEN)
                return
            station_id = data.get("station_id", "")
            if not station_id:
                self.redirect("/admin?error=missing_id")
                return
            db.delete_custom_station(station_id)
            self.redirect("/admin?saved=1")

        elif action == "save_config":
            if level < 3:
                self.respond_json({"error": "Access denied"}, HTTPStatus.FORBIDDEN)
                return
            for key in ("guild_name", "discord_client_id", "discord_client_secret", "discord_bot_token"):
                val = data.get(key, "").strip()
                if val:
                    db.set_config(key, val)
            self.redirect("/admin?saved=1")

        else:
            self.redirect("/admin?error=unknown_action")

    def respond_json(self, data, status=HTTPStatus.OK):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def respond(self, body, status=HTTPStatus.OK):
        body_bytes = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def redirect(self, location):
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def serve_static(self, path, content_type):
        if not path.exists():
            self.respond("Not found", HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(path.read_bytes())

    def log_message(self, fmt, *args):
        if "Bad request version" in str(args):
            return
        print(f"{self.address_string()} - {fmt % args}")


if __name__ == "__main__":
    db.init_db()
    gn = auth.get_guild_name()
    if gn:
        render.GUILD_NAME = gn
    bot.start()
    ws_server.start(WS_PORT)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Sho.W.E.R")
    print(f"  {render.GUILD_NAME}")
    print(f"  http://localhost:{PORT}")
    print(f"  ws://localhost:{WS_PORT}")
    print(f"  Database: {db.DB_PATH}")
    server.serve_forever()
