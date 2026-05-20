# SHOWER — Community Shopfront · Workorder · Exchange Registry

SHOWER is the server-side backend for the SC Personal Inventory Tracker System ecosystem. It provides Discord OAuth authentication, role-based access control, community inventory management, order matching, WebSocket sync to JOCKstrap clients, and a REST API for programmatic access.

## Features

- **Discord OAuth login** with guild membership verification
- **Role-based access control** (Blocked / User / Mod / Admin)
- **Community inventory** — add, sync, and manage item quantities with quality tracking
- **Order requests** — create and fulfill orders with automatic matching
- **WebSocket sync** — real-time inventory push to JOCKstrap (PITS extension)
- **REST API** — versioned, key-authenticated endpoints for inventory CRUD
- **Notifications** — order match alerts and system notifications (in-app + Discord DM)
- **Admin panel** — role management, user management, custom items/stations, bot controls, database reset
- **Dual database backend** — SQLite (default) or MySQL

## Quick Start

```bash
cp .env.example .env
# Edit .env with your Discord app credentials
pip install -r requirements.txt
python server.py
```

## Documentation

- [API Reference](API.md) — Complete REST API documentation
- `db.py` — Database schema, migrations, and CRUD helpers
- `api_lib.py` — Shared API library for inventory operations with event triggering
- `ws_server.py` — WebSocket sync server for JOCKstrap
- `bot.py` — Discord bot integration (role fetching, DM notifications)
- `auth.py` — OAuth2 authentication flow
- `render.py` — HTML template rendering

## Tech Stack

- **Runtime:** Python 3.12+
- **HTTP Server:** `http.server.ThreadingHTTPServer`
- **Database:** SQLite (via `sqlite3`) or MySQL (via `pymysql`)
- **WebSocket:** Custom raw-frame handler + `websockets` library
- **Auth:** Discord OAuth2 + Bearer token API keys
