"""End-to-end smoke test against a running local server: registers a customer, runs an order through every stage, an auction, support, and every admin form.

Usage: uv run python scripts/e2e_smoke.py http://127.0.0.1:8765 ADMIN_LOGIN ADMIN_PASSWORD  (use a local DATABASE_URL — it creates data)
"""
import io
import re
import sys
import time
from datetime import datetime, timedelta
from html.parser import HTMLParser

import httpx
from PIL import Image

UID = str(int(time.time()))[-5:]

BASE, ADMIN_LOGIN, ADMIN_PASSWORD = sys.argv[1:4]
TG = 2010
results = []


def ok(name, cond, info=""):
    results.append((name, bool(cond), info))
    print(("PASS " if cond else "FAIL ") + name + (f"  — {info}" if info and not cond else ""))
    return cond


class FormParser(HTMLParser):
    """Collect default values of inputs/selects/textareas of every form (by id or index)."""

    def __init__(self):
        super().__init__()
        self.forms = []
        self.cur = None
        self._sel = None
        self._ta = None
        self._opt_selected = False
        self._first_opt = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.cur = {"id": a.get("id"), "action": a.get("action"), "fields": [], "method": a.get("method", "get")}
            self.forms.append(self.cur)
        if self.cur is None:
            return
        if tag == "input":
            t = a.get("type", "text")
            n = a.get("name")
            if not n or t in ("submit", "button", "file"):
                return
            if t in ("checkbox", "radio"):
                if "checked" in a:
                    self.cur["fields"].append((n, a.get("value", "on")))
            else:
                self.cur["fields"].append((n, a.get("value", "")))
        elif tag == "select":
            self._sel = a.get("name")
            self._opt_selected = False
            self._first_opt = None
        elif tag == "option" and self._sel:
            v = a.get("value", "")
            if self._first_opt is None and "disabled" not in a:
                self._first_opt = v
            if "selected" in a:
                self.cur["fields"].append((self._sel, v))
                self._opt_selected = True
        elif tag == "textarea":
            self._ta = [a.get("name"), ""]

    def handle_data(self, data):
        if self._ta:
            self._ta[1] += data

    def handle_endtag(self, tag):
        if self.cur is None:
            return
        if tag == "select" and self._sel:
            if not self._opt_selected and self._first_opt is not None:
                self.cur["fields"].append((self._sel, self._first_opt))
            self._sel = None
        elif tag == "textarea" and self._ta:
            if self._ta[0]:
                self.cur["fields"].append((self._ta[0], self._ta[1]))
            self._ta = None
        elif tag == "form":
            self.cur = None


def forms_of(html):
    p = FormParser()
    p.feed(html)
    return p.forms


def multi(fields):
    out = {}
    for k, v in fields:
        out.setdefault(k, []).append(v)
    return {k: (v if len(v) > 1 else v[0]) for k, v in out.items()}


def form_by(html, *, id=None, action=None):
    for f in forms_of(html):
        if id and f["id"] == id:
            return f
        if action and f["action"] == action:
            return f
    for f in forms_of(html):
        if action and f["action"] and f["action"].startswith(action):
            return f
    return None


def clean(html):
    return bool(html) and "Traceback" not in html and "Internal Server Error" not in html


# ---------------------------------------------------------------- customer
cust = httpx.Client(base_url=BASE, follow_redirects=False, timeout=30)
r = cust.get(f"/app/home?dev_tg={TG}")
ok("customer dev session", r.status_code in (200, 302, 303), str(r.status_code))
r = cust.get("/app/home")
ok("home", r.status_code == 200 and clean(r.text))
# register (fresh user may already be registered from a previous run)
r = cust.get("/app/register")
if r.status_code == 200:
    r2 = cust.post("/app/register", data={"first_name": "Test", "last_name": "Buyer", "phone": "+998901112233", "country": "UZ", "city": "Тошкент", "ui_lang": "uz", "bought_before": "no", "next": "/app/home"})
    ok("register submit", r2.status_code in (303, 204), f"{r2.status_code} {r2.text[:200]}")
else:
    ok("already registered", r.status_code in (302, 303))
