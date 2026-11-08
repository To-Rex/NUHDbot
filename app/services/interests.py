"""Customer interests: what each customer looks at, searches, puts in the cart, orders and bids on — written down as
interest_events and read three ways.

* a customer's profile (brands, capacities, conditions, purposes, price range, the products they keep coming back to) —
  the customer's card in the admin panel, the assistant;
* recommendations for that customer in the Mini App (home "For you", the product page's rail, the cart);
* the demand analysis for the staff: which brands / capacities / models customers want against what is in stock, and the
  searches that found nothing — the gaps worth filling.

Events are kept for good; the profile weighs recent ones more (half-life HALF_LIFE_DAYS) without forgetting the old ones.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InterestEvent, Product, User

KINDS = ("view", "search", "filter", "cart", "order", "bid", "subscribe")
WEIGHT = {"view": 1.0, "search": 2.0, "filter": 1.5, "cart": 5.0, "order": 10.0, "bid": 5.0, "subscribe": 3.0}
HALF_LIFE_DAYS = 90  # an event's weight halves every 90 days — recent interest counts more, nothing is forgotten
DEDUPE_MINUTES = {"view": 30, "search": 10, "filter": 10}  # the same thing again within this window is not a new sign
MIN_EVENTS_FOR_RECS = 3  # below this the Mini App shows no "For you" block
PROFILE_LIMIT = 4000  # newest events read for one customer's profile


def _traits(p: Product | None) -> dict:
    if p is None:
        return {}
    return {"product_id": p.id, "brand": p.brand, "model": p.model, "capacity_gb": p.capacity_gb, "condition": p.condition.value,
            "purposes": list(p.purposes or []), "price": p.price}


def counts_as(user: User | None) -> bool:
    """Whose actions are signs of interest: signed-in customers (not the staff browsing the Mini App)."""
    return user is not None and not user.is_staff and not user.is_blocked


async def _recent_same(db: AsyncSession, user_id: int, kind: str, *, product_id: int | None = None, query: str | None = None) -> bool:
    minutes = DEDUPE_MINUTES.get(kind)
    if not minutes:
        return False
    stmt = select(InterestEvent.id).where(InterestEvent.user_id == user_id, InterestEvent.kind == kind,
                                          InterestEvent.created_at >= datetime.now(UTC) - timedelta(minutes=minutes))
    stmt = stmt.where(InterestEvent.product_id == product_id) if product_id is not None else stmt.where(InterestEvent.query == query)
    return (await db.execute(stmt.limit(1))).first() is not None


async def track(db: AsyncSession, user: User | None, kind: str, *, product: Product | None = None, query: str | None = None,
                results: int | None = None, qty: int | None = None, brand: str | None = None, capacity_gb: int | None = None,
                condition: str | None = None, model: str | None = None) -> InterestEvent | None:
    """Write one sign down (flushed; the caller commits). Returns None when it is not one (staff, a repeat within the window)."""
    if not counts_as(user) or kind not in KINDS:
        return None
    if await _recent_same(db, user.id, kind, product_id=product.id if product else None, query=query):
        return None
    data = _traits(product)
    for k, v in (("brand", brand), ("capacity_gb", capacity_gb), ("condition", condition), ("model", model)):
        if v is not None:
            data[k] = v
    ev = InterestEvent(user_id=user.id, kind=kind, query=(query or None) and query[:200], results=results, qty=qty, **data)
    db.add(ev)
    await db.flush()
    return ev


def filters_text(f) -> str:
    """The catalogue filters as one line a person can read (and the dedupe can compare): 'WD · 4TB · new · cctv'."""
    parts: list[str] = []
    parts += f.brands + [f"{c // 1000}TB" if c >= 1000 else f"{c}GB" for c in f.capacities] + f.conditions + f.purposes + f.colors + f.interfaces + f.form_factors
    if f.in_stock:
        parts.append("in_stock")
    if f.warranty:
        parts.append("warranty")
    if f.price_min is not None or f.price_max is not None:
        parts.append(f"${f.price_min or 0:g}–{f.price_max or ''}")
    return " · ".join(parts)


async def track_catalog(db: AsyncSession, user: User | None, f, total: int) -> None:
    """A search (q) and / or a filter set, with what it found; both are signs, a plain page open is not."""
    if not counts_as(user):
        return
    if f.q.strip():
        await track(db, user, "search", query=f.q.strip()[:200], results=total)
    if f.active_count:
        first_brand = f.brands[0] if len(f.brands) == 1 else None
        first_cap = f.capacities[0] if len(f.capacities) == 1 else None
        first_cond = f.conditions[0] if len(f.conditions) == 1 else None
        await track(db, user, "filter", query=filters_text(f), results=total, brand=first_brand, capacity_gb=first_cap, condition=first_cond)


# ---------- the profile ----------

def _decay(at: datetime, now: datetime) -> float:
    age = max(0.0, (now - at).total_seconds() / 86400)
    return math.pow(0.5, age / HALF_LIFE_DAYS)


def _shares(counter: Counter, top: int = 5) -> list[dict]:
    total = sum(counter.values()) or 1
    return [{"value": k, "score": round(v, 2), "share": round(v / total, 3)} for k, v in counter.most_common(top) if v > 0]


async def events_for(db: AsyncSession, user_id: int, *, limit: int = PROFILE_LIMIT) -> list[InterestEvent]:
    stmt = select(InterestEvent).where(InterestEvent.user_id == user_id).order_by(InterestEvent.id.desc()).limit(limit)
    return list((await db.execute(stmt)).scalars().all())


def build_profile(events: list[InterestEvent], now: datetime | None = None) -> dict:
    """Weighted, decayed shares per trait; the products with the most signs; the price band; what kinds of signs there were."""
    now = now or datetime.now(UTC)
    brands, caps, conds, purposes, products = Counter(), Counter(), Counter(), Counter(), Counter()
    kinds = Counter()
    prices: list[tuple[float, float]] = []
    last_at = first_at = None
    for ev in events:
        w = WEIGHT.get(ev.kind, 1.0) * _decay(ev.created_at, now)
        kinds[ev.kind] += 1
        if ev.brand:
            brands[ev.brand] += w
        if ev.capacity_gb:
            caps[ev.capacity_gb] += w
        if ev.condition:
            conds[ev.condition] += w
        for pu in ev.purposes or []:
            purposes[pu] += w
        if ev.product_id:
            products[ev.product_id] += w
        if ev.price is not None and ev.kind in ("view", "cart", "order"):
            prices.append((float(ev.price), w))
        last_at = max(last_at, ev.created_at) if last_at else ev.created_at
        first_at = min(first_at, ev.created_at) if first_at else ev.created_at
    band = None
    if prices:
        prices.sort()
        total = sum(w for _, w in prices)
        acc, lo, hi = 0.0, None, None
        for price, w in prices:
            acc += w
            if lo is None and acc >= total * 0.2:
                lo = price
            if hi is None and acc >= total * 0.8:
                hi = price
        band = {"low": lo if lo is not None else prices[0][0], "high": hi if hi is not None else prices[-1][0]}
    return {
        "events": len(events), "kinds": dict(kinds), "brands": _shares(brands), "capacities": _shares(caps), "conditions": _shares(conds, 3),
        "purposes": _shares(purposes), "products": [pid for pid, _ in products.most_common(12)], "product_scores": dict(products),
        "price_band": band, "first_at": first_at, "last_at": last_at, "enough": len(events) >= MIN_EVENTS_FOR_RECS,
    }


async def profile(db: AsyncSession, user_id: int) -> dict:
    return build_profile(await events_for(db, user_id))


# ---------- recommendations ----------

def score_product(p: Product, prof: dict) -> float:
    """How well a product fits a profile: brand, capacity, condition, purposes, the price band; the products already looked at
    are not repeated on top (they are one tap away in the history), but their siblings are."""
    if not prof or not prof.get("enough"):
        return 0.0
    share = lambda rows, value: next((r["share"] for r in rows if r["value"] == value), 0.0)  # noqa: E731
    s = 3.0 * share(prof["brands"], p.brand) + 3.0 * share(prof["capacities"], p.capacity_gb) + 1.5 * share(prof["conditions"], p.condition.value)
    s += 1.5 * max((share(prof["purposes"], pu) for pu in (p.purposes or [])), default=0.0)
    band = prof.get("price_band")
    if band and p.price is not None:
        price = float(p.price)
        if band["low"] * 0.8 <= price <= band["high"] * 1.2:
            s += 1.0
    if p.id in prof.get("product_scores", {}):
        s *= 0.6
    return s


async def recommend(db: AsyncSession, user: User | None, *, limit: int = 8, exclude: set[int] | None = None, prof: dict | None = None) -> list[Product]:
    """Products for this customer, best fit first; nothing until they have shown enough interest."""
    if not counts_as(user):
        return []
    prof = prof if prof is not None else await profile(db, user.id)
    if not prof["enough"]:
        return []
    stmt = select(Product).where(Product.is_active.is_(True), Product.sale_allowed.is_(True), Product.stock - Product.reserved > 0)
    if exclude:
        stmt = stmt.where(Product.id.notin_(list(exclude)))
    rows = list((await db.execute(stmt)).scalars().unique().all())
    scored = sorted(((score_product(p, prof), p) for p in rows), key=lambda t: (-t[0], -t[1].id))
    out, seen = [], set()
    for s, p in scored:
        key = (p.brand, p.model, p.capacity_gb, p.condition)  # one card per model / capacity / condition, not every listing of it
        if s > 0.4 and key not in seen:
            seen.add(key)
            out.append(p)
        if len(out) >= limit:
            break
    return out


def rerank(products: list[Product], prof: dict | None) -> list[Product]:
    """The same products, the better fits first (a stable order when there is no profile)."""
    if not prof or not prof.get("enough"):
        return products
    return sorted(products, key=lambda p: -score_product(p, prof))


# ---------- the staff's views ----------

async def product_interest(db: AsyncSession, product_id: int, *, days: int | None = None) -> dict:
    """Who is interested in one product: signs per kind, distinct customers, the top customers (with their signs)."""
    stmt = select(InterestEvent).where(InterestEvent.product_id == product_id)
    if days:
        stmt = stmt.where(InterestEvent.created_at >= datetime.now(UTC) - timedelta(days=days))
    rows = list((await db.execute(stmt.order_by(InterestEvent.id.desc()).limit(5000))).scalars().all())
    kinds, per_user, last_by_user = Counter(), defaultdict(Counter), {}
    for ev in rows:
        kinds[ev.kind] += 1
        per_user[ev.user_id][ev.kind] += 1
        last_by_user.setdefault(ev.user_id, ev.created_at)
    top = sorted(per_user.items(), key=lambda kv: (-sum(WEIGHT[k] * n for k, n in kv[1].items()), kv[0]))[:10]
    users = {u.id: u for u in (await db.execute(select(User).where(User.id.in_([uid for uid, _ in top])))).scalars().all()} if top else {}
    return {"events": len(rows), "kinds": dict(kinds), "customers": len(per_user),
            "top": [{"user": users.get(uid), "kinds": dict(c), "last_at": last_by_user[uid]} for uid, c in top if uid in users]}


async def demand(db: AsyncSession, *, days: int | None = 90) -> dict:
    """What customers want against what is in stock: per brand, capacity, brand+capacity, condition and purpose — weighted signs
    and distinct customers; the products with the most interest (and their stock); the searches that found nothing or little."""
    since = datetime.now(UTC) - timedelta(days=days) if days else None
    stmt = select(InterestEvent)
    if since is not None:
        stmt = stmt.where(InterestEvent.created_at >= since)
    rows = list((await db.execute(stmt.order_by(InterestEvent.id.desc()).limit(200_000))).scalars().all())
    brands, caps, combos, conds, purposes, products = Counter(), Counter(), Counter(), Counter(), Counter(), Counter()
    people = defaultdict(set)
    searches, misses, kinds = Counter(), Counter(), Counter()
    for ev in rows:
        w = WEIGHT.get(ev.kind, 1.0)
        kinds[ev.kind] += 1
        if ev.brand:
            brands[ev.brand] += w
            people[("brand", ev.brand)].add(ev.user_id)
        if ev.capacity_gb:
            caps[ev.capacity_gb] += w
            people[("cap", ev.capacity_gb)].add(ev.user_id)
        if ev.brand and ev.capacity_gb:
            combos[(ev.brand, ev.capacity_gb)] += w
            people[("combo", ev.brand, ev.capacity_gb)].add(ev.user_id)
        if ev.condition:
            conds[ev.condition] += w
        for pu in ev.purposes or []:
            purposes[pu] += w
        if ev.product_id:
            products[ev.product_id] += w
            people[("product", ev.product_id)].add(ev.user_id)
        if ev.kind == "search" and ev.query:
            q = ev.query.strip().lower()
            searches[q] += 1
            if (ev.results or 0) == 0:
                misses[q] += 1
    # the stock behind each trait, so demand can be read against supply
    stock_rows = (await db.execute(select(Product.brand, Product.capacity_gb, func.sum(Product.stock - Product.reserved), func.count())
                                   .where(Product.is_active.is_(True)).group_by(Product.brand, Product.capacity_gb))).all()
    stock_brand, stock_cap, stock_combo, models_combo = Counter(), Counter(), Counter(), Counter()
    for b, c, avail, n in stock_rows:
        avail = int(avail or 0)
        stock_brand[b] += avail
        stock_cap[c] += avail
        stock_combo[(b, c)] += avail
        models_combo[(b, c)] += int(n)
    top_products = products.most_common(20)
    prods = {p.id: p for p in (await db.execute(select(Product).where(Product.id.in_([pid for pid, _ in top_products])))).scalars().unique().all()} if top_products else {}

    def table(counter: Counter, key: str, stock: Counter | None, top: int = 12):
        total = sum(counter.values()) or 1
        out = []
        for value, score in counter.most_common(top):
            k = (key, value) if not isinstance(value, tuple) else (key, *value)
            out.append({"value": value, "score": round(score, 1), "share": round(score / total, 3), "customers": len(people.get(k, ())),
                        "stock": stock.get(value) if stock is not None else None, "models": models_combo.get(value) if key == "combo" else None})
        return out

    return {
        "days": days, "events": len(rows), "kinds": dict(kinds), "customers": len({ev.user_id for ev in rows}),
        "brands": table(brands, "brand", stock_brand), "capacities": table(caps, "cap", stock_cap), "combos": table(combos, "combo", stock_combo, 20),
        "conditions": table(conds, "cond", None, 3), "purposes": table(purposes, "purpose", None, 5),
        "products": [{"product": prods[pid], "score": round(s, 1), "customers": len(people.get(("product", pid), ()))} for pid, s in top_products if pid in prods],
        "searches": [{"query": q, "n": n, "misses": misses.get(q, 0)} for q, n in searches.most_common(25)],
        "misses": [{"query": q, "n": n} for q, n in misses.most_common(15)],
    }


async def recent(db: AsyncSession, user_id: int, limit: int = 40) -> list[InterestEvent]:
    return await events_for(db, user_id, limit=limit)


def summary_counts(events: list[InterestEvent]) -> dict:
    return dict(Counter(ev.kind for ev in events))


def to_json(prof: dict) -> dict:
    """The profile with plain values (for the assistant)."""
    out = dict(prof)
    out.pop("product_scores", None)
    for k in ("first_at", "last_at"):
        if out.get(k):
            out[k] = out[k].isoformat()
    if out.get("price_band"):
        out["price_band"] = {k: round(Decimal(str(v)), 2) for k, v in out["price_band"].items()}
    return out
