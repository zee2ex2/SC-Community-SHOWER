# SHOWER API Reference

Base URL: `http://your-server:9200`

All API endpoints return JSON. Responses use a standardized format for v1 endpoints and a legacy format for backward-compatible endpoints.

## Authentication

API requests are authenticated via **Bearer token** in the `Authorization` header:

```
Authorization: Bearer <your-api-key>
```

API keys are managed through the web UI at `/api-keys` or via the API itself.

### API Key Scopes

API keys inherit the permissions of the owning user's role. Standard roles:
- **Blocked (0)** — no access
- **User (1)** — can manage own inventory, orders, notifications
- **Mod (2)** — same as User, plus can manage other users' roles/tokens
- **Admin (3)** — full access including system settings

---

## v1 API Endpoints

Standardized response format:

```json
// Success
{"ok": true, "data": ...}

// Error
{"ok": false, "error": "description"}
```

### Inventory

#### `GET /api/v1/inventory`

List the authenticated user's inventory entries, most recent first.

**Auth:** Bearer token or session cookie

**Response:**
```json
{
  "ok": true,
  "data": [
    {
      "id": 1,
      "item_name": "Titanium",
      "quality": 100,
      "quantity_scu": 50.0,
      "station": "Area18",
      "synced_at": "2026-05-20 12:00:00"
    }
  ]
}
```

---

#### `POST /api/v1/inventory`

Add an item to the authenticated user's inventory. If an identical entry (same item, quality, and station) already exists, the quantity is merged (added).  

Triggers: **JOCKstrap push**, **order match notification**, **sync log**.

**Auth:** Bearer token or session cookie

**Request body** (JSON or form-encoded):
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `item_name` | string | — | **Required.** Name of the item |
| `quality` | int | `100` | Item quality (1–100) |
| `quantity_scu` | float | `1.0` | Quantity in SCU |
| `station` | string | `""` | Station/location name |

**Response (success):**
```json
{"ok": true, "data": {"id": 42}}
```

**Response (error):**
```json
{"ok": false, "error": "Item 'Unknown' does not exist."}
```

---

#### `DELETE /api/v1/inventory`

Delete a specific inventory entry by its ID.  

Triggers: **JOCKstrap push**, **sync log**.

**Auth:** Bearer token or session cookie

**Request body** (JSON or form-encoded):
| Field | Type | Description |
|-------|------|-------------|
| `id` | int | **Required.** Inventory entry ID |

**Response (success):**
```json
{"ok": true}
```

**Response (not found):**
```json
{"ok": false, "error": "Inventory entry not found"}
```

---

## Legacy API Endpoints (Backward Compatible)

These endpoints use the older `{"status": "ok"}` / `{"error": "..."}` response format and are maintained for existing PITS/JOCKstrap clients.

### `POST /api/inventory/sync`

Add or merge inventory. Delegates to `api_lib.add_inventory()` — triggers all events (JOCKstrap push, order matching, sync log).

**Auth:** Bearer token or session cookie

**Request body:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `item_name` | string | — | **Required.** Item name |
| `quality` | int | `100` | Quality |
| `quantity_scu` | float | `1.0` | Quantity |
| `station` | string | `""` | Station |

**Response:**
```json
{"status": "ok"}
```

---

### `DELETE /api/inventory/sync`

Delete inventory by matching item name, quality, and station (looks up the database ID internally). Triggers all events.

**Auth:** Bearer token or session cookie

**Request body:**
| Field | Type | Description |
|-------|------|-------------|
| `item_name` | string | **Required.** Item name |
| `quality` | int | Quality to match |
| `station` | string | Station to match |

**Response:**
```json
{"status": "ok"}
```

---

### `GET /api/inventory/sync`

List the authenticated user's inventory (same as v1 GET but uses legacy response format).

**Auth:** Bearer token or session cookie

**Response:**
```json
[
  {"id": 1, "item_name": "Titanium", "quality": 100, "quantity_scu": 50.0, "station": "Area18", "synced_at": "..."}
]
```

---

### `GET /api/notifications`

List the authenticated user's notifications, most recent first.

**Auth:** Bearer token or session cookie

**Response:**
```json
[
  {
    "id": 1,
    "title": "Item Available",
    "body": "Someone added Titanium (Q100) to their inventory, matching your order request.",
    "source": "order",
    "read": 0,
    "created_at": "2026-05-20 12:00:00"
  }
]
```

---

### Orders

#### `GET /api/orders`

List orders. Use `?status=my` to filter to the authenticated user's own orders.