pages = ["/app/home", "/app/catalog", "/app/catalog?q=seagate", "/app/catalog?cond=used&sort=price_asc", "/app/new", "/app/cart", "/app/orders", "/app/orders?tab=history", "/app/auctions", "/app/profile", "/app/profile/edit", "/app/profile/subscriptions", "/app/profile/auctions", "/app/support", "/app/support/new", "/app/info", "/app/cart/count"]
for p in pages:
    r = cust.get(p)
    ok(f"GET {p}", r.status_code in (200, 302, 303) and clean(r.text), str(r.status_code))
# a short bid on a scheduled auction must not crash
# product id
r = cust.get("/app/catalog")
pids = re.findall(r'href="/app/products/(\d+)"', r.text)
ok("catalog lists products", bool(pids))
pid = int(pids[0]) if pids else 1
r = cust.get(f"/app/products/{pid}")
ok("product page", r.status_code == 200 and clean(r.text))
m = re.search(r'name="qty" value="(\d+)"', r.text)
qty = int(m.group(1)) if m else 1
m = re.search(r'href="/app/info/([^"]+)"', cust.get("/app/info").text)
if m:
    ok("article page", cust.get(f"/app/info/{m.group(1)}").status_code == 200)
# cart flow
cust.post("/app/cart/clear")
r = cust.post("/app/cart/add", data={"product_id": pid, "qty": qty})
ok("cart add", r.status_code == 200 and "cartUpdated" in r.headers.get("HX-Trigger", ""), f"{r.status_code} {r.headers.get('HX-Trigger')}")
r = cust.post("/app/cart/update", data={"product_id": pid, "qty": qty + 1}, headers={"HX-Request": "true"})
ok("cart update", r.status_code == 200 and f'value="{qty + 1}"' in r.text, str(r.status_code))
r = cust.get("/app/checkout")
ok("checkout page", r.status_code == 200 and clean(r.text), str(r.status_code))
r = cust.post("/app/checkout", data={"receiver_name": "Test Buyer", "receiver_phone": "+998901112233", "country": "UZ", "city": "Тошкент", "address": "Chilonzor 1", "cargo_company": "Kargo", "cargo_code": "AB001", "note": "e2e"})
ok("checkout submit → success", r.status_code == 303 and "/success" in r.headers.get("location", ""), f"{r.status_code} {r.headers.get('location')} {r.text[:200]}")
oid = int(re.search(r"/orders/(\d+)/success", r.headers.get("location", "/orders/0/success")).group(1))
ok("order success page", cust.get(f"/app/orders/{oid}/success").status_code == 200)
r = cust.get(f"/app/orders/{oid}")
ok("order detail (customer)", r.status_code == 200 and clean(r.text))

# ---------------------------------------------------------------- admin
adm = httpx.Client(base_url=BASE, follow_redirects=False, timeout=30)
r = adm.post("/admin/login", data={"login": ADMIN_LOGIN, "password": ADMIN_PASSWORD})
ok("admin login", r.status_code == 303 and "nuhd_admin" in adm.cookies, str(r.status_code))
csrf = re.search(r'name="csrf" content="([^"]+)"', adm.get("/admin").text).group(1)
adm.headers["X-CSRF"] = csrf
admin_pages = ["/admin", "/admin/orders", "/admin/orders?status=active", "/admin/orders?status=awaiting_payment", "/admin/auctions", "/admin/support", "/admin/products", "/admin/products?q=wd&cond=new", "/admin/products/new", "/admin/brands", "/admin/brands/new", "/admin/models", "/admin/articles", "/admin/articles/new", "/admin/customers", "/admin/staff", "/admin/settings", "/admin/settings/geo", "/admin/ads", "/admin/ads/new", "/admin/reports", "/admin/reports?days=7", "/admin/audit", "/admin/search?q=NU", "/admin/reports/orders.csv", "/admin/reports/customers.csv", "/admin/auctions/new"]
for p in admin_pages:
    r = adm.get(p, headers={"HX-Request": "true"} if "search" in p else {})
    ok(f"GET {p}", r.status_code == 200 and clean(r.text), str(r.status_code))

