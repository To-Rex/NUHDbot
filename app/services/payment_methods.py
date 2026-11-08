"""Payment methods the shop accepts (Alipay, WeChat Pay, cards, USDT…): each with a QR code — a picture the admin uploaded,
or one generated here from a payment link / wallet address — and the details to copy. The Mini App shows them when a
customer pays an auction deposit or an order; the admin manages them at /admin/payments."""
import io

import segno
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import PaymentMethodKind
from app.i18n import pick
from app.models import PaymentMethod
from app.services import media

# the presets behind the kind picker: a usual name and what the "account" line is (the admin may change both)
PRESETS: dict[PaymentMethodKind, dict] = {
    PaymentMethodKind.ALIPAY: {"name": "Alipay", "account": "account", "icon": "scan"},
    PaymentMethodKind.WECHAT: {"name": "WeChat Pay", "account": "account", "icon": "bubble"},
    PaymentMethodKind.UNIONPAY: {"name": "UnionPay", "account": "card", "icon": "creditcard"},
    PaymentMethodKind.CARD: {"name": "Bank card", "account": "card", "icon": "creditcard"},
    PaymentMethodKind.BANK: {"name": "Bank transfer", "account": "iban", "icon": "building"},
    PaymentMethodKind.USDT: {"name": "USDT (TRC20)", "account": "wallet", "icon": "wallet"},
    PaymentMethodKind.PAYPAL: {"name": "PayPal", "account": "email", "icon": "mail"},
    PaymentMethodKind.OTHER: {"name": "", "account": "account", "icon": "qr"},
}


def icon(m: PaymentMethod) -> str:
    return PRESETS.get(m.kind, PRESETS[PaymentMethodKind.OTHER])["icon"]


def kind_of(value) -> PaymentMethodKind:
    try:
        return PaymentMethodKind(str(value or "other").lower())
    except ValueError:
        return PaymentMethodKind.OTHER


def instructions(m: PaymentMethod, lang: str) -> str:
    return pick(m.instructions or {}, lang) or ""


async def list_methods(db: AsyncSession, *, purpose: str | None = None, active_only: bool = True) -> list[PaymentMethod]:
    """All methods in the admin's order; purpose "deposit" / "order" keeps the ones shown there."""
    stmt = select(PaymentMethod)
    if active_only:
        stmt = stmt.where(PaymentMethod.is_active.is_(True))
    if purpose == "deposit":
        stmt = stmt.where(PaymentMethod.for_deposits.is_(True))
    elif purpose == "order":
        stmt = stmt.where(PaymentMethod.for_orders.is_(True))
    return list((await db.execute(stmt.order_by(PaymentMethod.sort, PaymentMethod.id))).scalars().all())


async def get(db: AsyncSession, method_id: int | None) -> PaymentMethod | None:
    return await db.get(PaymentMethod, method_id) if method_id else None


async def next_sort(db: AsyncSession) -> int:
    return ((await db.execute(select(func.max(PaymentMethod.sort)))).scalar_one() or 0) + 1


def qr_svg(text: str, *, scale: int = 8) -> bytes:
    """A QR code of `text` as an SVG picture: dark modules on white, with a quiet zone, so phones scan it in any theme."""
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="svg", scale=scale, border=3, dark="#111111", light="#ffffff", xmldecl=False, svgversion=None)
    return buf.getvalue()


def qr_png(text: str, *, scale: int = 10) -> bytes:
    buf = io.BytesIO()
    segno.make(text, error="m").save(buf, kind="png", scale=scale, border=3, dark="#111111", light="#ffffff")
    return buf.getvalue()


async def set_qr_picture(m: PaymentMethod, file) -> None:
    """A QR picture the admin uploaded replaces the old one (and the generated text QR, if any)."""
    meta = await media.save_image(file, prefix=f"pm{m.id or 0}")
    old = m.qr_filename
    m.qr_filename = meta["filename"]
    m.qr_text = None
    await media.delete_files(old, meta["thumb"])  # one picture is enough: no thumbnail kept


async def clear_qr_picture(m: PaymentMethod) -> None:
    if m.qr_filename:
        await media.delete_files(m.qr_filename)
        m.qr_filename = None


async def delete(db: AsyncSession, m: PaymentMethod) -> None:
    await clear_qr_picture(m)
    await db.delete(m)
    await db.flush()


def as_dict(m: PaymentMethod) -> dict:
    return {"id": m.id, "kind": m.kind.value, "name": m.name, "account": m.account, "instructions": m.instructions or {}, "currency": m.currency,
            "qr": "picture" if m.qr_filename else ("generated" if m.qr_text else None), "qr_text": m.qr_text, "qr_url": m.qr_url,
            "for_deposits": m.for_deposits, "for_orders": m.for_orders, "is_active": m.is_active, "sort": m.sort}
