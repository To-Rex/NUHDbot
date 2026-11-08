"""The lot rules shown on every lot page (payment, disputes, anti-sniping…).

One common text for all lots lives in the `auction_rules` setting — {"body": {lang: text}} — edited on the admin Auctions page or
through the assistant; empty means the standard text. A lot may carry its own rules instead (`Auction.rules`), set on the lot
form; a lot without its own text shows the common one.
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.i18n import pick, t
from app.models import Auction
from app.services.settings_service import get_setting, set_setting

KEY = "auction_rules"


def clean(value) -> dict:
    v = value if isinstance(value, dict) else {}
    body = v.get("body") if isinstance(v.get("body"), dict) else {}
    return {"body": {k: str(x).strip() for k, x in body.items() if str(x or "").strip()}}


async def load(db: AsyncSession) -> dict:
    return clean(await get_setting(db, KEY))


def common_text(rules: dict, lang: str) -> str:
    """The common rules in a language: the admin's text, else the standard one."""
    return pick(rules["body"], lang) or t(lang, "auction.rules_default")


def text_for(a: Auction, rules: dict, lang: str) -> str:
    """What a lot page shows: the lot's own rules when it has any, else the common ones."""
    return pick(a.rules or {}, lang) or common_text(rules, lang)


def has_own(a: Auction) -> bool:
    return any(str(v or "").strip() for v in (a.rules or {}).values())


async def save(db: AsyncSession, *, body: dict) -> dict:
    rules = clean({"body": body})
    await set_setting(db, KEY, rules)
    return rules


async def own_count(db: AsyncSession) -> int:
    """How many lots (not drafts) carry their own rules."""
    rows = (await db.execute(select(Auction.rules).where(Auction.status != "draft"))).scalars().all()
    return sum(1 for r in rows if any(str(v or "").strip() for v in (r or {}).values()))


async def clear_own(db: AsyncSession, a: Auction) -> None:
    a.rules = {}


async def total_count(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(Auction).where(Auction.status != "draft"))).scalar_one()