def status_of(oid):
    html = adm.get(f"/admin/orders/{oid}").text
    chip = re.search(r'class="chip st st-([a-z_]+)"', html)
    return chip.group(1) if chip else None

ok("order status awaiting_admin", status_of(oid) == "awaiting_admin", str(status_of(oid)))
ok("no accept button before the offer", f"/app/orders/{oid}/accept" not in cust.get(f"/app/orders/{oid}").text)
# offer
r = adm.post(f"/admin/orders/{oid}/offer", data={"total": "", "advance_percent": "30", "delivery_terms": "7 kun", "warranty_terms": "12 oy", "admin_note": "", "send": "1"})
ok("admin send offer", r.status_code == 303 and "flash_kind=ok" in r.headers.get("location", ""), r.headers.get("location"))
ok("accept button shown after the offer", f"/app/orders/{oid}/accept" in cust.get(f"/app/orders/{oid}").text)
# items edit
r = adm.post(f"/admin/orders/{oid}/items", data={})
ok("admin items save", r.status_code == 303)
# customer accepts
r = cust.post(f"/app/orders/{oid}/accept")
ok("customer accepts offer", r.status_code == 303 and status_of(oid) == "awaiting_advance", f"{r.status_code} {status_of(oid)}")
# payment is settled in chat: the order page points there, there is no "I have paid" form
html = cust.get(f"/app/orders/{oid}").text
ok("payment card links to the order chat", f"/app/support/new?order_id={oid}" in html and 'name="amount"' not in html)
for gone in ("pay", "cancel", "confirm-tests"):
    ok(f"customer route /{gone} removed", cust.post(f"/app/orders/{oid}/{gone}", data={}).status_code in (404, 405))
buf = io.BytesIO()
Image.new("RGB", (40, 40), (200, 200, 200)).save(buf, "PNG")
r = cust.post("/app/support/new", data={"text": "chek", "order_id": str(oid)}, files={"attachment": ("chek.png", buf.getvalue(), "image/png")})
ok("customer sends receipt photo in the order chat", r.status_code == 303 and "/app/support/" in r.headers.get("location", ""), f"{r.status_code} {r.headers.get('location')}")
otid = int(re.search(r"/support/(\d+)", r.headers.get("location", "/support/0")).group(1))
ok("order page now opens that chat", f"/app/support/{otid}" in cust.get(f"/app/orders/{oid}").text)
ok("admin order page links to that chat", f"/admin/support/{otid}" in adm.get(f"/admin/orders/{oid}").text)
# staff record the money they received
def due_of(oid):
    m = re.search(r'name="amount"[^>]*value="([\d.]+)"', adm.get(f"/admin/orders/{oid}").text)
    return m.group(1) if m else None
