import html
import re
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select

from app.admin.common import ADS_ROLES, DB, back, f_str, render, staff_dep
from app.admin.router import router
from app.bot.instance import get_bot
from app.config import settings
from app.enums import AdPostStatus
from app.i18n import t
from app.models import AdPost, Order, Product, User
from app.services import audit
from app.templating import capacity, money


def deep_links(campaign: str) -> dict:
    return {"app": f"https://t.me/{settings.bot_username}?startapp=src_{campaign}", "start": f"https://t.me/{settings.bot_username}?start=src_{campaign}"}


def render_post(post: AdPost, products: list[Product]) -> str:
    lines = [html.escape(post.text).strip(), ""]
    for p in products:
        price = money(p.price, p.currency) if p.price is not None else "—"
        lines.append(f"• <b>{html.escape(p.brand)} {html.escape(p.model)}</b> {capacity(p.capacity_gb)} · {p.condition.value.upper()} · {price}/pc")
    links = deep_links(post.campaign)
    lines += ["", f"🛒 <a href=\"{links['app']}\">{html.escape(settings.app_name)}</a>"]
    return "\n".join(lines)


async def _products(db, ids: list[int]) -> list[Product]:
    if not ids:
        return []
    rows = (await db.execute(select(Product).where(Product.id.in_(ids)))).scalars().unique().all()
    by = {p.id: p for p in rows}
    return [by[i] for i in ids if i in by]


@router.get("/ads")
async def ads_list(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    rows = (await db.execute(select(AdPost).order_by(AdPost.id.desc()).limit(200))).scalars().all()
    return render(request, staff, "admin/ads/list.html", {"page_title": t(staff.lang, "admin.ads.title"), "rows": rows})


@router.get("/ads/new")
async def ad_new(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    products = (await db.execute(select(Product).where(Product.is_active.is_(True)).order_by(Product.brand, Product.model))).scalars().unique().all()
    post = AdPost(title="", text="", product_ids=[], target_chat_ids=[], campaign=f"c{datetime.now(UTC):%y%m%d}")
    return render(request, staff, "admin/ads/form.html", {"page_title": t(staff.lang, "admin.ads.new"), "post": post, "products": products, "is_new": True})


def _apply(post: AdPost, form) -> list[str]:
    errors = []
    post.title = f_str(form, "title", maxlen=120)
    post.text = (form.get("text") or "").strip()
    post.campaign = re.sub(r"[^a-zA-Z0-9_-]", "", f_str(form, "campaign", maxlen=64)) or "camp"
    ids = [int(x) for x in form.getlist("product_ids") if x.isdigit()]
    if not (3 <= len(ids) <= 5):
        errors.append("products")
    post.product_ids = ids
    post.target_chat_ids = [int(x) for x in re.split(r"[,\s]+", form.get("targets") or "") if re.fullmatch(r"-?\d+", x)]
    if not post.title or not post.text:
        errors.append("title/text")
    return errors


@router.post("/ads/new")
async def ad_create(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    form = await request.form()
    post = AdPost(created_by=staff.id)
    errors = _apply(post, form)
    if errors:
        products = (await db.execute(select(Product).where(Product.is_active.is_(True)).order_by(Product.brand, Product.model))).scalars().unique().all()
        return render(request, staff, "admin/ads/form.html", {"page_title": t(staff.lang, "admin.ads.new"), "post": post, "products": products, "is_new": True, "errors": errors}, status_code=400)
    db.add(post)
    await db.flush()
    await audit.log(db, staff.id, "ad.create", "ad", post.id, None, {"campaign": post.campaign})
    await db.commit()
    return back(request, f"/admin/ads/{post.id}", t(staff.lang, "admin.flash.saved"))


@router.get("/ads/{pid}")
async def ad_detail(pid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    post = await db.get(AdPost, pid)
    if not post:
        raise HTTPException(404)
    products = await _products(db, post.product_ids)
    src = f"src_{post.campaign}"
    users_n = (await db.execute(select(func.count()).select_from(User).where(User.source.in_([src, post.campaign])))).scalar_one()
    orders_n = (await db.execute(select(func.count()).select_from(Order).where(Order.source.in_([src, post.campaign])))).scalar_one()
    all_products = (await db.execute(select(Product).where(Product.is_active.is_(True)).order_by(Product.brand, Product.model))).scalars().unique().all()
    return render(request, staff, "admin/ads/detail.html", {"page_title": post.title, "post": post, "products": products, "all_products": all_products, "preview": render_post(post, products), "links": deep_links(post.campaign), "users_n": users_n, "orders_n": orders_n, "bot_on": get_bot() is not None})


@router.post("/ads/{pid}")
async def ad_update(pid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    post = await db.get(AdPost, pid)
    if not post:
        raise HTTPException(404)
    form = await request.form()
    action = form.get("action")
    if action == "approve":
        post.status = AdPostStatus.APPROVED
        post.approved_by = staff.id
        await audit.log(db, staff.id, "ad.approve", "ad", post.id)
        await db.commit()
        return back(request, f"/admin/ads/{pid}", t(staff.lang, "admin.ads.approved"))
    if action == "send":
        if post.status != AdPostStatus.APPROVED:
            return back(request, f"/admin/ads/{pid}", t(staff.lang, "admin.forbidden"), "bad")
        bot = get_bot()
        if bot is None:
            return back(request, f"/admin/ads/{pid}", t(staff.lang, "admin.ads.bot_off"), "bad")
        text = render_post(post, await _products(db, post.product_ids))
        ok = bad = 0
        errors = []
        for chat in post.target_chat_ids:
            try:
                await bot.send_message(chat, text, disable_web_page_preview=True)
                ok += 1
            except Exception as e:  # noqa: BLE001
                bad += 1
                errors.append(f"{chat}: {str(e)[:120]}")
        if ok:
            post.status = AdPostStatus.SENT
            post.sent_at = datetime.now(UTC)
        await audit.log(db, staff.id, "ad.send", "ad", post.id, None, {"ok": ok, "bad": bad, "errors": errors})
        await db.commit()
        return back(request, f"/admin/ads/{pid}", t(staff.lang, "admin.ads.send_result", ok=ok, bad=bad), "ok" if not bad else "warn")
    if action == "delete":
        await db.delete(post)
        await db.commit()
        return back(request, "/admin/ads", t(staff.lang, "admin.flash.deleted"))
    errors = _apply(post, form)
    if errors:
        return back(request, f"/admin/ads/{pid}", t(staff.lang, "admin.ads.need_products") if "products" in errors else t(staff.lang, "admin.required"), "bad")
    if post.status == AdPostStatus.APPROVED:
        post.status = AdPostStatus.DRAFT  # edits require re-approval
    await audit.log(db, staff.id, "ad.update", "ad", post.id)
    await db.commit()
    return back(request, f"/admin/ads/{pid}", t(staff.lang, "admin.flash.saved"))
