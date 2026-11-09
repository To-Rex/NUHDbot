"""Admin → Ad posts: a post (text + 1–10 products) goes to Telegram groups and channels from an address book of chats the
bot knows; each send is kept per chat, and the post's link counts clicks, customers and orders back to the campaign."""
import re

from fastapi import Depends, HTTPException, Request
from sqlalchemy import func, select

from app.admin.common import ADS_ROLES, DB, back, f_str, render, staff_dep, toast
from app.admin.router import router
from app.bot.instance import get_bot
from app.config import settings
from app.enums import AdPostStatus
from app.i18n import t
from app.models import AdPost, Order, Product, User
from app.services import ads, audit
from app.services.ads import deep_links, new_campaign, render_post  # noqa: F401  (the assistant's tools import them from here)

TARGET_ICONS = {"channel": "bell", "supergroup": "users", "group": "users", "private": "user"}


async def _products(db, ids: list[int]) -> list[Product]:
    return await ads.products_of(db, ids)


async def _all_products(db) -> list[Product]:
    return (await db.execute(select(Product).where(Product.is_active.is_(True)).order_by(Product.brand, Product.model))).scalars().unique().all()


def _hx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


async def _targets_ctx(db, checked: list[int]) -> dict:
    rows = await ads.targets(db)
    known = {r["id"] for r in rows}
    return {"targets": rows, "checked": checked, "extra_ids": [i for i in checked if i not in known], "target_icons": TARGET_ICONS, "bot_on": get_bot() is not None,
            "staff_chat": settings.admin_chat_id}


async def _form_ctx(db, post: AdPost, **extra) -> dict:
    return {"post": post, "products": await _all_products(db), "links": deep_links(post.campaign), **(await _targets_ctx(db, list(post.target_chat_ids or []))), **extra}


# ---------- list ----------