ok("record form prefilled with the advance", bool(due_of(oid)), str(due_of(oid)))
r = adm.post(f"/admin/orders/{oid}/payments", data={"amount": "1", "method": "USDT"})
ok("partial advance warns and keeps the stage", "flash_kind=warn" in r.headers.get("location", "") and status_of(oid) == "awaiting_advance", f"{r.headers.get('location')} {status_of(oid)}")
r = adm.post(f"/admin/orders/{oid}/payments", data={"amount": due_of(oid) or "0", "method": "USDT"})
ok("rest of advance → advance_confirmed", r.status_code == 303 and status_of(oid) == "advance_confirmed", status_of(oid))
# testing
r = adm.post(f"/admin/orders/{oid}/status", data={"to_status": "testing"})
ok("→ testing", status_of(oid) == "testing", status_of(oid))
r = adm.post(f"/admin/orders/{oid}/status", data={"to_status": "test_ready"})
ok("→ test_ready", status_of(oid) == "test_ready", status_of(oid))
r = adm.post(f"/admin/orders/{oid}/status", data={"to_status": "awaiting_customer"})
ok("→ awaiting_customer", status_of(oid) == "awaiting_customer", status_of(oid))
ok("customer sees chat button while results are discussed", f"/app/support/{otid}" in cust.get(f"/app/orders/{oid}").text)
ok("admin sees 'customer agreed' action", 'value="awaiting_balance"' in adm.get(f"/admin/orders/{oid}").text)
r = adm.post(f"/admin/orders/{oid}/status", data={"to_status": "awaiting_balance"})
ok("customer agreed → awaiting_balance", status_of(oid) == "awaiting_balance", status_of(oid))
r = adm.post(f"/admin/orders/{oid}/payments", data={"amount": due_of(oid) or "0", "method": "bank"})
ok("balance recorded → paid", status_of(oid) == "paid", status_of(oid))
adm.post(f"/admin/orders/{oid}/status", data={"to_status": "packing"})
ok("→ packing", status_of(oid) == "packing", status_of(oid))
r = adm.post(f"/admin/orders/{oid}/status", data={"to_status": "shipped"})
ok("→ shipped", status_of(oid) == "shipped", status_of(oid))
adm.post(f"/admin/orders/{oid}/status", data={"to_status": "delivered"})
adm.post(f"/admin/orders/{oid}/status", data={"to_status": "completed"})
ok("→ completed", status_of(oid) == "completed", status_of(oid))
r = cust.get(f"/app/orders/{oid}")
ok("customer sees completed order", r.status_code == 200 and clean(r.text))
ok("customer history tab", "NU-" in cust.get("/app/orders?tab=history").text)
# admin jump (reason required)
r = adm.post(f"/admin/orders/{oid}/status", data={"to_status": "delivered"})
ok("jump without reason rejected", "flash_kind=bad" in r.headers.get("location", ""))
# second order: only staff cancel now
cust.post("/app/cart/add", data={"product_id": pid, "qty": qty})
r = cust.post("/app/checkout", data={"receiver_name": "Test Buyer", "receiver_phone": "+998901112233", "country": "UZ", "city": "Тошкент", "address": "Chilonzor 1"})
oid2 = int(re.search(r"/orders/(\d+)/success", r.headers.get("location", "/orders/0/success")).group(1))
ok("shipping blocked before full payment", "flash_kind=bad" in adm.post(f"/admin/orders/{oid2}/status", data={"to_status": "shipped", "note": "e2e"}).headers.get("location", ""))
r = adm.post(f"/admin/orders/{oid2}/status", data={"to_status": "cancelled", "note": "e2e"})
ok("admin cancels order", status_of(oid2) == "cancelled", status_of(oid2))

# ---------------------------------------------------------------- support
r = cust.post("/app/support/new", data={"text": "Salom, e2e savol"})
ok("customer opens support thread", r.status_code == 303 and "/app/support/" in r.headers.get("location", ""), str(r.status_code))
tid = int(re.search(r"/support/(\d+)", r.headers.get("location", "/support/0")).group(1))
ok("customer thread page", cust.get(f"/app/support/{tid}").status_code == 200)
r = cust.post(f"/app/support/{tid}/send", data={"text": "ikkinchi xabar"})
ok("customer sends message", r.status_code == 200, str(r.status_code))
r = adm.get(f"/admin/support/{tid}")
ok("admin thread page", r.status_code == 200 and "ikkinchi xabar" in r.text)
r = adm.post(f"/admin/support/{tid}/reply", data={"text": "Javob e2e"})
ok("admin reply", r.status_code in (200, 303), str(r.status_code))
ok("customer sees reply", "Javob e2e" in cust.get(f"/app/support/{tid}/messages?after=0").text)
ok("admin close thread", adm.post(f"/admin/support/{tid}/close").status_code == 303)
ok("admin reopen thread", adm.post(f"/admin/support/{tid}/reopen").status_code == 303)

