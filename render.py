import html as html_mod
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import db

_message_queue = []
_event_queue = []
_event_cond = threading.Condition()


def push_message(text, kind="success"):
    _message_queue.append({"text": text, "kind": kind})


def pop_messages():
    msgs = list(_message_queue)
    _message_queue.clear()
    return msgs


def push_event(event_type, data):
    with _event_cond:
        _event_queue.append({"type": event_type, "data": data})
        _event_cond.notify_all()

BASE_DIR = Path(__file__).resolve().parent

GUILD_NAME = "Sho.W.E.R Guild"

_stats_cache = None
_stats_cache_time = 0

def get_cached_stats(db):
    global _stats_cache, _stats_cache_time
    now = time.time()
    if _stats_cache and (now - _stats_cache_time) < 1800:
        return _stats_cache
    active_users = db.get_active_users_count()
    total_scu = db.get_total_scu()
    latest = db.get_latest_action_time()
    _stats_cache = (active_users, total_scu, latest)
    _stats_cache_time = now
    return _stats_cache


def esc(val):
    if val is None:
        return ""
    return html_mod.escape(str(val), quote=True)


def base_html(title, content, user=None, notif_count=0):
    nav = ""
    if user:
        badge = f'<span class="notif-badge">{notif_count}</span>' if notif_count > 0 else ""
        name = esc(user["display_name"] or user["username"] or "User")
        admin_link = f'<a class="button ghost" href="/admin">Admin</a>' if user["role_level"] >= 2 else ""
        nav = f"""
        <a class="button ghost" href="/dashboard">Dashboard</a>
        <a class="button ghost" href="/my-inventory">My Inventory</a>
        <a class="button ghost" href="/orders">Orders</a>
        <div class="user-dropdown" id="user-dropdown">
            <span class="dropdown-toggle button ghost" onclick="toggleDropdown(event)">{name} &#9662;</span>
            <div class="dropdown-menu">
                {admin_link}
                <a class="button ghost" href="/notifications">Notifications{badge}</a>
                <a class="button ghost" href="/api-keys">API Keys</a>
                <a class="button ghost" href="/auth/logout" style="color:var(--danger)">Logout</a>
            </div>
        </div>
        """
    else:
        nav = '<a class="button" href="/auth/login">Login with Discord</a>'
    return f"""<!doctype html>
<html lang="en" class="dark">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} — Sho.W.E.R</title>
<link rel="stylesheet" href="/static/styles.css?v=4">
<script src="/static/shower.js?v=2"></script>
</head>
<body>
<header class="topbar">
<div><h1>Sho.W.E.R</h1><p class="network-info">{esc(GUILD_NAME)}</p></div>
<nav class="nav-links">{nav}<button class="theme-toggle" onclick="toggleTheme()" aria-label="Toggle theme">&#x263E;</button></nav>
    </header>
    {notice_html({})}
    <main>{content}</main>
<footer class="footer">
  <span>Community Shopfront &middot; Workorder &middot; Exchange Registry — {esc(GUILD_NAME)}</span>
  <span>v{db.SHOWER_VERSION}</span>
</footer>
</body></html>"""


