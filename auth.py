import json
import os
import urllib.parse
import urllib.request

DISCORD_API = "https://discord.com/api/v10"
CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("DISCORD_REDIRECT_URI", "http://localhost:9200/auth/callback")
GUILD_ID = os.environ.get("DISCORD_GUILD_ID", "")
SESSION_TTL = 86400 * 7
_USER_AGENT = "SC-Community/0.1.0 (https://github.com/sc-pits; v0.1.0-alpha)"

def auth_url():
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
    }
    if GUILD_ID:
        params["scope"] = "identify guilds.members.read"
        params["guild_id"] = GUILD_ID
    else:
        params["scope"] = "identify"
    return f"https://discord.com/api/oauth2/authorize?{urllib.parse.urlencode(params)}"


def _headers(extra=None):
    h = {"User-Agent": _USER_AGENT}
    if extra:
        h.update(extra)
    return h

def exchange_code(code):
    data = urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
    }).encode()
    req = urllib.request.Request(
        f"{DISCORD_API}/oauth2/token",
        data=data,
        headers=_headers({"Content-Type": "application/x-www-form-urlencoded"}),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()}"
    except Exception as ex:
        return None, str(ex)


def get_discord_user(access_token):
    req = urllib.request.Request(
        f"{DISCORD_API}/users/@me",
        headers=_headers({"Authorization": f"Bearer {access_token}"}),
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()}"
    except Exception as ex:
        return None, str(ex)


def get_guild_member(access_token):
    if not GUILD_ID:
        return None, None
    req = urllib.request.Request(
        f"{DISCORD_API}/users/@me/guilds/{GUILD_ID}/member",
        headers=_headers({"Authorization": f"Bearer {access_token}"}),
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[auth] get_guild_member HTTP {e.code}: {body[:200]}", flush=True)
        return None, body
    except Exception as ex:
        print(f"[auth] get_guild_member error: {ex}", flush=True)
        return None, str(ex)


def get_guild_name():
    name = os.environ.get("DISCORD_GUILD_NAME", "")
    if name:
        return name
    if not GUILD_ID:
        return None
    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not bot_token:
        return None
    req = urllib.request.Request(
        f"{DISCORD_API}/guilds/{GUILD_ID}",
        headers=_headers({"Authorization": f"Bot {bot_token}"}),
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data.get("name")
    except Exception as e:
        print(f"[auth] get_guild_name error: {e}", flush=True)
        return None