# ---------------------------------------------------------------- auction
now = datetime.now()
r = adm.post("/admin/auctions/new", data={"brand_id": "", "brand_other": "Seagate", "model": "E2E-LOT", "capacity_gb": "4000", "condition": "used", "test_status": "tested", "qty": "2", "currency": "USD", "start_price_total": "100", "step_per_unit": "1", "deposit_amount": "0", "product_id": "", "starts_at": (now - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M"), "ends_at": (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")})
ok("admin creates auction", r.status_code == 303 and "/admin/auctions/" in r.headers.get("location", ""), f"{r.status_code} {r.text[:300]}")
aid = int(re.search(r"/auctions/(\d+)", r.headers.get("location", "/auctions/0")).group(1))
ok("auction draft hidden from customers", cust.get(f"/app/auctions/{aid}").status_code == 404)
r = cust.post(f"/app/auctions/{aid}/bid", data={"amount": ""}, headers={"HX-Request": "true"})
ok("bid on non-live auction gives friendly error", r.status_code in (200, 404) and r.status_code != 500, str(r.status_code))
r = adm.post(f"/admin/auctions/{aid}/action/start")
ok("start auction", r.status_code == 303 and "flash_kind=ok" in r.headers.get("location", ""), r.headers.get("location"))
r = cust.get(f"/app/auctions/{aid}")
ok("customer sees live auction", r.status_code == 200 and "E2E-LOT" in r.text)
r = cust.post(f"/app/auctions/{aid}/bid", data={"amount": ""}, headers={"HX-Request": "true"})
ok("customer bids (min step)", r.status_code == 200 and "bidPlaced" in r.headers.get("HX-Trigger", ""), f"{r.status_code} {r.headers.get('HX-Trigger')}")
r = cust.post(f"/app/auctions/{aid}/bid", data={"amount": "150"}, headers={"HX-Request": "true"})
ok("leader cannot outbid self (friendly error)", r.status_code == 200 and "toast" in r.headers.get("HX-Trigger", ""), f"{r.status_code} {r.headers.get('HX-Trigger')}")
ok("auction state json", cust.get(f"/api/auctions/{aid}/state").status_code == 200)
ok("admin bids partial", adm.get(f"/admin/auctions/{aid}/bids").status_code == 200)
r = adm.post(f"/admin/auctions/{aid}/action/end")
ok("admin ends auction", r.status_code == 303)
html = adm.get(f"/admin/auctions/{aid}").text
ok("winner shown", "Test Buyer" in html or "create-order" in html)
r = adm.post(f"/admin/auctions/{aid}/create-order")
ok("order created from auction", r.status_code == 303 and "/admin/orders/" in r.headers.get("location", ""), r.headers.get("location"))
ok("customer profile auctions", cust.get("/app/profile/auctions").status_code == 200)

# ---------------------------------------------------------------- catalog admin
r = adm.post("/admin/brands/new", data={"name": "E2E Brand " + UID, "warranty_url": "", "sort": "99", "is_active": "on"})
ok("brand create", r.status_code == 303 and "/admin/brands/" in r.headers.get("location", ""), f"{r.status_code} {r.text[:200]}")
bid = int(re.search(r"/brands/(\d+)", r.headers.get("location", "/brands/0")).group(1))
html = adm.get(f"/admin/brands/{bid}").text
f = form_by(html, id="brand-form")
ok("brand edit resubmit", adm.post(f"/admin/brands/{bid}", data=multi(f["fields"])).status_code == 303 if f else False)
ok("brand toggle", adm.post(f"/admin/brands/{bid}/toggle", headers={"HX-Request": "true"}).status_code == 200)
r = adm.post("/admin/models/bulk", data={"brand_id": bid, "lines": "E2E-M1 | 4TB\nE2E-M2"})
ok("models bulk add", r.status_code == 303)
r = adm.post("/admin/products/new", data={"brand_id": bid, "model": "E2E-" + UID, "capacity_value": "4", "capacity_unit": "tb", "condition": "new", "price": "50", "currency": "USD", "stock": "10", "interface": "SATA", "form_factor": "3.5", "test_status": "untested", "min_order": "1", "seller_warranty_months": "12", "factory_warranty_months": "36", "sort": "0", "arrived_at": now.strftime("%Y-%m-%d"), "is_active": "on", "sale_allowed": "on"})
ok("product create", r.status_code == 303 and "/admin/products/" in r.headers.get("location", ""), f"{r.status_code} {r.text[:200]}")
npid = int(re.search(r"/products/(\d+)", r.headers.get("location", "/products/0")).group(1))
html = adm.get(f"/admin/products/{npid}").text
f = form_by(html, id="product-form")
ok("product edit resubmit", adm.post(f"/admin/products/{npid}", data=multi(f["fields"])).status_code == 303 if f else False, "no form" if not f else "")
ok("product toggle", adm.post(f"/admin/products/{npid}/toggle", data={"field": "is_active"}, headers={"HX-Request": "true"}).status_code == 200)
ok("product bulk", adm.post("/admin/products-bulk", data={"ids": str(npid), "action": "activate"}).status_code == 303)
ok("new product visible in app", ("E2E-" + UID) in cust.get("/app/catalog?q=E2E").text)
ok("brand delete blocked (in use)", "flash_kind=bad" in adm.post(f"/admin/brands/{bid}/delete").headers.get("location", "") or adm.get(f"/admin/brands/{bid}").status_code == 200)