def setup_page():
    return """<!doctype html>
<html lang="en" class="dark">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Setup -- Sho.W.E.R</title>
<link rel="stylesheet" href="/static/styles.css?v=4">
<script src="/static/shower.js?v=2"></script>
<style>
.setup-wrap { max-width:600px; margin:40px auto; }
.setup-wrap h1 { font-size:24px; margin-bottom:4px; }
.setup-wrap p { color:var(--muted); font-size:13px; margin-bottom:20px; }
.setup-wrap .panel { margin-top:0; }
.setup-wrap label { display:block; color:var(--muted); font-size:12px; font-weight:600; text-transform:uppercase; margin-top:12px; margin-bottom:4px; }
.setup-wrap input, .setup-wrap select { width:100%; box-sizing:border-box; }
.setup-wrap .test-result { font-size:12px; margin-top:4px; }
.db-type-group { display:flex; gap:8px; margin-top:12px; }
.db-type-group button { flex:1; text-align:center; }
.db-type-group button.active { background:var(--green); }
</style>
</head>
<body>
<header class="topbar"><div><h1>Sho.W.E.R</h1><p class="network-info">Setup</p></div></header>
<main>
<div class="setup-wrap">
  <h1>Welcome to SHOWER</h1>
  <p>Configure your instance to get started.</p>
  <form id="setup-form" onsubmit="return saveSetup(event)">
  <section class="panel">
    <div class="section-heading"><h2>Discord OAuth</h2></div>
    <label>Client ID <span style="color:var(--danger)">*</span></label>
    <input type="text" name="discord_client_id" required>
    <label>Client Secret <span style="color:var(--danger)">*</span></label>
    <input type="password" name="discord_client_secret" required>
    <label>Redirect URI</label>
    <input type="text" name="discord_redirect_uri" placeholder="http://localhost:9200/auth/callback">
    <label>Guild ID</label>
    <input type="text" name="discord_guild_id">
    <label>Guild Name</label>
    <input type="text" name="discord_guild_name">
    <label>Admin Role ID</label>
    <input type="text" name="discord_admin_role">
    <label>Bot Token</label>
    <input type="password" name="discord_bot_token">
  </section>
  <section class="panel">
    <div class="section-heading"><h2>Database</h2></div>
    <label>Type</label>
    <select name="db_type" onchange="toggleDbType(this)">
      <option value="sqlite">SQLite (local file)</option>
      <option value="mysql">MySQL</option>
      <option value="odbc">SQL Server (ODBC)</option>
    </select>
    <div id="db-sqlite">
      <label>File Path</label>
      <input type="text" name="db_sqlite" value="shower_data/shower.db">
    </div>
    <div id="db-mysql" style="display:none">
      <label>Connection String</label>
      <input type="text" name="db_mysql" placeholder="mysql://user:pass@host:3306/db">
    </div>
    <div id="db-odbc" style="display:none">
      <label>Connection String</label>
      <input type="password" name="db_odbc" placeholder='Driver={ODBC Driver 18 for SQL Server};Server=tcp:...'>
    </div>
    <div style="margin-top:12px">
      <button type="button" class="button blue" onclick="testConnection()">Test Connection</button>
      <span id="db-test-result" class="test-result"></span>
    </div>
  </section>
  <div style="margin-top:16px;display:flex;gap:8px">
    <button type="submit" class="button green" style="flex:1">Save Configuration &amp; Restart</button>
  </div>
  </form>
</div>
</main>
<script>
var dbTested = false;
function toggleDbType(sel) {
  document.getElementById('db-sqlite').style.display = sel.value === 'sqlite' ? 'block' : 'none';
  document.getElementById('db-mysql').style.display = sel.value === 'mysql' ? 'block' : 'none';
  document.getElementById('db-odbc').style.display = sel.value === 'odbc' ? 'block' : 'none';
  dbTested = false;
  document.getElementById('db-test-result').textContent = '';
}
function testConnection() {
  var sel = document.querySelector('select[name=db_type]');
  var field = document.querySelector('[name=db_' + sel.value + ']');
  var result = document.getElementById('db-test-result');
  result.textContent = 'Testing...';
  result.style.color = 'var(--muted)';
  fetch('/setup/test-db', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({db_type: sel.value, connection_string: field.value})
  }).then(function(r) { return r.json(); }).then(function(d) {
    if (d.ok) {
      result.textContent = 'Connected!';
      result.style.color = 'var(--accent)';
      dbTested = true;
    } else {
      result.textContent = d.error;
      result.style.color = 'var(--danger)';
    }
  }).catch(function(e) {
    result.textContent = 'Request failed';
    result.style.color = 'var(--danger)';
  });
}
function saveSetup(e) {
  e.preventDefault();
  if (!dbTested && !confirm('Connection not tested. Save anyway?')) return;
  var btn = e.target.querySelector('button[type=submit]');
  btn.textContent = 'Saving...';
  btn.disabled = true;
  var form = document.getElementById('setup-form');
  var data = {};
  new FormData(form).forEach(function(v, k) { data[k] = v; });
  fetch('/setup/save', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  }).then(function(r) { return r.json(); }).then(function(d) {
    if (d.ok) {
      btn.textContent = 'Restarting...';
      setTimeout(function() { window.location.href = '/setup/restart'; }, 500);
    } else {
      btn.textContent = 'Save Failed';
      btn.disabled = false;
      alert(d.error);
    }
  }).catch(function(e) {
    btn.textContent = 'Save Failed';
    btn.disabled = false;
    alert(e.message);
  });
}
</script>
</body></html>"""


def page_panel(heading, body_html, back_url=None, extra_actions=""):
    back = f'<a class="button ghost" href="{esc(back_url)}">Back</a>' if back_url else ""
    return f"""<section class="panel">
<div class="section-heading"><h2>{esc(heading)}</h2><div>{extra_actions}{back}</div></div>
{body_html}
</section>"""


def notice_html(qs):
    html = ""
    for key, cls in [("created", "success"), ("fulfilled", "success"), ("error", "error")]:
        val = qs.get(key, "")
        if val:
            msg = val if val != "1" else key.replace("_", " ").title()
            html += f'<div class="messages"><div class="message {cls}">{esc(msg)}<button class="dismiss-btn" onclick="this.parentElement.remove()">dismiss</button></div></div>'
            break
    for msg in pop_messages():
        html += f'<div class="messages"><div class="message {msg["kind"]}">{esc(msg["text"])}<button class="dismiss-btn" onclick="this.parentElement.remove()">dismiss</button></div></div>'
    return html


def api_keys_section(user, db):
    keys = db.get_api_keys(user["discord_id"])
    rows = ""
    for k in keys:
        short = k["key"][:16] + "..."
        rows += f"""<tr><td><code>{esc(short)}</code></td><td>{esc(k['label'])}</td><td>{esc(k['last_used'] or 'never')}</td><td>{esc(k['created_at'])}</td>
        <td class="cell-actions" style="min-width:0">
            <form method="post" action="/api/keys/revoke" style="display:inline" onsubmit="event.preventDefault();if(!confirm('Revoke this API key? This cannot be undone.'))return;fetch(this.action,{{method:'POST',body:new URLSearchParams(new FormData(this))}}).then(r=>r.json()).then(d=>{{if(d.status=='ok')location.reload()}})">
                <input type="hidden" name="key" value="{esc(k['key'])}">
                <button type="submit" class="button ghost" style="color:var(--danger);font-size:12px">Revoke</button>
            </form>
        </td></tr>"""
    if not rows:
        rows = '<tr><td colspan="5" class="empty">No API keys yet.</td></tr>'

    return f"""<div id="new-key-msg"></div>
<div style="margin-bottom:12px">
    <button class="button green" onclick="createKey()">Generate New Key</button>
</div>
<div class="table-wrap"><table><thead><tr><th>Key</th><th>Label</th><th>Last Used</th><th>Created</th><th class="cell-actions" style="min-width:0">Actions</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="muted" style="margin-top:8px;font-size:13px">Use these keys in your PITS extension settings as <code>Authorization: Bearer &lt;key&gt;</code> to sync without Discord re-authentication.</p>"""


def api_keys_page(user, db):
    if not user:
        return base_html("API Keys", page_panel("API Keys", '<p class="muted">Login to manage API keys.</p>'))
    return base_html("API Keys", page_panel("API Keys", api_keys_section(user, db), back_url="/dashboard"), user)


