"""Currencies entered by staff (name, symbol, manual rate) and price display in the customer's currency.

Products, orders and payments keep their own currency; conversion is for display only. The table is
tiny, so it is cached in-process: reloaded after every admin change and at most once a minute otherwise
(the app runs one worker). Templates are rendered synchronously, hence the cache.
"""
import time
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Currency

COOKIE = "nuhd_currency"  # renamed once so picks made while testing the launch are forgotten
ORDER = (Currency.is_default.desc(), Currency.is_base.desc(), Currency.sort, Currency.id)  # the main one first
TTL = 60
NBSP = " "


@dataclass(frozen=True)
class Cur:
    code: str
    name: str
    symbol: str
    symbol_first: bool
    rate: Decimal
    decimals: int
    is_base: bool
    is_active: bool
    is_default: bool = False


_cache: dict[str, Cur] = {}
_loaded_at = 0.0


async def load(db: AsyncSession) -> None:
    global _cache, _loaded_at
    rows = (await db.execute(select(Currency).order_by(*ORDER))).scalars().all()
    _cache = {r.code: Cur(r.code, r.name, r.symbol, r.symbol_first, Decimal(r.rate), r.decimals, r.is_base, r.is_active, r.is_default) for r in rows}
    _loaded_at = time.monotonic()


async def ensure(db: AsyncSession) -> None:
    if not _loaded_at or time.monotonic() - _loaded_at > TTL:
        await load(db)


def get(code: str | None) -> Cur | None:
    return _cache.get((code or "").upper())


def all_() -> list[Cur]:
    return list(_cache.values())


def active() -> list[Cur]:
    return [c for c in _cache.values() if c.is_active]


def base_code() -> str:
    return next((c.code for c in _cache.values() if c.is_base), "USD")


def default_code() -> str | None:
    """The currency the Mini App shows prices in until a customer picks one (None = as priced)."""
    return next((c.code for c in _cache.values() if c.is_default and c.is_active), None)


def convert(value, from_code: str | None, to_code: str | None) -> Decimal | None:
    src, dst = get(from_code), get(to_code)
    if value is None or src is None or dst is None or src.rate <= 0:
        return None
    try:
        return Decimal(value) / src.rate * dst.rate
    except (InvalidOperation, TypeError):
        return None


def fmt(value, cur: Cur, *, exact: bool = False) -> str:
    """40 → "$40", 1280000 → "1 280 000 so'm" (whole amounts drop the decimals, like money()).
    exact: up to 4 decimals whatever the currency uses — for rates like "$1 = 96.5 ₽"."""
    dec = max(cur.decimals, 4) if exact else cur.decimals
    v = Decimal(value).quantize(Decimal(1).scaleb(-dec), ROUND_HALF_UP)
    if v == v.to_integral():
        s = f"{v:,.0f}"
    elif exact:
        s = f"{v:,.{dec}f}".rstrip("0")
    else:
        s = f"{v:,.{dec}f}"
    if cur.symbol_first:
        return f"{cur.symbol}{s}"
    return f"{s.replace(',', NBSP)}{NBSP}{cur.symbol}"


def rate_text(value) -> str:
    """A rate for an input box: 12800 → "12 800", 96.5 → "96.5"."""
    if value is None:
        return ""
    v = Decimal(value).normalize()
    whole, _, frac = f"{v:,f}".partition(".")
    return whole.replace(",", " ") + (f".{frac}" if frac.strip("0") else "")


def display(value, from_code: str | None, to_code: str | None = None, *, dash: str = "—") -> str:
    """A price in the viewer's currency when a rate exists, else as priced."""
    from app.templating import money

    if value is None:
        return dash
    dst = get(to_code)
    if dst is not None and dst.is_active:
        v = convert(value, from_code, dst.code)
        if v is not None:
            return fmt(v, dst)
    src = get(from_code)
    return fmt(value, src) if src is not None else money(value, from_code, dash=dash)