**Auth:** Bearer token or session cookie

**Response:**
```json
[
  {
    "id": 1,
    "item_name": "Titanium",
    "min_quality": 80,
    "quantity": 100,
    "notes": "Need for crafting",
    "status": "open",
    "created_by_discord": "123456789",
    "assigned_to_discord": "",
    "created_at": "2026-05-20 12:00:00"
  }
]
```

---

#### `POST /api/orders`

Create a new order request.

**Auth:** Bearer token or session cookie

**Request body:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `item_name` | string | — | **Required.** Item name |
| `min_quality` | int | `1` | Minimum acceptable quality |
| `quantity` | int | `1` | Quantity needed |
| `notes` | string | `""` | Optional notes |

**Response:**
```json
{"status": "ok", "order_id": 1}
```

---

#### `POST /api/orders/fulfill`

Mark an order as fulfilled by the authenticated user.

**Auth:** Bearer token or session cookie

**Request body:**
| Field | Type | Description |
|-------|------|-------------|
| `order_id` | int | **Required.** Order ID to fulfill |

**Response:**
```json
{"status": "ok", "order_id": 1}
```

---

### API Keys Management

#### `GET /api/keys`

List the authenticated user's API keys.

**Auth:** Bearer token or session cookie

**Response:**
```json
[
  {
    "key": "abc123...",
    "label": "PITS sync key",
    "last_used": "2026-05-20 12:00:00",
    "expires_at": null,
    "created_at": "2026-05-19 12:00:00"
  }
]
```

---

#### `POST /api/keys/create`

Generate a new API key. Returns the full key — it will not be shown again.

**Auth:** Bearer token or session cookie

**Request body:**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `label` | string | `"PITS sync key"` | Human-readable label |

**Response:**
```json
{"status": "ok", "key": "a1b2c3d4e5f6..."}
```

---

#### `POST /api/keys/revoke`

Revoke (delete) an API key.

**Auth:** Bearer token or session cookie

**Request body:**
| Field | Type | Description |
|-------|------|-------------|
| `key` | string | **Required.** The full key to revoke |

**Response:**
```json
{"status": "ok"}
```

---

### Autocomplete (Public)

#### `GET /api/autocomplete/items?q=<prefix>`

Search items by name prefix. No authentication required.

**Response:**
```json
["Titanium", "Titanium Alloy", "Titanium Carbide"]
```

---

#### `GET /api/autocomplete/stations?q=<prefix>`

Search stations by name prefix. No authentication required.

**Response:**
```json
["Area18", "Area20"]
```

---

## WebSocket Sync

JOCKstrap clients connect via WebSocket for real-time inventory sync. The WebSocket runs on the same port as HTTP (port `9200`) with HTTP upgrade, or on a separate port (`9201` by default).

### Authentication

Two methods are supported:

1. **Auth code** (preferred): obtain a one-time code from `POST /jock/login` in a browser, then send it via WebSocket.
2. **Client token**: obtain from the web UI, send via WebSocket.

### Message Protocol

All messages are JSON text frames.

**Client → Server:**
```json
{"type": "auth_code", "code": "abc123"}
{"type": "sync_inventory", "action": "add", "item_name": "Titanium", "quality": 100, "quantity_scu": 50.0, "station": "Area18"}
{"type": "ping"}
```

**Server → Client:**
```json
{"type": "auth_ok", "user": {"discord_id": "...", "discord_tag": "...", "username": "..."}}
{"type": "pong"}
{"type": "push_inventory", "action": "add", "itemid": "1", "item_name": "Titanium", "quality": "100", "quantity_scu": "50.0", "stationid": "5", "station": "Area18"}
```

---

## Error Codes

| HTTP Status | Meaning |
|-------------|---------|
| `200` | Success |
| `400` | Bad request (missing or invalid parameters) |
| `401` | Unauthorized (missing or invalid Bearer token) |
| `403` | Forbidden (authenticated but insufficient role) |
| `404` | Not found (endpoint or resource) |
| `500` | Internal server error |

---

## Database Backends

SHOWER supports two database backends configured via the `SHOWER_DB` environment variable:

| Format | Backend | Example |
|--------|---------|---------|
| File path | SQLite | `SHOWER_DB=/data/shower.db` |
| `mysql://` DSN | MySQL | `SHOWER_DB=mysql://user:pass@host:3306/shower` |

The API and application code are backend-agnostic — all SQL uses `{Q}` placeholders (`?` for SQLite, `%s` for MySQL) via the `Q` import from `db.py`.