def dashboard(user, db, qs):
    if not user:
        return base_html("Welcome", f"""<section class="panel" style="text-align:center;padding:60px">
        <h2 style="font-size:28px;margin-bottom:16px">Sho.W.E.R</h2>
        <p style="color:var(--muted);margin-bottom:24px">{esc(GUILD_NAME)}</p>
        <a class="button green" href="/auth/login" style="font-size:18px;padding:12px 32px">Login with Discord</a>
        </section>""")
    inv_count = len(db.get_user_inventory(user["discord_id"]))
    notifs = db.get_notifications(user["discord_id"], limit=5)
    unread = sum(1 for n in notifs if not n["read"])

    active_users, total_scu, latest = get_cached_stats(db)
    if latest:
        latest_display = latest[:19].replace("T", " ")
    else:
        latest_display = "—"
    total_scu_display = f"{total_scu:,.2f}"
    last_updated_str = time.strftime("%H:%M", time.localtime(_stats_cache_time))

    stats = f"""<section class="panel stats-panel" style="margin-bottom:16px">
    <div style="display:flex;gap:24px;justify-content:space-around;padding:16px 0;text-align:center">
        <div><div class="stat-value" style="font-size:28px;font-weight:700">{active_users}</div><div class="stat-label" style="font-size:12px;text-transform:uppercase;letter-spacing:0.05em;margin-top:4px">Active Users</div></div>
        <div><div class="stat-value" style="font-size:28px;font-weight:700">{total_scu_display}</div><div class="stat-label" style="font-size:12px;text-transform:uppercase;letter-spacing:0.05em;margin-top:4px">Total SCU</div></div>
        <div><div class="stat-value" style="font-size:14px;font-weight:600">{latest_display}</div><div class="stat-label" style="font-size:12px;text-transform:uppercase;letter-spacing:0.05em;margin-top:4px">Latest Action</div></div>
    </div>
    <div style="text-align:right;font-size:11px;color:rgba(255,255,255,0.6);margin-top:8px">Last updated: {last_updated_str}</div>
    </section>"""

    metrics = f"""<div class="summary-grid">
    <a class="metric" href="/my-inventory"><span>Your Items</span><strong>{inv_count}</strong></a>
    <a class="metric" href="/orders"><span>Open Orders</span><strong>{len([o for o in db.get_open_orders()])}</strong></a>
    <a class="metric" href="/notifications"><span>Notifications</span><strong>{unread}</strong></a>
    </div>"""

    search = qs.get("q", "").strip()
    qual_min = qs.get("qual_min")
    qual_max = qs.get("qual_max")
    qty_min = qs.get("qty_min")
    qual_min = int(qual_min) if qual_min else None
    qual_max = int(qual_max) if qual_max else None
    qty_min = float(qty_min) if qty_min else None
    items = db.all_inventory(limit=200, search=search or None, qual_min=qual_min, qual_max=qual_max, qty_min=qty_min)
    rows = ""
    for item in items:
        rows += f"<tr><td>{esc(item['item_name'])}</td><td>{item['quality']}</td><td>{item['quantity_scu']}</td><td>{esc(item['station'] or '')}</td><td>{esc(item['display_name'] or 'Unknown')}</td><td class='cell-actions' style='min-width:0'><button class='button blue' onclick=''>Order</button></td></tr>"
    if not rows:
        if search or qual_min is not None or qual_max is not None or qty_min is not None:
            rows = '<tr><td colspan="6" class="empty">No items match your filters.</td></tr>'
        else:
            rows = '<tr><td colspan="6" class="empty">No inventory synced yet.</td></tr>'
    qmin = str(qual_min) if qual_min is not None else "0"
    qmax = str(qual_max) if qual_max is not None else "1000"
    qtmin = str(qty_min) if qty_min is not None else ""
    filter_bar = f"""<div class="filter-bar">
    <form method="get" class="search-form">
        <span class="search-wrap">
        <input type="search" name="q" placeholder="Search items..." value="{esc(search)}" >
        <div class="search-suggestions" id="inv-search-suggestions"></div>
        </span>
        <button class="icon-btn" type="submit" aria-label="Search" title="Search items">&#x1F50D;</button>
        <input type="hidden" name="qual_min" value="{qmin}">
        <input type="hidden" name="qual_max" value="{qmax}">
        <input type="hidden" name="qty_min" value="{qtmin}">
    </form>
    <button class="icon-btn" onclick="showFilter('filter')" aria-label="Filter" title="Filter"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" style="vertical-align:middle"><path d="M1 2h14l-5 7v4l-4 1.5V9L1 2z"/></svg></button>
    </div>"""
    inv_body = f"""<div id="filter-overlay" class="modal-overlay" style="display:none" onclick="if(event.target==this)hideFilter('filter')">
    <div class="modal-content">
        <div class="modal-header">
        <span>Filter Inventory</span>
        <button class="modal-close" onclick="hideFilter('filter')">&times;</button>
        </div>
        <form method="get">
        <input type="hidden" name="q" value="{esc(search)}">
        <div class="filter-group">
            <label>Quality</label>
            <div class="dual-slider">
            <div class="slider-track"></div>
            <input type="range" class="slider-thumb" name="qual_min" min="0" max="1000" value="{qmin}" oninput="syncQual(event)">
            <input type="range" class="slider-thumb slider-max" name="qual_max" min="0" max="1000" value="{qmax}" oninput="syncQual(event)">
            </div>
            <div class="slider-values" id="qual-values">{qmin} &ndash; {qmax}</div>
        </div>
        <div class="filter-group">
            <label>Minimum QTY</label>
            <div class="qty-slider-wrap">
            <div class="slider-track"></div>
            <input type="range" id="qty-slider" min="0" max="48" value="0" oninput="updateQtyFilter(this)">
            </div>
            <input type="hidden" name="qty_min" id="qty-min-cents" value="{qtmin}">
            <div class="slider-values" id="qty-display">0.00 SCU</div>
        </div>
        <div style="margin-top:16px;display:flex;gap:8px">
            <button type="submit">Apply</button>
            <a class="button ghost" href="/dashboard">Clear</a>
        </div>
        </form>
    </div>
    </div>
    <script>
    setupAutocomplete('inv-search-input','inv-search-suggestions','/api/autocomplete/items');
    (function() {{ initQtyFilter("{qtmin}" || "0"); syncQualFromStatic(); }})();
    </script>
    <div class="table-wrap"><table><thead><tr><th>Item</th><th>Quality</th><th>QTY (SCU)</th><th>Station</th><th>User</th><th class="cell-actions" style="min-width:0">Actions</th></tr></thead><tbody>{rows}</tbody></table></div>"""
    content = f"""{stats}{metrics}{page_panel("Community Inventory", inv_body, extra_actions=filter_bar)}"""
    return base_html("Dashboard", content, user, unread)