def viewer_code(request: Request, user) -> str | None:
    """The currency this Mini App visitor picked (account first, then cookie), if it is still active."""
    for code in (getattr(user, "currency", None), request.cookies.get(COOKIE)):
        c = get(code)
        if c is not None and c.is_active:
            return c.code
    return None


class Prices:
    """Template helper bound to one viewer: price(p.price, p.currency), price.original(...), price.cur."""

    def __init__(self, viewer: str | None):
        self.cur = get(viewer) or get(default_code())  # the customer's pick, else the shop's main currency
        self.base = get(base_code())
        self.shown = self.cur or self.base  # what the customer sees now (as priced = base)
        self.choices = active()
        self.base_code = base_code()

    def __call__(self, value, from_code: str | None, *, dash: str = "—") -> str:
        return display(value, from_code, self.cur.code if self.cur else None, dash=dash)

    def main_code(self, from_code: str | None) -> str:
        """The currency the big price is shown in: the visitor's pick when it converts, else as priced."""
        return self.cur.code if self.converts(from_code) else (from_code or "").upper()

    def all(self, value, from_code: str | None) -> list[dict]:
        """The price in every currency customers can pick, the main one marked — [] when there is only one."""
        if value is None or get(from_code) is None:
            return []
        main = self.main_code(from_code)
        out = []
        for c in self.choices:
            v = convert(value, from_code, c.code)
            if v is not None:
                out.append({"code": c.code, "name": c.name, "text": fmt(v, c), "on": c.code == main})
        return out if len(out) > 1 else []

    def others(self, value, from_code: str | None) -> str:
        """ "$68 · ¥490" — the same price in the other currencies, for a line under the main price."""
        return " · ".join(x["text"] for x in self.all(value, from_code) if not x["on"])

    def rates(self, from_code: str | None) -> str:
        """ "$1 = ¥7.2 · $1 = 12 800 so'm" — the rates behind those prices."""
        src = get(from_code)
        if src is None:
            return ""
        return " · ".join(r for c in self.choices if c.code != src.code and (r := self.rate_line(src.code, c.code)))

    def converts(self, from_code: str | None) -> bool:
        return self.cur is not None and get(from_code) is not None and self.cur.code != (from_code or "").upper()

    def original(self, value, from_code: str | None) -> str:
        return display(value, from_code)

    def amount(self, value, from_code: str | None):
        """Number in the viewer's currency (for client-side totals), or the value as priced."""
        v = convert(value, from_code, self.cur.code) if self.cur else None
        return v if v is not None else Decimal(value or 0)

    def js(self, from_code: str | None) -> dict:
        """How the client formats amount() for this price: symbol, position, decimals."""
        c = (self.cur if self.converts(from_code) else None) or get(from_code)
        if c is None:
            code = (from_code or "USD").upper()
            return {"sym": "$" if code == "USD" else code, "first": code == "USD", "dec": 2}
        return {"sym": c.symbol, "first": c.symbol_first, "dec": c.decimals}

    def rate_line(self, from_code: str | None, to_code: str | None = None) -> str:
        """"$1 = 12 800 so'm" — one unit of from_code in to_code (default: the viewer's currency)."""
        src, dst = get(from_code), get(to_code) if to_code else self.cur
        if src is None or dst is None or src.code == dst.code:
            return ""
        v = convert(1, src.code, dst.code)
        return f"{fmt(1, src)} = {fmt(v, dst, exact=True)}" if v is not None else ""

    def range(self, lo, hi, from_code: str | None) -> str:
        """Catalogue price range: "$40–$400" or "512 000–5 120 000 so'm"."""
        a, b = self(lo, from_code), self(hi, from_code)
        c = self.cur if self.converts(from_code) else get(from_code)
        if c is not None and not c.symbol_first and a.endswith(NBSP + c.symbol):
            a = a[: -len(NBSP + c.symbol)]
        return f"{a}–{b}"

    def to_base(self, value: float | None, to_code: str | None = None) -> float | None:
        """A number the viewer typed in their currency, back in the given (default: base) currency."""
        if value is None or self.cur is None:
            return value
        v = convert(value, self.cur.code, to_code or base_code())
        return float(v) if v is not None else value
