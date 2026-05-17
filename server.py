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

import auth
import bot
import db
import render

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "9200"))
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

        if path == "/" or path == "/dashboard":
            body = render.dashboard(user, db)
            self.respond(body)
            return

        if path == "/inventory":
            body = render.inventory_browse(user, db, qs)
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

        if path == "/notifications":
            body = render.notifications_page(user, db)
            self.respond(body)
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
            db.sync_inventory(discord_id, item_name, quality, quantity_scu, station)
            db.log_sync(discord_id, "push", "ok", f"Synced {item_name} Q{quality} x{quantity_scu}")
            self._check_order_match(discord_id, item_name, quality)
            self.respond_json({"status": "ok"})
            return

        if path == "/api/inventory/sync" and method == "DELETE":
            if not user:
                self.respond_json({"error": "Unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            discord_id = user["discord_id"]
            inventory_id = data.get("inventory_id", "")
            if not inventory_id:
                self.respond_json({"error": "Missing inventory_id"}, HTTPStatus.BAD_REQUEST)
                return
            db.delete_inventory_item(discord_id, inventory_id)
            db.log_sync(discord_id, "push", "ok", f"Deleted inventory item {inventory_id}")
            self.respond_json({"status": "ok"})
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

    def _handle_jock_login(self, qs):
        redirect_uri = qs.get("redirect_uri", "")
        if not redirect_uri:
            self.respond("Missing redirect_uri", HTTPStatus.BAD_REQUEST)
            return
        state = secrets.token_hex(16)
        _jock_oauth_states[state] = redirect_uri
        oauth_params = {
            "client_id": auth.CLIENT_ID,
            "redirect_uri": auth.REDIRECT_URI,
            "response_type": "code",
            "state": state,
        }
        if auth.GUILD_ID:
            oauth_params["scope"] = "identify guilds.members.read"
            oauth_params["guild_id"] = auth.GUILD_ID
        else:
            oauth_params["scope"] = "identify"
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
        role_ids = ""
        is_admin = False
        if member_data:
            role_ids = ",".join(member_data.get("roles", []))
            admin_role = os.environ.get("DISCORD_ADMIN_ROLE", "")
            if admin_role:
                is_admin = admin_role in role_ids
        discord_id = user_data["id"]
        discord_tag = f"{user_data['username']}#{user_data.get('discriminator', '0')}"
        username = user_data.get("username", "")
        avatar = user_data.get("avatar", "")
        db.upsert_user(discord_id, discord_tag, username, avatar, access_token, refresh_token,
                       token_data.get("expires_in", 0), role_ids, is_admin)

        if state in _jock_oauth_states:
            redirect_uri = _jock_oauth_states.pop(state)
            client_token, expires_at = db.create_client_token(discord_id)
            params = urllib.parse.urlencode({
                "token": client_token,
                "discord_tag": discord_tag,
                "discord_id": discord_id,
                "guild_verified": "1" if member_data else "0",
                "guild_roles": role_ids,
                "expires_at": expires_at,
            })
            sep = "&" if "?" in redirect_uri else "?"
            self.redirect(f"{redirect_uri}{sep}{params}")
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
        if cookie:
            c = SimpleCookie()
            c.load(cookie)
            sid = c.get("session_id")
            if sid:
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
    bot.start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"SC Community SHOWER")
    print(f"  SHOpfront, Workorder and Exchange Register")
    print(f"  http://localhost:{PORT}")
    print(f"  Database: {db.DB_PATH}")
    server.serve_forever()