def my_inventory_page(user, db, qs):
    notice = notice_html(qs)
    items = db.get_user_inventory(user["discord_id"])
    rows = ""
    for item in items:
        rows += f"""<tr>
            <td>{esc(item['item_name'])}</td>
            <td>{item['quality']}</td>
            <td>{item['quantity_scu']}</td>
            <td>{esc(item['station'] or '')}</td>
            <td>{esc(item['synced_at'] or '')}</td>
            <td class="cell-actions" style="min-width:0">
                <form action="/my-inventory/delete" method="post" onsubmit="return confirm('Delete this item?')" style="display:inline">
                    <input type="hidden" name="inv_id" value="{item['id']}">
                    <button class="button ghost" style="color:var(--danger)">Delete</button>
                </form>
            </td>
        </tr>"""
    if not rows:
        rows = '<tr><td colspan="6" class="empty">No items in your inventory. Add one below.</td></tr>'

    body = f"""{notice}
    <form action="/my-inventory/add" method="post" class="inline-form" style="margin-bottom:16px;flex-wrap:wrap">
        <div style="display:inline-block;position:relative;vertical-align:middle">
            <label for="myinv-item-input" style="display:block;font-size:11px;color:var(--muted);margin-bottom:2px">Item</label>
            <span class="search-wrap" style="display:inline-block">
                <input type="text" name="item_name" id="myinv-item-input" placeholder="Item name"  required style="width:180px" class="sm-input">
                <div class="search-suggestions" id="myinv-item-suggestions"></div>
            </span>
        </div>
        <div style="display:inline-block;position:relative;vertical-align:middle">
            <label for="myinv-station-input" style="display:block;font-size:11px;color:var(--muted);margin-bottom:2px">Station</label>
            <span class="search-wrap" style="display:inline-block">
                <input type="text" name="station" id="myinv-station-input" placeholder="Station (optional)"  style="width:140px" class="sm-input">
                <div class="search-suggestions" id="myinv-station-suggestions"></div>
            </span>
        </div>
        <div style="display:inline-block;position:relative;vertical-align:middle">
            <label for="myinv-quality" style="display:block;font-size:11px;color:var(--muted);margin-bottom:2px">Quality</label>
            <input name="quality" id="myinv-quality" type="number" min="0" placeholder="500" required class="sm-input" style="width:80px">
        </div>
        <div style="display:inline-block;position:relative;vertical-align:middle">
            <label for="myinv-qty" style="display:block;font-size:11px;color:var(--muted);margin-bottom:2px">QTY (SCU)</label>
            <input name="quantity_scu" id="myinv-qty" type="number" min="0.01" step="0.01" placeholder="1.00" required class="sm-input" style="width:100px">
        </div>
        <div style="display:inline-block;vertical-align:middle">
            <div style="font-size:11px;color:var(--muted);margin-bottom:2px;visibility:hidden">&#xa0;</div>
            <button type="submit" class="button green">Add</button>
        </div>
    </form>
    <div class="table-wrap"><table><thead><tr><th>Item</th><th>Qual</th><th>QTY SCU</th><th>Station</th><th>Added</th><th></th></tr></thead><tbody>{rows}</tbody></table></div>
    <script>setupAutocomplete('myinv-item-input','myinv-item-suggestions','/api/autocomplete/items');setupAutocomplete('myinv-station-input','myinv-station-suggestions','/api/autocomplete/stations');</script>"""
    return base_html("My Inventory", page_panel("My Inventory", body), user, 0)