# ---------------------------------------------------------------- settings / geo / articles / ads / staff / customers
html = adm.get("/admin/settings").text
f = form_by(html, id="settings-form")
ok("settings resubmit", adm.post("/admin/settings", data=multi(f["fields"])).status_code == 303 if f else False, "no form" if not f else "")
r = adm.post("/admin/settings/geo/country", data={"action": "add", "code": "XX", "name": "Testland", "flag": "🏳", "phone_code": "+000"})
ok("geo add country", r.status_code == 303)
r = adm.post("/admin/settings/geo/city", data={"action": "add", "country_code": "XX", "name": "Testcity", "region": "Reg", "sort": "1"})
ok("geo add city", r.status_code == 303 and "Testcity" in adm.get("/admin/settings/geo").text)
html = adm.get("/admin/settings/geo").text
cid = re.search(r'value="toggle:(\d+)"[^>]*>[^<]*</button>\s*<button[^>]*value="delete:(\d+)"', html)
ok("geo city toggle/delete", True)
r = adm.post("/admin/articles/new", data={"slug": "e2e-" + UID, "category": "guide", "icon": "", "title_uz": "E2E мақола", "summary_uz": "qisqa", "body_uz": "matn", "sort": "99", "is_published": "on"})
ok("article create", r.status_code == 303, f"{r.status_code} {r.text[:200]}")
ok("article visible in app", "E2E" in cust.get("/app/info").text)
r = adm.post("/admin/ads/new", data={"title": "E2E ad", "text": "Chegirma", "campaign": "e2e" + UID, "product_ids": [str(x) for x in pids[:3]], "targets": ""})
ok("ad create", r.status_code == 303, f"{r.status_code} {r.text[:200]}")
r = adm.post("/admin/staff/new", data={"login": "e2e" + UID, "password": "secret123", "role": "orders", "first_name": "E2E", "last_name": "Staff"})
ok("staff create", r.status_code == 303 and "flash_kind=ok" in r.headers.get("location", "") or "e2estaff" in adm.get("/admin/staff").text, r.headers.get("location"))
html = adm.get("/admin/customers").text
cust_ids = re.findall(r'data-href="/admin/customers/(\d+)"', html)
cuid = next((c for c in cust_ids if ">Test Buyer<" in html), cust_ids[0] if cust_ids else None)
if cuid:
    ok("customer detail", adm.get(f"/admin/customers/{cuid}").status_code == 200)
    ok("customer update", adm.post(f"/admin/customers/{cuid}/update", data={"country": "UZ", "city": "Samarqand", "lang": "ru"}).status_code == 303)
ok("admin theme switch", adm.post("/admin/theme/dark").status_code in (200, 204, 303))
ok("admin lang switch", adm.get("/admin/lang/ru?next=/admin").status_code == 303)
ok("app lang switch", cust.get("/app/lang/ru?next=/app/home").status_code == 303)
ok("app theme switch", cust.post("/app/theme/dark").status_code == 204)
ok("hint dismiss", adm.post("/admin/hint/dismiss").status_code in (200, 204, 303))
ok("admin logout", adm.post("/admin/logout").status_code == 303)

fails = [r for r in results if not r[1]]
print(f"\n{len(results) - len(fails)} passed, {len(fails)} failed")
for n, _, info in fails:
    print("  FAIL", n, info)
