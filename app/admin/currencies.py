"""Currencies: staff type in each currency with its rate; the Mini App shows prices in the one a customer picks."""
import re
from decimal import Decimal, InvalidOperation

from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select, update

from app.admin.common import ADMIN, DB, back, f_bool, f_int, f_str, render, snapshot, staff_dep, toast
from app.admin.router import router
from app.i18n import t
from app.models import Currency, Product, User
from app.models.base import utcnow
from app.services import audit, currencies

FIELDS = ["code", "name", "symbol", "symbol_first", "rate", "decimals", "is_active", "is_default"]
MAX_RATE = Decimal("1000000000000")
# quick picks in the add dialog: code, symbol, symbol first, decimals (names come from the locale)
PRESETS = [("UZS", "so'm", False, 0), ("RUB", "₽", False, 0), ("CNY", "¥", True, 2), ("KZT", "₸", False, 0), ("EUR", "€", True, 2), ("KGS", "сом", False, 0)]


def parse_rate(raw: str | None) -> Decimal | None:
    """ "12 800,5" → 12800.5; None unless 0 < rate < 10^12."""
    v = re.sub(r"[\s  ']", "", raw or "").replace(",", ".")
    try:
        d = Decimal(v).quantize(Decimal("0.000001"))
    except InvalidOperation:
        return None
    return d if Decimal(0) < d < MAX_RATE else None


def _set_rate(c: Currency, rate: Decimal) -> None:
    if c.rate is None or Decimal(c.rate) != rate:
        c.rate, c.rate_at = rate, utcnow()


def _apply(c: Currency, form) -> str | None:
    """Copy the dialog form onto the currency; returns an error key or None."""
    name = f_str(form, "name", maxlen=40)
    if not name:
        return "name_required"
    c.name = name
    c.symbol = f_str(form, "symbol", maxlen=8) or c.code
    c.symbol_first = f_bool(form, "symbol_first")
    c.decimals = max(0, min(4, f_int(form, "decimals", 2) or 0))
    if c.is_base:
        c.rate, c.is_active = Decimal(1), True
        return None
    rate = parse_rate(form.get("rate"))
    if rate is None:
        return "rate_invalid"
    _set_rate(c, rate)
    return None


async def _set_default(db, c: Currency, on: bool) -> None:
    """Make c the currency the Mini App shows first (only one is), or stop it being that."""
    if on:
        await db.execute(update(Currency).where(Currency.id != c.id).values(is_default=False))
        c.is_default, c.is_active = True, True
    else:
        c.is_default = False


async def _usage(db) -> dict[str, int]:
    rows = await db.execute(select(Product.currency, func.count()).group_by(Product.currency))
    return {code: n for code, n in rows.all()}


async def _row(request: Request, db, staff: User, c: Currency, msg: str, kind: str = "ok"):
    """One list row re-rendered after an inline change (rate, visibility)."""
    return render(request, staff, "admin/currencies/_row.html", {"c": c, "usage": await _usage(db)}, headers=toast(msg, kind))