def inventory_browse(user, db, qs):
    search = qs.get("q", "").strip()
    qual_min = qs.get("qual_min")
    qual_max = qs.get("qual_max")
    qty_min = qs.get("qty_min")
    qual_min = int(qual_min) if qual_min else None
    qual_max = int(qual_max) if qual_max else None
    qty_min = float(qty_min) if qty_min else None
    items = db.all_inventory(limit=200, search=search or None, qual_min=qual_min, qual_max=qual_max, qty_min=qty_min)
    rows = ""
    for item in items:
        rows += f"<tr><td>{esc(item['item_name'])}</td><td>{item['quality']}</td><td>{item['quantity_scu']}</td><td>{esc(item['station'] or '')}</td><td>{esc(item['display_name'] or 'Unknown')}</td><td class='cell-actions' style='min-width:0'><button class='button blue' onclick=''>Order</button></td></tr>"
    if not rows:
        if search or qual_min is not None or qual_max is not None or qty_min is not None:
            rows = '<tr><td colspan="6" class="empty">No items match your filters.</td></tr>'
        else:
            rows = '<tr><td colspan="6" class="empty">No inventory synced yet.</td></tr>'
    qmin = str(qual_min) if qual_min is not None else "0"
    qmax = str(qual_max) if qual_max is not None else "1000"
    qtmin = str(qty_min) if qty_min is not None else ""
    body = f"""<div class="section-heading" style="margin-bottom:12px">
    <div class="filter-bar">
    <form method="get" class="search-form">
        <span class="search-wrap">
        <input type="search" name="q" placeholder="Search items..." value="{esc(search)}" >
        <div class="search-suggestions" id="inv-search-suggestions"></div>
        </span>
        <button class="icon-btn" type="submit" aria-label="Search" title="Search items">&#x1F50D;</button>
        <input type="hidden" name="qual_min" value="{qmin}">
        <input type="hidden" name="qual_max" value="{qmax}">
        <input type="hidden" name="qty_min" value="{qtmin}">
    </form>
    <button class="icon-btn" onclick="showFilter('filter')" aria-label="Filter" title="Filter"><svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" style="vertical-align:middle"><path d="M1 2h14l-5 7v4l-4 1.5V9L1 2z"/></svg></button>
    </div>
    </div>
    <div id="filter-overlay" class="modal-overlay" style="display:none" onclick="if(event.target==this)hideFilter('filter')">
    <div class="modal-content">
        <div class="modal-header">
        <span>Filter Inventory</span>
        <button class="modal-close" onclick="hideFilter('filter')">&times;</button>
        </div>
        <form method="get">
        <input type="hidden" name="q" value="{esc(search)}">
        <div class="filter-group">
            <label>Quality</label>
            <div class="dual-slider">
            <div class="slider-track"></div>
            <input type="range" class="slider-thumb" name="qual_min" min="0" max="1000" value="{qmin}" oninput="syncQual(event)">
            <input type="range" class="slider-thumb slider-max" name="qual_max" min="0" max="1000" value="{qmax}" oninput="syncQual(event)">
            </div>
            <div class="slider-values" id="qual-values">{qmin} &ndash; {qmax}</div>
        </div>
        <div class="filter-group">
            <label>Minimum QTY</label>
            <div class="qty-slider-wrap">
            <div class="slider-track"></div>
            <input type="range" id="qty-slider" min="0" max="48" value="0" oninput="updateQtyFilter(this)">
            </div>
            <input type="hidden" name="qty_min" id="qty-min-cents" value="{qtmin}">
            <div class="slider-values" id="qty-display">0.00 SCU</div>
        </div>
        <div style="margin-top:16px;display:flex;gap:8px">
            <button type="submit">Apply</button>
            <a class="button ghost" href="/inventory">Clear</a>
        </div>
        </form>
    </div>
    </div>
    <script>
    setupAutocomplete('inv-search-input','inv-search-suggestions','/api/autocomplete/items');
    (function() {{ initQtyFilter("{qtmin}" || "0"); syncQualFromStatic(); }})();
    </script>
    <div class="table-wrap"><table><thead><tr><th>Item</th><th>Quality</th><th>QTY (SCU)</th><th>Station</th><th>User</th><th class="cell-actions" style="min-width:0">Actions</th></tr></thead><tbody>{rows}</tbody></table></div>"""
    notif_count = len(db.get_notifications(user["discord_id"])) if user else 0
    return base_html("Inventory", page_panel("Community Inventory", body), user, notif_count)


def orders_page(user, db, qs):
    if not user:
        return base_html("Orders", page_panel("Orders", '<p class="muted">Login to view orders.</p>'))
    notice = notice_html(qs)
    open_orders = db.get_open_orders()
    rows = ""
    for o in open_orders:
        is_mine = o["discord_id"] == user["discord_id"]
        action = ""
        if not is_mine:
            action = f"""<form action="/orders/fulfill" method="post" style="display:inline">
            <input type="hidden" name="order_id" value="{o['id']}">
            <button type="submit" class="button blue">I Have This</button></form>"""
        elif o["status"] == "open":
            action = '<span class="pill hold">Your request</span>'
        rows += f"<tr><td>{esc(o['item_name'])}</td><td>{o['min_quality']}</td><td>{o['quantity']}</td><td>{action}</td></tr>"
    if not rows:
        rows = '<tr><td colspan="4" class="empty">No open order requests.</td></tr>'

    my_orders = db.get_user_orders(user["discord_id"])
    my_rows = ""
    for o in my_orders:
        status_cls = "ok" if o["status"] == "fulfilled" else "hold"
        my_rows += f"<tr><td>{esc(o['item_name'])}</td><td>{o['min_quality']}</td><td>{o['quantity']}</td><td><span class='pill {status_cls}'>{esc(o['status'])}</span></td></tr>"
    if not my_rows:
        my_rows = '<tr><td colspan="4" class="empty">No requests.</td></tr>'

    body = f"""{notice}
    <h3 style="margin-bottom:8px">Open Requests</h3>
    <div class="table-wrap"><table><thead><tr><th>Item</th><th>Min Qual</th><th>QTY</th><th>Action</th></tr></thead><tbody>{rows}</tbody></table></div>
    <h3 style="margin:24px 0 8px">My Requests</h3>
    <div class="table-wrap"><table><thead><tr><th>Item</th><th>Min Qual</th><th>QTY</th><th>Status</th></tr></thead><tbody>{my_rows}</tbody></table></div>"""
    notif_count = len(db.get_notifications(user["discord_id"]))
    create_btn = '<a class="button green" href="/orders/create">Create Order Request</a>'
    return base_html("Orders", page_panel("Order Requests", body, extra_actions=create_btn), user, notif_count)


def order_create_form(user):
    if not user:
        return base_html("Create Order", page_panel("Create Order", '<p class="muted">Login first.</p>'))
    body = """<form method="post" action="/orders/create" class="inline-form" style="flex-direction:column;align-items:stretch">
    <input type="text" name="item_name" placeholder="Item name" required>
    <input type="number" name="min_quality" placeholder="Minimum quality" min="1" max="1000" value="1" required>
    <input type="number" name="quantity" placeholder="Quantity" min="1" value="1" required>
    <textarea name="notes" placeholder="Notes (optional)" style="min-height:60px;resize:vertical"></textarea>
    <button type="submit">Submit Request</button>
    </form>"""
    return base_html("Create Order", page_panel("Create Order Request", body, back_url="/orders"))


