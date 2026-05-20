import json
import os
import threading
import time
import urllib.error
import urllib.request

import db

DISCORD_API = "https://discord.com/api/v10"
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
GUILD_ID = os.environ.get("DISCORD_GUILD_ID", "")
POLL_INTERVAL = int(os.environ.get("BOT_POLL_INTERVAL", "30"))
_USER_AGENT = "SC-Community/0.1.0 (https://github.com/sc-pits; v0.1.0-alpha)"
_stop_flag = threading.Event()


def _headers(extra=None):
    h = {"User-Agent": _USER_AGENT}
    if extra:
        h.update(extra)
    return h


def send_dm(discord_id, title, body):
    message = f"**{title}**\n{body}"
    req = urllib.request.Request(
        f"{DISCORD_API}/users/@me/channels",
        data=json.dumps({"recipient_id": discord_id}).encode(),
        headers={
            "Authorization": f"Bot {BOT_TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            channel = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return False, f"create DM: HTTP {e.code}: {e.read().decode()}"
    except Exception as ex:
        return False, f"create DM: {ex}"

    req = urllib.request.Request(
        f"{DISCORD_API}/channels/{channel['id']}/messages",
        data=json.dumps({"content": message}).encode(),
        headers={
            "Authorization": f"Bot {BOT_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return True, None
    except urllib.error.HTTPError as e:
        return False, f"send DM: HTTP {e.code}: {e.read().decode()}"
    except Exception as ex:
        return False, f"send DM: {ex}"


def poll_and_send():
    while not _stop_flag.is_set():
        try:
            notifs = db.get_pending_dm_notifications()
            for n in notifs:
                if _stop_flag.is_set():
                    return
                ok, err = send_dm(n["discord_id"], n["title"], n["body"])
                if ok:
                    db.mark_notification_dm_sent(n["id"])
                else:
                    print(f"[bot] Failed DM to {n['discord_id']}: {err}")
        except Exception as e:
            print(f"[bot] Poll error: {e}")
        time.sleep(POLL_INTERVAL)


def fetch_guild_roles():
    """Fetch Discord guild roles via REST API. Returns list of {id, name} or empty list."""
    if not BOT_TOKEN or not GUILD_ID:
        return []
    try:
        req = urllib.request.Request(
            f"{DISCORD_API}/guilds/{GUILD_ID}/roles",
            headers=_headers({"Authorization": f"Bot {BOT_TOKEN}"}),
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            roles = json.loads(resp.read().decode())
            return [{"id": r["id"], "name": r["name"]} for r in roles]
    except Exception as e:
        print(f"[bot] fetch_guild_roles error: {e}", flush=True)
        return []


def start():
    if not BOT_TOKEN:
        print("[bot] DISCORD_BOT_TOKEN not set — DM delivery disabled")
        return
    _stop_flag.clear()
    t = threading.Thread(target=poll_and_send, daemon=True)
    t.start()
    print(f"[bot] Started (poll every {POLL_INTERVAL}s)")


def restart():
    _stop_flag.set()
    time.sleep(0.5)
    start()