@router.get("/ads")
async def ads_list(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    rows = (await db.execute(select(AdPost).order_by(AdPost.id.desc()).limit(200))).scalars().all()
    camps = {p.campaign for p in rows} | {f"src_{p.campaign}" for p in rows}
    users_by, orders_by = {}, {}
    if camps:
        for src, n in (await db.execute(select(User.source, func.count()).where(User.source.in_(camps)).group_by(User.source))).all():
            users_by[src.removeprefix("src_")] = users_by.get(src.removeprefix("src_"), 0) + n
        for src, n in (await db.execute(select(Order.source, func.count()).where(Order.source.in_(camps)).group_by(Order.source))).all():
            orders_by[src.removeprefix("src_")] = orders_by.get(src.removeprefix("src_"), 0) + n
    names = {r["id"]: r for r in await ads.targets(db)}
    items = [{"p": p, "users": users_by.get(p.campaign, 0), "orders": orders_by.get(p.campaign, 0), "sum": ads.summary(p), "targets": [names.get(c, {"id": c, "title": str(c), "type": "group"}) for c in p.target_chat_ids]} for p in rows]
    totals = {"posts": len(rows), "sent": sum(1 for p in rows if p.status == AdPostStatus.SENT), "clicks": sum(p.clicks for p in rows), "users": sum(users_by.values()), "orders": sum(orders_by.values())}
    return render(request, staff, "admin/ads/list.html", {"page_title": t(staff.lang, "admin.ads.title"), "items": items, "totals": totals, "bot_on": get_bot() is not None, "n_targets": len(names)})


# ---------- new ----------

def _blank() -> AdPost:
    return AdPost(title="", text="", product_ids=[], target_chat_ids=[], campaign=new_campaign(), deliveries=[])


@router.get("/ads/new")
async def ad_new(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    post = _blank()
    src = request.query_params.get("copy")
    if src and src.isdigit():  # a copy of an earlier post, as a new draft
        orig = await db.get(AdPost, int(src))
        if orig is not None:
            post.title, post.text, post.product_ids, post.target_chat_ids = orig.title, orig.text, list(orig.product_ids), list(orig.target_chat_ids)
    return render(request, staff, "admin/ads/form.html", {"page_title": t(staff.lang, "admin.ads.new"), "is_new": True, **(await _form_ctx(db, post))})


def _apply(post: AdPost, form) -> list[str]:
    errors = []
    post.title = f_str(form, "title", maxlen=120)
    post.text = (form.get("text") or "").strip()
    ids = list(dict.fromkeys(int(x) for x in form.getlist("product_ids") if x.isdigit()))
    if not (1 <= len(ids) <= 10):
        errors.append("products")
    post.product_ids = ids
    picked = [int(x) for x in form.getlist("target_ids") if re.fullmatch(r"-?\d+", x)]
    extra = ads.parse_ids(form.get("targets"))
    post.target_chat_ids = list(dict.fromkeys(picked + extra))
    if not post.title or not post.text:
        errors.append("title/text")
    return errors


@router.post("/ads/new")
async def ad_create(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    form = await request.form()
    post = AdPost(created_by=staff.id, deliveries=[], campaign=new_campaign())  # the link code is made here, nobody has to think one up
    errors = _apply(post, form)
    if errors:
        return render(request, staff, "admin/ads/form.html", {"page_title": t(staff.lang, "admin.ads.new"), "is_new": True, "errors": errors, **(await _form_ctx(db, post))}, status_code=400)
    db.add(post)
    await db.flush()
    await audit.log(db, staff.id, "ad.create", "ad", post.id, None, {"campaign": post.campaign})
    await db.commit()
    return back(request, f"/admin/ads/{post.id}", t(staff.lang, "admin.flash.saved"))


# ---------- the address book of chats ----------

@router.post("/ads/targets")
async def ad_target_add(request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    """Look a chat up (id, @username or t.me link) with the bot and add it; the block comes back with it checked."""
    form = await request.form()
    ref = f_str(form, "target_ref", maxlen=120)
    checked = [int(x) for x in form.getlist("target_ids") if re.fullmatch(r"-?\d+", x)]
    msg, kind = "", "ok"
    try:
        row = await ads.check_target(db, get_bot(), ref)
        checked.append(row["id"])
        await audit.log(db, staff.id, "ad.target_add", "setting", "ad_targets", None, {"id": row["id"], "title": row["title"]})
        await db.commit()
        msg = t(staff.lang, "admin.ads.target_added", title=row["title"] or row["id"])
    except ads.TargetError as e:
        code = str(e)
        kind = "bad"
        msg = t(staff.lang, f"admin.ads.target_err_{code}") if code in ("bad_ref", "bot_off", "not_found") else t(staff.lang, "admin.ads.target_err_api", e=code.removeprefix("api:"))
    if _hx(request):
        return render(request, staff, "admin/ads/_targets.html", await _targets_ctx(db, list(dict.fromkeys(checked))), headers=toast(msg, kind))
    return back(request, request.headers.get("referer") or "/admin/ads", msg, kind)


@router.post("/ads/targets/{chat_id}/delete")
async def ad_target_delete(chat_id: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    form = await request.form()
    checked = [int(x) for x in form.getlist("target_ids") if re.fullmatch(r"-?\d+", x) and int(x) != chat_id]
    if await ads.remove_target(db, chat_id):
        await audit.log(db, staff.id, "ad.target_delete", "setting", "ad_targets", None, {"id": chat_id})
        await db.commit()
    if _hx(request):
        return render(request, staff, "admin/ads/_targets.html", await _targets_ctx(db, checked), headers=toast(t(staff.lang, "admin.flash.deleted")))
    return back(request, request.headers.get("referer") or "/admin/ads", t(staff.lang, "admin.flash.deleted"))


# ---------- one post ----------

async def _detail_ctx(db, request: Request, staff: User, post: AdPost) -> dict:
    products = await _products(db, post.product_ids)
    src = f"src_{post.campaign}"
    users_n = (await db.execute(select(func.count()).select_from(User).where(User.source.in_([src, post.campaign])))).scalar_one()
    orders_n = (await db.execute(select(func.count()).select_from(Order).where(Order.source.in_([src, post.campaign])))).scalar_one()
    names = {r["id"]: r for r in await ads.targets(db)}
    deliveries = [{**d, "title": d.get("title") or names.get(d.get("chat_id"), {}).get("title") or str(d.get("chat_id"))} for d in reversed(post.deliveries or [])]
    return {"page_title": post.title, "preview": render_post(post, products), "preview_photo": ads.photo_url(products), "users_n": users_n, "orders_n": orders_n, "deliveries": deliveries, "sum": ads.summary(post),
            "staff_tg": staff.tg_id, "button_text": ads.button_text(staff.lang), **(await _form_ctx(db, post))}


@router.get("/ads/{pid}")
async def ad_detail(pid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    post = await db.get(AdPost, pid)
    if not post:
        raise HTTPException(404)
    return render(request, staff, "admin/ads/detail.html", await _detail_ctx(db, request, staff, post))


@router.post("/ads/{pid}")
async def ad_update(pid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADS_ROLES))):
    post = await db.get(AdPost, pid)
    if not post:
        raise HTTPException(404)
    form = await request.form()
    action = form.get("action")
    lang = staff.lang
    if action == "approve":
        post.status, post.approved_by = AdPostStatus.APPROVED, staff.id
        await audit.log(db, staff.id, "ad.approve", "ad", post.id)
        await db.commit()
        return back(request, f"/admin/ads/{pid}", t(lang, "admin.ads.approved"))
    if action == "unapprove":
        post.status = AdPostStatus.DRAFT
        await audit.log(db, staff.id, "ad.unapprove", "ad", post.id)
        await db.commit()
        return back(request, f"/admin/ads/{pid}", t(lang, "admin.flash.saved"))
    if action in ("send", "test"):
        bot = get_bot()
        if bot is None:
            return back(request, f"/admin/ads/{pid}", t(lang, "admin.ads.bot_off"), "bad")
        if action == "test":
            chat = staff.tg_id if form.get("to") == "me" else settings.admin_chat_id
            if not chat:
                return back(request, f"/admin/ads/{pid}", t(lang, "admin.ads.test_no_chat"), "bad")
            r = await ads.send_test(db, bot, post, int(chat))
            await audit.log(db, staff.id, "ad.test", "ad", post.id, None, {"chat": chat, "ok": r["ok"], "error": r["error"]})
            await db.commit()
            return back(request, f"/admin/ads/{pid}", t(lang, "admin.ads.test_sent") if r["ok"] else t(lang, "admin.ads.test_failed", e=r["error"] or ""), "ok" if r["ok"] else "bad")
        if post.status != AdPostStatus.APPROVED:
            return back(request, f"/admin/ads/{pid}", t(lang, "admin.ads.approve_first"), "bad")
        if not post.target_chat_ids:
            return back(request, f"/admin/ads/{pid}", t(lang, "admin.ads.no_targets"), "bad")
        results = await ads.send_post(db, bot, post)
        ok, bad = sum(1 for r in results if r["ok"]), sum(1 for r in results if not r["ok"])
        await audit.log(db, staff.id, "ad.send", "ad", post.id, None, {"ok": ok, "bad": bad, "errors": [f"{r['chat_id']}: {r['error']}" for r in results if not r["ok"]]})
        await db.commit()
        return back(request, f"/admin/ads/{pid}", t(lang, "admin.ads.send_result", ok=ok, bad=bad), "ok" if not bad else ("warn" if ok else "bad"))
    if action == "delete":
        await db.delete(post)
        await audit.log(db, staff.id, "ad.delete", "ad", pid)
        await db.commit()
        return back(request, "/admin/ads", t(lang, "admin.flash.deleted"))
    if post.status == AdPostStatus.SENT and action != "save_targets":
        return back(request, f"/admin/ads/{pid}", t(lang, "admin.ads.sent_locked"), "bad")
    errors = _apply(post, form)
    if errors:
        return back(request, f"/admin/ads/{pid}", t(lang, "admin.ads.need_products") if "products" in errors else t(lang, "admin.ads.need_text"), "bad")
    if post.status == AdPostStatus.APPROVED:
        post.status = AdPostStatus.DRAFT  # edits require re-approval
    await audit.log(db, staff.id, "ad.update", "ad", post.id)
    await db.commit()
    return back(request, f"/admin/ads/{pid}", t(lang, "admin.flash.saved"))