def notifications_page(user, db):
    if not user:
        return base_html("Notifications", page_panel("Notifications", '<p class="muted">Login first.</p>'))
    notifs = db.get_notifications(user["discord_id"])
    items = ""
    for n in notifs[:50]:
        cls = "" if n["read"] else "unread"
        items += f"""<div class="notif {cls}"><div class="notif-body">
        <div class="notif-msg"><strong>{esc(n['title'])}</strong> {esc(n['body'])}</div>
        <div class="notif-time">{esc(n['created_at'] or '')}</div>
        </div></div>"""
    if not items:
        items = '<p class="muted">No notifications.</p>'
    return base_html("Notifications", page_panel("Notifications", f'<div class="notif-list">{items}</div>'), user, 0)


def admin_page(user, db_obj, qs, discord_roles=None, bot_token_set=False):
    level = db_obj.get_user_role_level(user["discord_id"])
    is_admin = level >= 3
    is_mod = level >= 2
    notice = notice_html(qs)

    # --- Role Management ---
    roles = db_obj.get_roles()
    role_rows = ""
    for r in roles:
        env_tag = '<span style="color:var(--muted);font-size:11px">SET IN ENV</span>' if r["is_env"] else ""
        actions = ""
        if not r["is_env"]:
            drid = r["discord_role_id"] or ""
            actions = f"""
            <button class="button ghost" style="font-size:12px" onclick="editRole({r['id']},'{esc(r['name'])}',{r['level']},'{esc(drid)}')">Edit</button>
            <form method="post" action="/admin" style="display:inline" onsubmit="return confirm('Delete role {esc(r['name'])}?')">
                <input type="hidden" name="action" value="delete_role">
                <input type="hidden" name="role_id" value="{r['id']}">
                <button type="submit" class="button ghost" style="color:var(--danger);font-size:12px">Delete</button>
            </form>""" if is_admin else ""
        else:
            actions = env_tag
        level_label = ["Blocked", "User", "Mod", "Admin"][r["level"]] if r["level"] < 4 else "Admin"
        role_rows += f"<tr><td>{esc(r['name'])}</td><td>{level_label}</td><td class='cell-actions' style='min-width:0'>{actions}</td></tr>"
    if not role_rows:
        role_rows = '<tr><td colspan="3" class="empty">No roles defined.</td></tr>'

    role_overlay = ""
    if is_admin:
        discord_role_opts = ""
        if discord_roles:
            opts = ['<option value="">None</option>']
            for dr in discord_roles:
                opts.append(f'<option value="{dr["id"]}">{esc(dr["name"])}</option>')
            discord_role_field = f'<label>Discord Role <span style="color:var(--muted);font-size:11px">(from guild)</span></label><select name="discord_role_id" id="role-discord-id" style="width:100%">{"".join(opts)}</select>'
        else:
            discord_role_field = '<label>Discord Role ID <span style="color:var(--muted);font-size:11px">(bot disconnected)</span></label><input type="text" name="discord_role_id" id="role-discord-id" placeholder="Discord Role ID" style="width:100%">'
        role_overlay = f"""<div id="role-overlay" class="modal-overlay" style="display:none" onclick="if(event.target==this)document.getElementById('role-overlay').style.display='none'">
        <div class="modal-content" style="max-width:400px">
            <div class="modal-header"><span id="role-modal-title">Add Role</span>
            <button class="modal-close" onclick="document.getElementById('role-overlay').style.display='none'">&times;</button></div>
            <form method="post" action="/admin" id="role-form">
                <input type="hidden" name="action" id="role-action" value="add_role">
                <input type="hidden" name="role_id" id="role-id" value="">
                <div class="filter-group">
                    <label>Role Name</label>
                    <input type="text" name="name" id="role-name" required placeholder="Role name" style="width:100%">
                </div>
                <div class="filter-group">
                    {discord_role_field}
                </div>
                <div class="filter-group">
                    <label>Permission Level</label>
                    <div style="display:flex;gap:12px;margin-top:4px">
                        <label><input type="radio" name="level" value="0"> Blocked</label>
                        <label><input type="radio" name="level" value="1" checked> User</label>
                        <label><input type="radio" name="level" value="2"> Mod</label>
                        <label><input type="radio" name="level" value="3"> Admin</label>
                    </div>
                </div>
                <div style="margin-top:16px;display:flex;gap:8px">
                    <button type="submit" class="button green">Save</button>
                    <button type="button" class="button ghost" onclick="document.getElementById('role-overlay').style.display='none'">Cancel</button>
                </div>
            </form>
        </div>
        </div>"""

    role_mgmt = f"""{role_overlay}
    <div style="margin-bottom:12px">
        <button class="button green" onclick="document.getElementById('role-overlay').style.display='flex'" {'style="display:none"' if not is_admin else ''}>Add Role</button>
    </div>
    <div class="table-wrap"><table><thead><tr><th>Role</th><th>Level</th><th class='cell-actions' style='min-width:0'>Actions</th></tr></thead><tbody>{role_rows}</tbody></table></div>"""

    # --- User Management ---
    users = db_obj.get_all_users()
    user_rows = ""
    for u in users:
        user_level = db_obj.get_user_role_level(u["discord_id"])
        target_is_mod = user_level >= 2
        can_modify = is_admin or (not target_is_mod)
        action_btns = ""
        if can_modify and is_mod:
            roles_opts = "".join(f'<option value="{rr["id"]}" {"selected" if (u["role_id"] or 2)==rr["id"] else ""}>{esc(rr["name"])}</option>' for rr in roles)
            role_sel = f"""<form method="post" action="/admin" style="display:inline">
                <input type="hidden" name="action" value="set_user_role">
                <input type="hidden" name="discord_id" value="{u['discord_id']}">
                <select name="role_id" onchange="this.form.submit()" style="font-size:12px;padding:2px 4px">{roles_opts}</select>
            </form>"""
            token_clear = f"""<form method="post" action="/admin" style="display:inline" onsubmit="return confirm('Revoke all API keys for {esc(u['display_name'] or u['username'])}?')">
                <input type="hidden" name="action" value="clear_user_api_keys">
                <input type="hidden" name="discord_id" value="{u['discord_id']}">
                <button type="submit" class="button ghost" style="color:var(--danger);font-size:12px">Clear Keys</button>
            </form>"""
            ban_action = "unban" if u["banned"] else "ban"
            ban_btn = f"""<form method="post" action="/admin" style="display:inline" onsubmit="return confirm('{ban_action.title()} {esc(u['display_name'] or u['username'])}?')">
                <input type="hidden" name="action" value="set_user_banned">
                <input type="hidden" name="discord_id" value="{u['discord_id']}">
                <input type="hidden" name="banned" value="{'0' if u['banned'] else '1'}">
                <button type="submit" class="button ghost" style="color:{'var(--green)' if u['banned'] else 'var(--danger)'};font-size:12px">{'Unban' if u['banned'] else 'Ban'}</button>
            </form>"""
            del_btn = ""
            if is_admin:
                del_btn = f"""<form method="post" action="/admin" style="display:inline" onsubmit="return confirm('Permanently delete {esc(u['display_name'] or u['username'])} and all their data? This cannot be undone.')">
                    <input type="hidden" name="action" value="delete_user">
                    <input type="hidden" name="discord_id" value="{u['discord_id']}">
                    <button type="submit" class="button ghost" style="color:var(--danger);font-size:12px">Delete</button>
                </form>"""
            action_btns = f'<div style="display:flex;gap:4px">{token_clear}{ban_btn}{del_btn}</div>'
        else:
            role_sel = esc(u["role_name"] or "User")
        banned_tag = ' <span style="color:var(--danger);font-size:11px">[BANNED]</span>' if u["banned"] else ""
        last_activity = esc(u["last_seen"] or u["created_at"] or "")
        user_rows += f"<tr><td>{esc(u['display_name'] or u['username'])}{banned_tag}</td><td>{role_sel}</td><td>{last_activity}</td><td class='cell-actions' style='min-width:0'>{action_btns}</td></tr>"
    if not user_rows:
        user_rows = '<tr><td colspan="4" class="empty">No users yet.</td></tr>'

    user_mgmt = f"""<div class="table-wrap"><table><thead><tr><th>User</th><th>Role</th><th>Last Activity</th><th class='cell-actions' style='min-width:0'>Actions</th></tr></thead><tbody>{user_rows}</tbody></table></div>"""

    # --- Custom Fields ---
    items = db_obj.get_all_items()
    item_rows = ""
    for item in items:
        del_form = ""
        if is_admin:
            del_form = f"""<form method="post" action="/admin" style="display:inline" onsubmit="return confirm('Delete item {esc(item['name'])}?')">
                <input type="hidden" name="action" value="delete_item">
                <input type="hidden" name="item_id" value="{item['id']}">
                <button type="submit" class="button ghost" style="color:var(--danger);font-size:12px">Delete</button>
            </form>"""
        item_rows += f"<tr><td>{esc(item['name'])}</td><td class='cell-actions' style='min-width:0'>{del_form}</td></tr>"
    if not item_rows:
        item_rows = '<tr><td colspan="2" class="empty">No custom items.</td></tr>'

    stations = db_obj.get_all_stations()
    station_rows = ""
    for s in stations:
        del_form = ""
        if is_admin:
            del_form = f"""<form method="post" action="/admin" style="display:inline" onsubmit="return confirm('Delete station {esc(s['name'])}?')">
                <input type="hidden" name="action" value="delete_station">
                <input type="hidden" name="station_id" value="{s['id']}">
                <button type="submit" class="button ghost" style="color:var(--danger);font-size:12px">Delete</button>
            </form>"""
        station_rows += f"<tr><td>{esc(s['name'])}</td><td class='cell-actions' style='min-width:0'>{del_form}</td></tr>"
    if not station_rows:
        station_rows = '<tr><td colspan="2" class="empty">No custom stations.</td></tr>'

    add_item_form = ""
    add_station_form = ""
    if is_admin:
        cats = db_obj.get_itemcategories()
        cat_opts = "".join(f'<option value="{c["id"]}">{esc(c["name"])}</option>' for c in cats)
        cat_select = f'<select name="catid" class="sm-input" style="width:120px">{cat_opts}</select>'
        add_item_form = f"""<form method="post" action="/admin" class="inline-form" style="margin-bottom:12px">
            <input type="hidden" name="action" value="add_item">
            <input type="number" name="item_id" placeholder="ID" class="sm-input" style="width:60px" min="1">
            <input type="text" name="name" placeholder="Item name" required class="sm-input" style="width:180px">
            {cat_select}
            <input type="text" name="code" placeholder="Code" class="sm-input" style="width:70px">
            <label style="font-size:12px;display:inline-flex;align-items:center;gap:4px">
                <input type="checkbox" name="hasquality" value="1" checked> Quality
            </label>
            <button type="submit" class="button green">Add Item</button>
        </form>"""
        add_station_form = f"""<form method="post" action="/admin" class="inline-form">
            <input type="hidden" name="action" value="add_station">
            <input type="number" name="station_id" placeholder="ID" required class="sm-input" style="width:60px" min="1">
            <input type="text" name="name" placeholder="Station name" required class="sm-input" style="width:180px">
            <button type="submit" class="button green">Add Station</button>
        </form>"""

    custom_fields = f"""
    <h3 style="margin-bottom:8px">Items</h3>
    {add_item_form}
    <div class="table-wrap"><table><thead><tr><th>Name</th><th class='cell-actions' style='min-width:0'>Actions</th></tr></thead><tbody>{item_rows}</tbody></table></div>
    <hr style="border:none;border-top:1px solid var(--line);margin:16px 0">
    <h3 style="margin-bottom:8px">Stations</h3>
    {add_station_form}
    <div class="table-wrap"><table><thead><tr><th>Name</th><th class='cell-actions' style='min-width:0'>Actions</th></tr></thead><tbody>{station_rows}</tbody></table></div>"""

    # --- Server Settings ---
    guild_name = db_obj.get_config("guild_name", GUILD_NAME)
    config_form = ""
    if is_admin:
        config_form = f"""<form method="post" action="/admin" class="inline-form" style="flex-direction:column;align-items:stretch">
            <input type="hidden" name="action" value="save_config">
            <div class="filter-group">
                <label>Guild Name</label>
                <input type="text" name="guild_name" value="{esc(guild_name)}" style="width:100%">
            </div>
            <hr style="border:none;border-top:1px solid var(--line);margin:16px 0">
            <p class="muted" style="font-size:12px;margin-bottom:8px">Leave blank to keep current values.</p>
            <div class="filter-group">
                <label>Discord Client ID</label>
                <input type="text" name="discord_client_id" placeholder="New Client ID" style="width:100%">
            </div>
            <div class="filter-group">
                <label>Discord Client Secret</label>
                <input type="password" name="discord_client_secret" placeholder="New Client Secret" style="width:100%">
            </div>
            <div class="filter-group">
                <label>Discord Bot Token</label>
                <input type="password" name="discord_bot_token" placeholder="New Bot Token" style="width:100%">
            </div>
            <div style="margin-top:16px">
                <button type="submit" class="button green">Save Settings</button>
            </div>
        </form>
        <hr style="border:none;border-top:1px solid var(--line);margin:16px 0">
        <h3 style="margin-bottom:8px">Database</h3>
        <p class="muted" style="font-size:12px;margin-bottom:8px">Status: <strong>Configured</strong></p>
        <form method="post" action="/admin" class="inline-form" style="flex-direction:column;align-items:stretch">
            <input type="hidden" name="action" value="change_db">
            <div class="filter-group">
                <label>Connection String (leave blank to keep current)</label>
                <input type="password" name="dsn" placeholder="New connection string" style="width:100%" autocomplete="off">
            </div>
            <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap">
                <button type="submit" class="button blue">Save Database</button>
                <button type="button" class="button ghost" onclick="restartServer()">Restart App</button>
            </div>
        </form>
        <div style="margin-top:12px">
            <form method="post" action="/admin" style="display:inline" onsubmit="return confirm('Reset database? All data will be lost and tables recreated from seed.')">
                <input type="hidden" name="action" value="reset_db">
                <button type="submit" class="button red" style="background:var(--red)">Reset Database</button>
            </form>
        </div>
        <script>
        function restartServer() {{
            if (confirm('Restart SHOWER? The page will reload.')) {{
                fetch('/setup/restart').then(function() {{ location.reload(); }});
            }}
        }}
        </script>"""

    server_settings = config_form or '<p class="muted">Admin access required.</p>'

    bot_card = ""
    if is_admin:
        bot_status = "Connected" if bot_token_set else "Disconnected"
        bot_status_cls = "ok" if bot_token_set else "error"
        bot_card = f"""<section class="panel">
        <div class="section-heading" onclick="toggleSection(this)" style="cursor:pointer">
            <h2>Bot Settings <span class="collapse-arrow" style="font-size:12px;margin-left:6px;color:var(--muted)">&#9654;</span></h2>
        </div>
        <div class="collapse-content" style="display:none">
            <p style="margin-bottom:12px">Status: <span class="pill {bot_status_cls}">{bot_status}</span></p>
            <div style="display:flex;gap:8px">
                <form method="post" action="/admin" style="display:inline">
                    <input type="hidden" name="action" value="reboot_bot">
                    <button type="submit" class="button blue">Reboot Bot</button>
                </form>
                <form method="post" action="/admin" style="display:inline">
                    <input type="hidden" name="action" value="bot_invite">
                    <button type="submit" class="button green">Generate Invite Link</button>
                </form>
            </div>
        </div>
        </section>"""

    cards = f"""
    <section class="panel">
        <div class="section-heading" onclick="toggleSection(this)" style="cursor:pointer">
            <h2>Role Management <span class="collapse-arrow" style="font-size:12px;margin-left:6px;color:var(--muted)">&#9654;</span></h2>
        </div>
        <div class="collapse-content" style="display:none">{role_mgmt}</div>
    </section>
    <section class="panel">
        <div class="section-heading" onclick="toggleSection(this)" style="cursor:pointer">
            <h2>User Management <span class="collapse-arrow" style="font-size:12px;margin-left:6px;color:var(--muted)">&#9654;</span></h2>
        </div>
        <div class="collapse-content" style="display:none">{user_mgmt}</div>
    </section>
    <section class="panel">
        <div class="section-heading" onclick="toggleSection(this)" style="cursor:pointer">
            <h2>Custom Fields <span class="collapse-arrow" style="font-size:12px;margin-left:6px;color:var(--muted)">&#9654;</span></h2>
        </div>
        <div class="collapse-content" style="display:none">{custom_fields}</div>
    </section>
    {bot_card}
    <section class="panel">
        <div class="section-heading" onclick="toggleSection(this)" style="cursor:pointer">
            <h2>Server Settings <span class="collapse-arrow" style="font-size:12px;margin-left:6px;color:var(--muted)">&#9654;</span></h2>
        </div>
        <div class="collapse-content" style="display:none">{server_settings}</div>
    </section>"""

    return base_html("Admin", notice + cards, user, 0)
