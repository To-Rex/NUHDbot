from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import Role
from app.i18n import normalize_lang
from app.models import User
from app.security import hash_password, verify_password


async def get_or_create_tg_user(db: AsyncSession, tg_user: dict, source: str | None = None) -> User:
    tg_id = int(tg_user["id"])
    user = (await db.execute(select(User).where(User.tg_id == tg_id))).scalar_one_or_none()
    now = datetime.now(UTC)
    if user is None:
        user = User(
            tg_id=tg_id,
            tg_username=tg_user.get("username"),
            first_name=(tg_user.get("first_name") or "")[:100],
            last_name=(tg_user.get("last_name") or "")[:100],
            lang=normalize_lang(tg_user.get("language_code")),
            source=source,
            last_seen_at=now,
        )
        db.add(user)
        await db.flush()
    else:
        user.tg_username = tg_user.get("username") or user.tg_username
        user.last_seen_at = now
        if source and not user.source:
            user.source = source
    return user


async def complete_registration(
    db: AsyncSession,
    user: User,
    *,
    first_name: str,
    last_name: str,
    phone: str,
    country: str,
    city: str,
    lang: str,
    bought_before: bool | None,
    ads_opt_in: bool,
) -> User:
    user.first_name = first_name.strip()[:100]
    user.last_name = last_name.strip()[:100]
    user.phone = phone.strip()[:32]
    user.country = country.strip().upper()[:2]
    user.city = city.strip()[:100]
    user.lang = normalize_lang(lang)
    user.bought_from_china_before = bought_before
    user.ads_opt_in = ads_opt_in
    if not user.registered_at:
        user.registered_at = datetime.now(UTC)
    await db.flush()
    return user


async def set_phone_from_contact(db: AsyncSession, user: User, phone: str) -> None:
    user.phone = phone if phone.startswith("+") else f"+{phone}"
    user.phone_verified = True
    await db.flush()


async def authenticate_staff(db: AsyncSession, login: str, password: str) -> User | None:
    user = (await db.execute(select(User).where(User.login == login))).scalar_one_or_none()
    if user and user.is_staff and not user.is_blocked and verify_password(password, user.password_hash):
        return user
    return None


async def ensure_initial_admin(db: AsyncSession, login: str, password: str) -> User:
    existing = (await db.execute(select(User).where(User.login == login))).scalar_one_or_none()
    if existing:
        return existing
    admin = User(first_name="Admin", role=Role.ADMIN, login=login, password_hash=hash_password(password), lang="uz")
    db.add(admin)
    await db.flush()
    return admin
