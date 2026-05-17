import html as html_mod
from pathlib import Path
from urllib.parse import urlencode

BASE_DIR = Path(__file__).resolve().parent


def esc(val):
    if val is None:
        return ""
    return html_mod.escape(str(val), quote=True)


def base_html(title, content, user=None, notif_count=0):
    nav = ""
    if user:
        badge = f'<span class="notif-badge">{notif_count}</span>' if notif_count > 0 else ""
        nav = f"""
        <a class="button ghost" href="/dashboard">Dashboard</a>
        <a class="button ghost" href="/inventory">Inventory</a>
        <a class="button ghost" href="/orders">Orders</a>
        <a class="button ghost" href="/notifications">Notifs{badge}</a>
        <a class="button ghost" href="/auth/logout">Logout</a>
        """
    else:
        nav = '<a class="button" href="/auth/login">Login with Discord</a>'
    return f"""<!doctype html>
<html lang="en" class="dark">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} — SC Community</title>
<link rel="stylesheet" href="/static/styles.css"></head>
<body>
<header class="topbar">
<div><h1>SC Community SHOWER</h1><p class="network-info">SHOpfront · Workorder · Exchange Register</p></div>
<nav class="nav-links">{nav}</nav>
</header>
<main>{content}</main>
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
            html += f'<div class="messages"><div class="message {cls}">{esc(msg)}</div></div>'
            break
    return html


def api_keys_section(user, db):
    keys = db.get_api_keys(user["discord_id"])
    rows = ""
    for k in keys:
        short = k["key"][:16] + "..."
        rows += f"<tr><td><code>{esc(short)}</code></td><td>{esc(k['label'])}</td><td>{esc(k['last_used'] or 'never')}</td><td>{esc(k['created_at'])}</td></tr>"
    if not rows:
        rows = '<tr><td colspan="4" class="empty">No API keys yet.</td></tr>'

    return f"""<script>
function copyKey(id) {{
    var val = document.getElementById(id).textContent;
    navigator.clipboard.writeText(val).then(function() {{
        var btn = document.querySelector('[data-for="' + id + '"]');
        btn.textContent = 'Copied!';
        setTimeout(function() {{ btn.textContent = 'Copy'; }}, 2000);
    }});
}}
function createKey() {{
    var label = prompt('Label for this API key:', 'PITS sync key');
    if (!label) return;
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/keys/create');
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.onload = function() {{
        var resp = JSON.parse(xhr.responseText);
        if (resp.key) {{
            var msg = document.getElementById('new-key-msg');
            msg.innerHTML = '<div class="message success">New API key: <code style="word-break:break-all">' + resp.key + '</code><br><small style="color:var(--muted)">Copy this now — it won\\'t be shown again.</small></div>';
        }}
    }};
    xhr.send(JSON.stringify({{label: label}}));
}}
function revokeKey() {{
    var key = prompt('Paste the full API key to revoke:');
    if (!key) return;
    if (!confirm('Revoke this API key? This cannot be undone.')) return;
    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/keys/revoke');
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.onload = function() {{ location.reload(); }};
    xhr.send(JSON.stringify({{key: key}}));
}}
</script>
<div id="new-key-msg"></div>
<div style="margin-bottom:12px">
    <button class="button" onclick="createKey()">Generate New Key</button>
    <button class="button ghost" onclick="revokeKey()" style="color:var(--error)">Revoke Key</button>
</div>
<div class="table-wrap"><table><thead><tr><th>Key</th><th>Label</th><th>Last Used</th><th>Created</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="muted" style="margin-top:8px;font-size:13px">Use these keys in your PITS extension settings as <code>Authorization: Bearer &lt;key&gt;</code> to sync without Discord re-authentication.</p>"""


def dashboard(user, db):
    if not user:
        return base_html("Welcome", f"""<section class="panel" style="text-align:center;padding:60px">
        <h2 style="font-size:28px;margin-bottom:16px">SC Community SHOWER</h2>
        <p style="color:var(--muted);margin-bottom:24px">Shopfront, Workorder and Exchange Register</p>
        <a class="button" href="/auth/login" style="font-size:18px;padding:12px 32px">Login with Discord</a>
        </section>""")
    inv_count = len(db.get_user_inventory(user["discord_id"]))
    notifs = db.get_notifications(user["discord_id"], limit=5)
    unread = sum(1 for n in notifs if not n["read"])

    metrics = f"""<div class="summary-grid">
    <div class="metric"><span>Your Items</span><strong>{inv_count}</strong></div>
    <div class="metric"><span>Open Orders</span><strong>{len([o for o in db.get_open_orders()])}</strong></div>
    <div class="metric"><span>Notifications</span><strong>{unread}</strong></div>
    </div>"""

    notif_html = ""
    for n in notifs[:3]:
        cls = "" if n["read"] else "unread"
        notif_html += f"""<div class="notif {cls}"><div class="notif-body">
        <div class="notif-msg"><strong>{esc(n["title"])}</strong> {esc(n["body"])}</div>
        <div class="notif-time">{esc(n["created_at"] or "")}</div>
        </div></div>"""
    if not notif_html:
        notif_html = '<p class="muted">No recent notifications.</p>'

    content = f"""{metrics}{page_panel("API Keys", api_keys_section(user, db))}{page_panel("Recent Notifications", f'<div class="notif-list">{notif_html}</div>', back_url="/notifications")}"""
    return base_html("Dashboard", content, user, unread)


def inventory_browse(user, db, qs):
    search = qs.get("q", "").strip()
    items = db.all_inventory(limit=200) if not user else db.all_inventory(limit=200)
    rows = ""
    for item in items:
        rows += f"<tr><td>{esc(item['item_name'])}</td><td>{item['quality']}</td><td>{item['quantity_scu']}</td><td>{esc(item['station'] or '')}</td><td>{esc(item['discord_tag'] or 'Unknown')}</td><td>{esc(item['synced_at'] or '')}</td></tr>"
    if not rows:
        rows = '<tr><td colspan="6" class="empty">No inventory synced yet.</td></tr>'
    body = f"""<form method="get" class="search-form" style="margin-bottom:12px">
    <div class="search-wrap"><input type="search" name="q" placeholder="Search items..." value="{esc(search)}"></div>
    <button type="submit">Search</button>
    </form>
    <div class="table-wrap"><table><thead><tr><th>Item</th><th>Quality</th><th>QTY (SCU)</th><th>Station</th><th>Owner</th><th>Synced</th></tr></thead><tbody>{rows}</tbody></table></div>"""
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
            <button type="submit">I Have This</button></form>"""
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
    <div style="margin-bottom:16px"><a class="button" href="/orders/create">Create Order Request</a></div>
    <h3 style="margin-bottom:8px">Open Requests</h3>
    <div class="table-wrap"><table><thead><tr><th>Item</th><th>Min Qual</th><th>QTY</th><th>Action</th></tr></thead><tbody>{rows}</tbody></table></div>
    <h3 style="margin:24px 0 8px">My Requests</h3>
    <div class="table-wrap"><table><thead><tr><th>Item</th><th>Min Qual</th><th>QTY</th><th>Status</th></tr></thead><tbody>{my_rows}</tbody></table></div>"""
    notif_count = len(db.get_notifications(user["discord_id"]))
    return base_html("Orders", page_panel("Order Requests", body), user, notif_count)


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
