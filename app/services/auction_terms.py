"""The auction terms a customer must read and accept before joining a lot (a bid or a deposit).

The text lives in the `auction_terms` setting — {"show": bool, "version": int, "title": {lang: text}, "body": {lang: text}} — and
is edited on the admin Auctions page or through the assistant. Acceptance is stamped on the user (date + version); when the
admin asks for a fresh acceptance the version goes up and everybody reads the terms again. With `show` off nothing is asked.
"""
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.i18n import pick, t
from app.models import Setting, User
from app.services.settings_service import get_setting, set_setting

KEY = "auction_terms"


def clean(value) -> dict:
    """A saved value → {"show", "version", "title", "body"}; asked for unless switched off, version at least 1, empty texts dropped."""
    v = value if isinstance(value, dict) else {}
    texts = lambda d: {k: str(x).strip() for k, x in (d if isinstance(d, dict) else {}).items() if str(x or "").strip()}  # noqa: E731
    try:
        version = max(1, int(v.get("version") or 1))
    except (TypeError, ValueError):
        version = 1
    return {"show": bool(v.get("show", True)), "version": version, "title": texts(v.get("title")), "body": texts(v.get("body"))}


async def load(db: AsyncSession) -> dict:
    return clean(await get_setting(db, KEY))


async def updated_at(db: AsyncSession) -> datetime | None:
    row = await db.get(Setting, KEY)
    return row.updated_at if row is not None else None


def title(terms: dict, lang: str) -> str:
    return pick(terms["title"], lang) or t(lang, "auction.terms_title")


def body(terms: dict, lang: str) -> str:
    return pick(terms["body"], lang) or t(lang, "auction.terms_default")


def paragraphs(text: str) -> list[str]:
    """The terms as paragraphs: blank lines separate them, single line breaks stay inside one."""
    return [p.strip() for p in text.replace("\r", "").split("\n\n") if p.strip()]


def accepted(user: User | None, terms: dict) -> bool:
    """Nothing to accept when the terms are off; otherwise the user must have accepted this very version."""
    if not terms["show"]:
        return True
    return bool(user is not None and (user.auction_terms_version or 0) >= terms["version"])


async def is_accepted(db: AsyncSession, user: User | None) -> bool:
    return accepted(user, await load(db))


async def accept(db: AsyncSession, user: User, terms: dict | None = None) -> dict:
    """Stamp the user's acceptance of the current version. Caller commits."""
    terms = terms or await load(db)
    user.auction_terms_at = datetime.now(UTC)
    user.auction_terms_version = terms["version"]
    await db.flush()
    return terms


async def save(db: AsyncSession, *, show: bool | None = None, title: dict | None = None, body: dict | None = None, reaccept: bool = False) -> dict:
    """Change the terms; `reaccept` raises the version so every customer reads them again. Caller commits."""
    cur = await load(db)
    if show is not None:
        cur["show"] = bool(show)
    if title is not None:
        cur["title"] = title
    if body is not None:
        cur["body"] = body
    if reaccept:
        cur["version"] += 1
    cur = clean(cur)
    await set_setting(db, KEY, cur)
    return cur


async def accepted_count(db: AsyncSession, terms: dict) -> int:
    """How many customers have accepted the current version."""
    return (await db.execute(select(func.count()).select_from(User).where(User.auction_terms_version >= terms["version"]))).scalar_one()