@router.get("/currencies")
async def currencies_page(request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    rows = (await db.execute(select(Currency).order_by(*currencies.ORDER))).scalars().all()
    base = next((c for c in rows if c.is_base), None)
    main = next((c for c in rows if c.is_default and c.is_active), None) or base
    have = {c.code for c in rows}
    presets = [{"code": code, "name": t(staff.lang, f"admin.cur.preset.{code}"), "symbol": sym, "first": first, "dec": dec, "exists": code in have} for code, sym, first, dec in PRESETS]
    p = (await db.execute(select(Product).where(Product.is_active.is_(True), Product.price.is_not(None)).order_by(Product.sort, Product.id).limit(1))).scalars().first()
    sample = {"title": f"{p.brand} {p.model}", "price": str(p.price), "currency": p.currency} if p else None
    return render(request, staff, "admin/currencies/list.html", {
        "page_title": t(staff.lang, "admin.cur.title"), "rows": rows, "base": base, "main": main, "usage": await _usage(db), "presets": presets, "sample": sample,
    })


@router.post("/currencies")
async def currency_add(request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    form = await request.form()
    code = f_str(form, "code", maxlen=3).upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        return back(request, "/admin/currencies", t(staff.lang, "admin.cur.err.code_invalid"), "bad")
    if await db.scalar(select(Currency.id).where(Currency.code == code)):
        return back(request, "/admin/currencies", t(staff.lang, "admin.cur.err.code_taken", code=code), "bad")
    c = Currency(code=code, is_base=False, is_active=True, sort=100)
    err = _apply(c, form)
    if err:
        return back(request, "/admin/currencies", t(staff.lang, f"admin.cur.err.{err}"), "bad")
    db.add(c)
    await db.flush()
    if f_bool(form, "is_default"):
        await _set_default(db, c, True)
    await audit.log(db, staff.id, "currency.create", "currency", c.id, None, snapshot(c, FIELDS))
    await db.commit()
    await currencies.load(db)
    return back(request, "/admin/currencies", t(staff.lang, "admin.cur.added", code=code))


@router.post("/currencies/{cid}")
async def currency_save(cid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    c = await db.get(Currency, cid)
    if c is None:
        return back(request, "/admin/currencies", t(staff.lang, "admin.flash.error"), "bad")
    form = await request.form()
    before = snapshot(c, FIELDS)
    err = _apply(c, form)
    if err:
        await db.rollback()
        return back(request, "/admin/currencies", t(staff.lang, f"admin.cur.err.{err}"), "bad")
    if f_bool(form, "is_default") != c.is_default:
        await _set_default(db, c, f_bool(form, "is_default"))
    await audit.log(db, staff.id, "currency.update", "currency", c.id, before, snapshot(c, FIELDS))
    await db.commit()
    await currencies.load(db)
    return back(request, "/admin/currencies", t(staff.lang, "admin.flash.saved"))


@router.post("/currencies/{cid}/rate")
async def currency_rate(cid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    """Inline rate update from the list (HTMX): returns the row."""
    c = await db.get(Currency, cid)
    if c is None:
        raise HTTPException(404)
    rate = parse_rate((await request.form()).get("rate"))
    if c.is_base or rate is None:
        return await _row(request, db, staff, c, t(staff.lang, "admin.cur.err.rate_invalid"), "bad")
    before = snapshot(c, FIELDS)
    _set_rate(c, rate)
    await audit.log(db, staff.id, "currency.rate", "currency", c.id, before, snapshot(c, FIELDS))
    await db.commit()
    await currencies.load(db)
    return await _row(request, db, staff, c, t(staff.lang, "admin.cur.rate_saved", code=c.code))


@router.post("/currencies/{cid}/toggle")
async def currency_toggle(cid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    """Show / hide the currency in the Mini App (HTMX): returns the row."""
    c = await db.get(Currency, cid)
    if c is None or c.is_base:
        raise HTTPException(404)
    if c.is_default and c.is_active:
        return await _row(request, db, staff, c, t(staff.lang, "admin.cur.err.default_hidden"), "bad")
    c.is_active = not c.is_active
    await audit.log(db, staff.id, "currency.toggle", "currency", c.id, {"is_active": not c.is_active}, {"is_active": c.is_active})
    await db.commit()
    await currencies.load(db)
    return await _row(request, db, staff, c, t(staff.lang, "admin.cur.shown_toast" if c.is_active else "admin.cur.hidden_toast", code=c.code))


@router.post("/currencies/{cid}/default")
async def currency_default(cid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    """Show prices in this currency first in the Mini App (customers can still pick another)."""
    c = await db.get(Currency, cid)
    if c is None:
        return back(request, "/admin/currencies", t(staff.lang, "admin.flash.error"), "bad")
    before = snapshot(c, FIELDS)
    await _set_default(db, c, True)
    await audit.log(db, staff.id, "currency.default", "currency", c.id, before, snapshot(c, FIELDS))
    await db.commit()
    await currencies.load(db)
    return back(request, "/admin/currencies", t(staff.lang, "admin.cur.default_toast", code=c.code))


@router.post("/currencies/{cid}/delete")
async def currency_delete(cid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    c = await db.get(Currency, cid)
    if c is None or c.is_base:
        return back(request, "/admin/currencies", t(staff.lang, "admin.cur.err.base_locked"), "bad")
    used = (await _usage(db)).get(c.code, 0)
    if used:  # products are priced in it: hide it instead
        return back(request, "/admin/currencies", t(staff.lang, "admin.cur.err.in_use", n=used), "warn")
    await audit.log(db, staff.id, "currency.delete", "currency", c.id, snapshot(c, FIELDS), None)
    await db.delete(c)
    await db.commit()
    await currencies.load(db)
    return back(request, "/admin/currencies", t(staff.lang, "admin.cur.deleted", code=c.code))
