"""More assistant tools: everything the admin pages do that the first set left out.

Images attached in the chat (AssistantUpload rows — the staff member's pictures, already converted and stored) go onto
products, banners, directions, auction lots and brand logos; the home page layout (block order, directions order,
hidden slider looks, the Drive conditions and Payment & delivery blocks); ad posts (edit, approve, send); auction
deposits and the winner's order; order lines and payment records; currencies; countries and cities; dictionary models;
the audit log and export links. Registered on import (see the end of tools.py).
"""
import re
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select

from app.config import settings
from app.enums import (
    COLOR_DIRECTION,
    AdPostStatus,
    AuctionStatus,
    DepositStatus,
    ImageKind,
    OrderStatus,
    PaymentKind,
    PaymentMethodKind,
    PaymentStatus,
    ProductColor,
)
from app.i18n import pick, t
from app.models import (
    AdPost,
    AssistantUpload,
    Auction,
    AuctionDeposit,
    AuctionImage,
    AuditLog,
    Banner,
    Brand,
    BrandModel,
    City,
    Country,
    Currency,
    Order,
    OrderItem,
    OrderStatusHistory,
    PaymentMethod,
    Product,
    ProductImage,
    Setting,
    User,
)
from app.models.base import utcnow
from app.services import (
    auction_rules,
    auction_terms,
    deletion,
    interests,
    model_dict,
    notifications,
    storage,
    ui_settings,
)
from app.services import auctions as asvc
from app.services import banners as bsvc
from app.services import orders as osvc
from app.services import payment_methods as pm_svc
from app.services import series as series_service
from app.services.assistant.tools import (
    ARR,
    I18N,
    B,
    Ctx,
    I,
    N,
    S,
    ToolError,
    _order,
    dec,
    i18n,
    limit,
    local,
    money,
    need,
    order_full,
    product_row,
    tool,
    user_row,
)
from app.services.settings_service import get_setting, set_setting

LOOKS = "coverflow orbit stack fan cylinder spiral cascade pile"


# ---------- attached pictures ----------

async def _uploads(ctx: Ctx, ids) -> list[AssistantUpload]:
    """The staff member's own, not yet used, attached pictures — in the order asked for."""
    ids = [int(i) for i in (ids if isinstance(ids, list) else [ids])]
    if not ids:
        raise ToolError("no upload ids given — the staff member attaches pictures with the paperclip in the chat")
    rows = {u.id: u for u in (await ctx.db.execute(select(AssistantUpload).where(AssistantUpload.id.in_(ids)))).scalars().all()}
    out = []
    for i in ids:
        u = rows.get(i)
        if u is None or u.staff_id != ctx.staff.id:
            raise ToolError(f"upload {i} not found — ask the staff member to attach the picture in the chat")
        if u.used:
            raise ToolError(f"upload {i} was already used; attach the picture again to use it once more")
        out.append(u)
    return out


def _use(ctx: Ctx, u: AssistantUpload) -> None:
    ctx.journal.track(u)
    u.used = True


async def _setting_row(ctx: Ctx, key: str, value) -> None:
    """Save a setting with its row in the undo journal."""
    row = await ctx.db.get(Setting, key)
    if row is not None:
        ctx.journal.track(row)
    await set_setting(ctx.db, key, value)
    if row is None:
        ctx.journal.created(await ctx.db.get(Setting, key))


@tool("list_uploads", "Pictures the staff member attached in the chat that are not used yet (id, name, size).")
async def list_uploads(ctx: Ctx):
    rows = (await ctx.db.execute(select(AssistantUpload).where(AssistantUpload.staff_id == ctx.staff.id, AssistantUpload.used.is_(False)).order_by(AssistantUpload.id.desc()).limit(40))).scalars().all()
    return {"uploads": [{"upload_id": u.id, "name": u.name, "size": f"{u.width}x{u.height}", "at": local(u.created_at)} for u in rows]}


@tool("list_product_images", "A product's photos (id, cover, kind sample|real).", {"product_id": I("")}, required=("product_id",))
async def list_product_images(ctx: Ctx, product_id: int):
    p = await need(ctx.db, Product, int(product_id), "product")
    return {"product": f"{p.brand} {p.model}", "images": [{"id": i.id, "is_cover": i.is_cover, "kind": i.kind.value, "sort": i.sort, "url": i.url} for i in p.images]}


@tool("add_product_images", "Put attached pictures on a product (the first photo of a product becomes its cover). kind: sample = stock photo, real = photo of the actual drive.",
      {"product_id": I(""), "upload_ids": ARR("Upload ids of the attached pictures"), "kind": S("sample | real (default sample)"), "make_cover": B("Make the first of these the cover")}, required=("product_id", "upload_ids"), mutating=True)
async def add_product_images(ctx: Ctx, product_id: int, upload_ids, kind=None, make_cover=False):
    from app.config import settings

    p = await need(ctx.db, Product, int(product_id), "product")
    ups = await _uploads(ctx, upload_ids)
    if len(p.images) + len(ups) > settings.max_images_per_product:
        raise ToolError(f"a product holds at most {settings.max_images_per_product} photos (it has {len(p.images)})")
    k = ImageKind(kind) if kind in ("sample", "real") else ImageKind.SAMPLE
    start, new = len(p.images), []
    if make_cover:
        for im in p.images:
            ctx.journal.track(im)
            im.is_cover = False
    for n, u in enumerate(ups):
        img = ProductImage(product_id=p.id, filename=u.filename, thumb=u.thumb, width=u.width, height=u.height, kind=k, is_cover=(n == 0 and (make_cover or start == 0)), sort=start + n)
        ctx.db.add(img)
        new.append(img)
        _use(ctx, u)
    await ctx.db.flush()
    for img in new:
        ctx.journal.created(img)
    await ctx.db.refresh(p, ["images"])
    ctx.summary, ctx.entity, ctx.entity_id = f"{len(new)} photo(s) added to {p.brand} {p.model}", "product", str(p.id)
    return {"ok": True, "images": len(p.images), "admin_url": f"/admin/products/{p.id}"}


@tool("product_image_action", "On one product photo: cover (make it the cover), delete, or kind (switch sample ↔ real).", {"product_id": I(""), "image_id": I(""), "action": S("cover | delete | kind")}, required=("product_id", "image_id", "action"), mutating=True)
async def product_image_action(ctx: Ctx, product_id: int, image_id: int, action: str):
    p = await need(ctx.db, Product, int(product_id), "product")
    img = next((i for i in p.images if i.id == int(image_id)), None)
    if img is None:
        raise ToolError("photo not found on this product")
    if action == "cover":
        for i in p.images:
            ctx.journal.track(i)
            i.is_cover = i.id == img.id
    elif action == "kind":
        ctx.journal.track(img)
        img.kind = ImageKind.REAL if img.kind == ImageKind.SAMPLE else ImageKind.SAMPLE
    elif action == "delete":
        was_cover = img.is_cover
        await ctx.journal.deleted(ctx.db, img)
        await deletion._rm(img.filename, img.thumb)
        p.images.remove(img)
        await ctx.db.delete(img)
        await ctx.db.flush()
        if was_cover and p.images:
            ctx.journal.track(p.images[0])
            p.images[0].is_cover = True
    else:
        raise ToolError("action: cover | delete | kind")
    await ctx.db.flush()
    ctx.summary, ctx.entity, ctx.entity_id = f"Photo {image_id} of {p.brand} {p.model}: {action}", "product", str(p.id)
    return {"ok": True}


@tool("set_banner_image", "Give a banner an attached picture, or remove its picture.", {"banner_id": I(""), "upload_id": I("Attached picture"), "remove": B("Remove the banner's picture")}, required=("banner_id",), mutating=True)
async def set_banner_image(ctx: Ctx, banner_id: int, upload_id=None, remove=False):
    b = await need(ctx.db, Banner, int(banner_id), "banner")
    ctx.journal.track(b)
    old = (b.image, b.image_thumb)
    if upload_id:
        u = (await _uploads(ctx, [upload_id]))[0]
        b.image, b.image_thumb = u.filename, u.thumb
        _use(ctx, u)
    elif remove:
        b.image = b.image_thumb = None
    else:
        raise ToolError("upload_id or remove is required")
    await deletion._rm(*old)
    await ctx.db.flush()
    ctx.summary, ctx.entity, ctx.entity_id = f"Banner {pick(b.title, 'uzl') or b.id}: picture {'set' if upload_id else 'removed'}", "banner", str(b.id)
    return {"ok": True}


def _direction(v) -> ProductColor:
    d = str(v or "").strip().lower()
    c = next((c for c, name in COLOR_DIRECTION.items() if d in (c.value, name.lower())), None)
    if c is None:
        raise ToolError("direction: one of " + ", ".join(f"{c.value} ({n})" for c, n in COLOR_DIRECTION.items()))
    return c


@tool("set_direction_image", "The picture of a catalogue direction (its card on the Mini App home): set it from an attached picture or remove it.",
      {"direction": S("blue/Desktop, purple/Surveillance, red/NAS, gold/Enterprise, silver/Data Center, black/Gaming"), "upload_id": I("Attached picture"), "remove": B("Remove the picture")}, required=("direction",), mutating=True)
async def set_direction_image(ctx: Ctx, direction, upload_id=None, remove=False):
    c = _direction(direction)
    images = dict(await get_setting(ctx.db, "direction_images") or {})
    old = images.get(c.value) or {}
    if upload_id:
        u = (await _uploads(ctx, [upload_id]))[0]
        images[c.value] = {"filename": u.filename, "thumb": u.thumb}
        _use(ctx, u)
    elif remove:
        images.pop(c.value, None)
    else:
        raise ToolError("upload_id or remove is required")
    await _setting_row(ctx, "direction_images", images)
    await deletion._rm(old.get("filename"), old.get("thumb"))
    ctx.summary, ctx.entity, ctx.entity_id = f"Direction {COLOR_DIRECTION[c]}: picture {'set' if upload_id else 'removed'}", "direction", c.value
    return {"ok": True}


@tool("auction_images", "Add attached pictures to an auction lot, or delete one of its pictures.", {"auction_id": I(""), "upload_ids": ARR("Attached pictures to add"), "delete_image_id": I("Picture of the lot to delete")}, required=("auction_id",), mutating=True)
async def auction_images(ctx: Ctx, auction_id: int, upload_ids=None, delete_image_id=None):
    a = await need(ctx.db, Auction, int(auction_id), "auction")
    done = []
    if upload_ids:
        start = len(a.images)
        new = []
        for n, u in enumerate(await _uploads(ctx, upload_ids)):
            img = AuctionImage(auction_id=a.id, filename=u.filename, thumb=u.thumb, sort=start + n)
            ctx.db.add(img)
            new.append(img)
            _use(ctx, u)
        await ctx.db.flush()
        for img in new:
            ctx.journal.created(img)
        done.append(f"{len(new)} added")
    if delete_image_id:
        img = await ctx.db.get(AuctionImage, int(delete_image_id))
        if img is None or img.auction_id != a.id:
            raise ToolError("picture not found on this lot")
        await ctx.journal.deleted(ctx.db, img)
        await deletion._rm(img.filename, img.thumb)
        await ctx.db.delete(img)
        await ctx.db.flush()
        done.append("1 deleted")
    if not done:
        raise ToolError("upload_ids or delete_image_id is required")
    ctx.summary, ctx.entity, ctx.entity_id = f"Auction #{a.id} pictures: {', '.join(done)}", "auction", str(a.id)
    return {"ok": True}


@tool("set_brand_logo", "A brand's logo from an attached picture, or remove it.", {"brand_id": I(""), "upload_id": I(""), "remove": B("")}, required=("brand_id",), mutating=True)
async def set_brand_logo(ctx: Ctx, brand_id: int, upload_id=None, remove=False):
    b = await need(ctx.db, Brand, int(brand_id), "brand")
    ctx.journal.track(b)
    old = (b.logo, b.logo_thumb)
    if upload_id:
        u = (await _uploads(ctx, [upload_id]))[0]
        b.logo, b.logo_thumb = u.filename, u.thumb
        _use(ctx, u)
    elif remove:
        b.logo = b.logo_thumb = None
    else:
        raise ToolError("upload_id or remove is required")
    await deletion._rm(*old)
    await ctx.db.flush()
    ctx.summary, ctx.entity, ctx.entity_id = f"Brand {b.name}: logo {'set' if upload_id else 'removed'}", "brand", str(b.id)
    return {"ok": True}


# ---------- the Mini App home ----------

@tool("get_home_settings", "How the Mini App home is laid out: block order, directions order, automatic slides, slider looks (chosen and hidden), the Drive conditions and Payment & delivery blocks.")
async def get_home_settings(ctx: Ctx):
    g = lambda k: get_setting(ctx.db, k)  # noqa: E731
    cur_b, cur_d = bsvc.clean_style(await g("banner_slider_style")), series_service.clean_style(await g("dir_slider_style"))
    return {
        "blocks_order": bsvc.clean_order(await g("home_order")), "directions_order": bsvc.clean_order(await g("direction_order"), bsvc.DIRECTIONS),
        "direction_names": {c.value: n for c, n in COLOR_DIRECTION.items()}, "direction_images": sorted((await g("direction_images") or {}).keys()),
        "auto_slides": bsvc.clean_auto_slides(await g("auto_slides")), "slide_seconds": await g("slider_seconds"), "dir_slide_seconds": await g("dir_slider_seconds"),
        "banner_slider": {"look": cur_b, "shape": bsvc.clean_shape(await g("banner_slider_shape")), "hidden_looks": bsvc.clean_hidden(await g("banner_styles_hidden"), bsvc.STYLES, cur_b), "all_looks": list(bsvc.STYLES)},
        "directions_slider": {"look": cur_d, "shape": bsvc.clean_shape(await g("dir_slider_shape")), "hidden_looks": bsvc.clean_hidden(await g("dir_styles_hidden"), series_service.DIR_STYLES, cur_d), "all_looks": list(series_service.DIR_STYLES)},
        "conditions_block": bsvc.clean_conditions(await g("home_conditions")), "terms_block": bsvc.clean_terms(await g("home_terms")) | {"payment_text": await g("payment_text"), "delivery_text": await g("delivery_text")},
    }


@tool("set_home_layout", "Order of the Mini App home: the blocks (banners, directions, auctions) and/or the six directions (blue purple red gold silver black). Give the full list in the wanted order; names you leave out go to the end.",
      {"blocks_order": ARR("banners | directions | auctions, first = top", {"type": "string"}), "directions_order": ARR("Direction colours, first = in front", {"type": "string"})}, mutating=True)
async def set_home_layout(ctx: Ctx, blocks_order=None, directions_order=None):
    done = []
    if blocks_order:
        order = bsvc.clean_order([str(x).lower() for x in blocks_order])
        await _setting_row(ctx, "home_order", order)
        done.append("blocks: " + " → ".join(order))
    if directions_order:
        order = bsvc.clean_order([_direction(x).value for x in directions_order], bsvc.DIRECTIONS)
        await _setting_row(ctx, "direction_order", order)
        done.append("directions: " + " → ".join(COLOR_DIRECTION[ProductColor(c)] for c in order))
    if not done:
        raise ToolError("blocks_order or directions_order is required")
    ctx.summary, ctx.entity = "Home layout — " + "; ".join(done), "setting"
    return {"ok": True}


@tool("set_slider_looks_hidden", f"Which animation looks are hidden from the admin pickers (full lists; the chosen look cannot be hidden). Looks: {LOOKS}; the Directions slider has coverflow orbit stack fan.",
      {"banner_hidden": ARR("Hidden looks of the banner slider ([] = none)", {"type": "string"}), "directions_hidden": ARR("Hidden looks of the Directions slider ([] = none)", {"type": "string"})}, mutating=True)
async def set_slider_looks_hidden(ctx: Ctx, banner_hidden=None, directions_hidden=None):
    done = []
    if banner_hidden is not None:
        cur = bsvc.clean_style(await get_setting(ctx.db, "banner_slider_style"))
        v = bsvc.clean_hidden([str(x) for x in banner_hidden], bsvc.STYLES, cur)
        await _setting_row(ctx, "banner_styles_hidden", v)
        done.append(f"banner: {', '.join(v) or 'none'}")
    if directions_hidden is not None:
        cur = series_service.clean_style(await get_setting(ctx.db, "dir_slider_style"))
        v = bsvc.clean_hidden([str(x) for x in directions_hidden], series_service.DIR_STYLES, cur)
        await _setting_row(ctx, "dir_styles_hidden", v)
        done.append(f"directions: {', '.join(v) or 'none'}")
    if not done:
        raise ToolError("banner_hidden or directions_hidden is required")
    ctx.summary, ctx.entity = "Hidden slider looks — " + "; ".join(done), "setting"
    return {"ok": True}


@tool("set_home_block", "The Mini App home's text blocks. block=conditions: show, title, and the New / Used / Refresh descriptions (also shown on the product page). block=terms: show, title, payment_text and delivery_text (shared with the product page, checkout and the bot help). An empty text for a language falls back to the standard one.",
      {"block": S("conditions | terms"), "show": B("Show the block on the home page"), "title": I18N, "new": I18N, "used": I18N, "refresh": I18N, "payment_text": I18N, "delivery_text": I18N}, required=("block",), mutating=True)
async def set_home_block(ctx: Ctx, block: str, show=None, title=None, new=None, used=None, refresh=None, payment_text=None, delivery_text=None):
    if block == "conditions":
        cur = bsvc.clean_conditions(await get_setting(ctx.db, "home_conditions"))
        if show is not None:
            cur["show"] = bool(show)
        if title is not None:
            cur["title"] = i18n(title, cur["title"])
        for key, val in (("new", new), ("used", used), ("refresh", refresh)):
            if val is not None:
                cur["desc"][key] = i18n(val, cur["desc"][key])
        await _setting_row(ctx, "home_conditions", bsvc.clean_conditions(cur))
    elif block == "terms":
        cur = bsvc.clean_terms(await get_setting(ctx.db, "home_terms"))
        if show is not None:
            cur["show"] = bool(show)
        if title is not None:
            cur["title"] = i18n(title, cur["title"])
        await _setting_row(ctx, "home_terms", bsvc.clean_terms(cur))
        for key, val in (("payment_text", payment_text), ("delivery_text", delivery_text)):
            if val is not None:
                await _setting_row(ctx, key, i18n(val, await get_setting(ctx.db, key) or {}))
    else:
        raise ToolError("block: conditions | terms")
    ctx.summary, ctx.entity, ctx.entity_id = f"Home block “{block}” updated", "setting", "home_" + block
    return {"ok": True}


# ---------- auction terms ----------

@tool("get_auction_terms", "The auction terms a customer must read and accept before joining a lot (a bid or a deposit): asked or not, version, heading and text per language (empty = the standard text), how many customers accepted the current version.")
async def get_auction_terms(ctx: Ctx):
    terms = await auction_terms.load(ctx.db)
    return {**terms, "accepted_customers": await auction_terms.accepted_count(ctx.db, terms), "standard_text": {code: t(code, "auction.terms_default") for code in settings.langs}}


@tool("set_auction_terms", "Change the auction terms: show (ask for acceptance or not), heading and text per language (blank lines separate paragraphs; an empty text means the standard one), reaccept=true raises the version so every customer reads and accepts them again.",
      {"show": B("Ask customers to accept the terms before joining"), "title": I18N, "body": I18N, "reaccept": B("Everyone must accept again (the version goes up)")}, mutating=True)
async def set_auction_terms(ctx: Ctx, show=None, title=None, body=None, reaccept=None):
    cur = await auction_terms.load(ctx.db)
    row = await ctx.db.get(Setting, auction_terms.KEY)
    if row is not None:
        ctx.journal.track(row)
    after = await auction_terms.save(ctx.db, show=show, title=i18n(title, cur["title"]) if title is not None else None,
                                     body=i18n(body, cur["body"]) if body is not None else None, reaccept=bool(reaccept))
    if row is None:
        ctx.journal.created(await ctx.db.get(Setting, auction_terms.KEY))
    ctx.summary, ctx.entity, ctx.entity_id = f"Auction terms updated (v{after['version']}" + (", everyone accepts again" if reaccept else "") + ")", "setting", auction_terms.KEY
    return {"ok": True, **after}


# ---------- ad posts ----------

@tool("get_auction_rules", "The common lot rules shown on every lot page unless a lot has its own (payment, disputes): text per language (empty = the standard text), the standard text, how many lots carry their own rules.")
async def get_auction_rules(ctx: Ctx):
    rules = await auction_rules.load(ctx.db)
    return {**rules, "standard": {code: t(code, "auction.rules_default") for code in settings.langs}, "lots_with_own_rules": await auction_rules.own_count(ctx.db)}


@tool("set_auction_rules", "Change the common lot rules (text per language; an empty text means the standard one). A single lot's own rules are set with update_auction (rules; an empty rules object makes it use the common text).",
      {"body": I18N}, required=("body",), mutating=True)
async def set_auction_rules(ctx: Ctx, body):
    current = await auction_rules.load(ctx.db)
    await _setting_row(ctx, auction_rules.KEY, current)
    after = await auction_rules.save(ctx.db, body=i18n(body, current["body"]))
    ctx.summary, ctx.entity, ctx.entity_id = "Common lot rules changed", "setting", auction_rules.KEY
    return {"ok": True, **after}


@tool("get_ad", "One ad post in full.", {"id": I("")}, required=("id",))
async def get_ad(ctx: Ctx, id: int):  # noqa: A002
    p = await need(ctx.db, AdPost, int(id), "ad")
    return {"id": p.id, "title": p.title, "text": p.text, "product_ids": p.product_ids, "target_chat_ids": p.target_chat_ids, "campaign": p.campaign, "status": p.status.value, "clicks": p.clicks, "sent_at": local(p.sent_at)}


@tool("update_ad", "Edit an ad post (an approved one goes back to draft). target_chat_ids are the Telegram chats / channels it is sent to.",
      {"id": I(""), "title": S(""), "text": S(""), "product_ids": ARR("3 to 5 product ids"), "campaign": S(""), "target_chat_ids": ARR("Telegram chat ids")}, required=("id",), mutating=True)
async def update_ad(ctx: Ctx, id: int, title=None, text=None, product_ids=None, campaign=None, target_chat_ids=None):  # noqa: A002
    p = await need(ctx.db, AdPost, int(id), "ad")
    if p.status == AdPostStatus.SENT:
        raise ToolError("a sent post cannot be edited")
    ctx.journal.track(p)
    if title is not None:
        p.title = str(title).strip()[:120]
    if text is not None:
        p.text = str(text).strip()
    if product_ids is not None:
        ids = [int(i) for i in product_ids]
        if not 3 <= len(ids) <= 5:
            raise ToolError("3 to 5 products")
        p.product_ids = ids
    if campaign is not None:
        p.campaign = re.sub(r"[^a-zA-Z0-9_-]", "", str(campaign)) or p.campaign
    if target_chat_ids is not None:
        p.target_chat_ids = [int(i) for i in target_chat_ids]
    if p.status == AdPostStatus.APPROVED:
        p.status = AdPostStatus.DRAFT
    await ctx.db.flush()
    ctx.summary, ctx.entity, ctx.entity_id = f"Ad updated: {p.title}", "ad_post", str(p.id)
    return {"ok": True, "status": p.status.value}


@tool("ad_action", "approve an ad post, or send an approved one to its Telegram chats (sending cannot be undone).", {"id": I(""), "action": S("approve | send")}, required=("id", "action"), mutating=True)
async def ad_action(ctx: Ctx, id: int, action: str):  # noqa: A002
    from app.admin.ads import _products, render_post
    from app.bot.instance import get_bot

    p = await need(ctx.db, AdPost, int(id), "ad")
    ctx.journal.track(p)
    if action == "approve":
        p.status, p.approved_by = AdPostStatus.APPROVED, ctx.staff.id
        ctx.summary = f"Ad approved: {p.title}"
        result = {"ok": True, "status": "approved"}
    elif action == "send":
        if p.status != AdPostStatus.APPROVED:
            raise ToolError("approve the post first")
        if not p.target_chat_ids:
            raise ToolError("the post has no target chats; set target_chat_ids with update_ad")
        bot = get_bot()
        if bot is None:
            raise ToolError("the Telegram bot is off")
        text = render_post(p, await _products(ctx.db, p.product_ids))
        ok, errors = 0, []
        for chat in p.target_chat_ids:
            try:
                await bot.send_message(chat, text, disable_web_page_preview=True)
                ok += 1
            except Exception as e:  # noqa: BLE001
                errors.append(f"{chat}: {str(e)[:120]}")
        if ok:
            p.status, p.sent_at = AdPostStatus.SENT, datetime.now(UTC)
        ctx.summary = f"Ad sent: {p.title} — {ok} ok, {len(errors)} failed"
        result = {"ok": bool(ok), "sent": ok, "errors": errors}
    else:
        raise ToolError("action: approve | send")
    await ctx.db.flush()
    ctx.entity, ctx.entity_id = "ad_post", str(p.id)
    return result


# ---------- auctions: deposits, the winner's order ----------

def _deposit_row(d: AuctionDeposit) -> dict:
    return {"id": d.id, "auction_id": d.auction_id, "user_id": d.user_id, "user": d.user.full_name if d.user else None, "amount": str(d.amount), "currency": d.currency,
            "status": d.status.value, "method": d.method.name if d.method else None, "receipt_url": d.proof_url, "customer_note": d.note, "admin_note": d.admin_note,
            "at": local(d.created_at), "reviewed_at": local(d.reviewed_at)}


@tool("list_deposits", "Auction deposits — the receipts customers sent to join a lot. Without auction_id: every lot, the pending ones (waiting for a check) first; status filters (pending | confirmed | rejected | refunded | applied).",
      {"auction_id": I("One lot only"), "status": S("pending | confirmed | rejected | refunded | applied")})
async def list_deposits(ctx: Ctx, auction_id=None, status=None):
    stmt = select(AuctionDeposit)
    if auction_id:
        stmt = stmt.where(AuctionDeposit.auction_id == int(auction_id))
    if status:
        try:
            stmt = stmt.where(AuctionDeposit.status == DepositStatus(str(status)))
        except ValueError as e:
            raise ToolError("status: pending | confirmed | rejected | refunded | applied") from e
    rows = (await ctx.db.execute(stmt.order_by((AuctionDeposit.status == DepositStatus.PENDING).desc(), AuctionDeposit.id.desc()).limit(200))).scalars().all()
    return {"deposits": [_deposit_row(d) for d in rows], "pending": sum(1 for d in rows if d.status == DepositStatus.PENDING)}


@tool("deposit_action", "The verdict on a deposit receipt: confirm (the customer may bid), reject with a reason (shown to the customer; they may send another receipt), refund, or apply the winner's deposit to the purchase. The customer is notified in Telegram and their open lot page follows at once.",
      {"deposit_id": I(""), "action": S("confirm | reject | refund | apply"), "note": S("The reason (required for reject)"), "auction_id": I("Optional check: the lot the deposit belongs to")}, required=("deposit_id", "action"), mutating=True)
async def deposit_action(ctx: Ctx, deposit_id: int, action: str, note=None, auction_id=None):
    dep = await ctx.db.get(AuctionDeposit, int(deposit_id))
    if dep is None or (auction_id and dep.auction_id != int(auction_id)):
        raise ToolError("deposit not found" + (" on this lot" if auction_id else ""))
    if action not in asvc.REVIEW:
        raise ToolError("action: confirm | reject | refund | apply")
    if action == "reject" and not (note or "").strip():
        raise ToolError("reject needs a note: the reason the customer will read")
    ctx.journal.track(dep)
    before = await asvc.review_deposit(ctx.db, dep, ctx.staff, action, note)
    a = await ctx.db.get(Auction, dep.auction_id)
    ctx.after_commit.append(lambda: asvc.announce_deposit(dep))
    if before != dep.status and dep.status in (DepositStatus.CONFIRMED, DepositStatus.REJECTED, DepositStatus.REFUNDED) and a is not None:
        await notifications.notify_deposit(ctx.db, dep.user, a, dep)
    ctx.summary, ctx.entity, ctx.entity_id = f"Deposit {dep.id} on auction #{dep.auction_id}: {dep.status.value}", "auction", str(dep.auction_id)
    return {"ok": True, "deposit": _deposit_row(dep)}


# ---------- payment methods: how customers pay (QR codes) ----------

@tool("list_payment_methods", "The shop's payment methods (Alipay, WeChat Pay, cards, USDT…): kind, name, account to copy, instructions per language, QR (uploaded picture or generated from qr_text), currency, where shown (deposits / orders), active, order.")
async def list_payment_methods(ctx: Ctx):
    rows = await pm_svc.list_methods(ctx.db, active_only=False)
    return {"methods": [pm_svc.as_dict(m) for m in rows], "kinds": [k.value for k in PaymentMethodKind]}


@tool("save_payment_method", "Create a payment method (no id) or change one (id). kind: alipay | wechat | unionpay | card | bank | usdt | paypal | other. qr_text = a payment link or wallet address the QR is generated from (an uploaded picture, if any, stays unless replaced with set_payment_method_qr). instructions: text per language {uz, uzl, ru, en, zh}.",
      {"id": I("Existing method to change"), "kind": S(""), "name": S("Shown to customers, e.g. Alipay"), "account": S("The number / address / holder to copy"), "qr_text": S("Link or address → generated QR; empty string removes a generated QR"),
       "instructions": I18N, "currency": S("3-letter code the method takes, e.g. CNY; empty = any"), "for_deposits": B("Shown when paying an auction deposit"), "for_orders": B("Shown when paying an order"), "is_active": B("")}, mutating=True)
async def save_payment_method(ctx: Ctx, id=None, kind=None, name=None, account=None, qr_text=None, instructions=None, currency=None, for_deposits=None, for_orders=None, is_active=None):  # noqa: A002
    if id:
        m = await need(ctx.db, PaymentMethod, int(id), "payment method")
        ctx.journal.track(m)
    else:
        if not (name or "").strip():
            raise ToolError("name is required for a new method")
        m = PaymentMethod(kind=PaymentMethodKind.OTHER, name="", instructions={}, for_deposits=True, for_orders=True, is_active=True, sort=await pm_svc.next_sort(ctx.db))
        ctx.db.add(m)
    if kind is not None:
        m.kind = pm_svc.kind_of(kind)
    if name is not None:
        m.name = str(name).strip()[:80] or m.name
    if account is not None:
        m.account = str(account).strip()[:200] or None
    if qr_text is not None:
        m.qr_text = str(qr_text).strip()[:1000] or None
        if m.qr_text and m.qr_filename:
            await pm_svc.clear_qr_picture(m)
    if instructions is not None:
        m.instructions = i18n(instructions, m.instructions or {})
    if currency is not None:
        cur = str(currency).strip().upper()[:3]
        m.currency = cur if cur.isalpha() else None
    for attr, v in (("for_deposits", for_deposits), ("for_orders", for_orders), ("is_active", is_active)):
        if v is not None:
            setattr(m, attr, bool(v))
    await ctx.db.flush()
    if not id:
        ctx.journal.created(m)
    ctx.summary, ctx.entity, ctx.entity_id = f"Payment method {m.name} {'changed' if id else 'created'}", "payment_method", str(m.id)
    return {"ok": True, "method": pm_svc.as_dict(m), "admin_url": f"/admin/payments/{m.id}"}


@tool("set_payment_method_qr", "Give a payment method the QR code from an attached picture (replaces a generated one), or remove its picture.", {"id": I(""), "upload_id": I("Attached picture of the QR"), "remove": B("Remove the QR picture")}, required=("id",), mutating=True)
async def set_payment_method_qr(ctx: Ctx, id: int, upload_id=None, remove=False):  # noqa: A002
    m = await need(ctx.db, PaymentMethod, int(id), "payment method")
    ctx.journal.track(m)
    if remove:
        await pm_svc.clear_qr_picture(m)
    elif upload_id:
        u = (await _uploads(ctx, [upload_id]))[0]
        old = m.qr_filename
        m.qr_filename, m.qr_text = u.filename, None  # the upload's own file becomes the QR picture
        await deletion._rm(old, u.thumb)
        _use(ctx, u)
    else:
        raise ToolError("give upload_id or remove=true")
    await ctx.db.flush()
    ctx.summary, ctx.entity, ctx.entity_id = f"Payment method {m.name}: QR {'removed' if remove else 'set from the attached picture'}", "payment_method", str(m.id)
    return {"ok": True, "method": pm_svc.as_dict(m)}


@tool("delete_payment_method", "Delete a payment method (deposits that named it keep their record).", {"id": I("")}, required=("id",), mutating=True)
async def delete_payment_method(ctx: Ctx, id: int):  # noqa: A002
    m = await need(ctx.db, PaymentMethod, int(id), "payment method")
    name = m.name
    await ctx.journal.deleted(ctx.db, m)
    await pm_svc.delete(ctx.db, m)
    ctx.summary, ctx.entity, ctx.entity_id = f"Payment method {name} deleted", "payment_method", str(id)
    return {"ok": True}


@tool("create_auction_order", "Create the winner's order for an ended lot (the confirmed deposit counts towards it).", {"auction_id": I("")}, required=("auction_id",), mutating=True)
async def create_auction_order(ctx: Ctx, auction_id: int):
    a = await need(ctx.db, Auction, int(auction_id), "auction")
    if a.status != AuctionStatus.ENDED or not a.winner_user_id:
        raise ToolError("the lot has not ended with a winner")
    if a.result_order_id:
        raise ToolError(f"the order already exists: /admin/orders/{a.result_order_id}")
    winner = await ctx.db.get(User, a.winner_user_id)
    ctx.journal.track(a)
    unit = (Decimal(a.current_price_total) / a.qty).quantize(Decimal("0.01"))
    o = Order(number=await osvc.next_order_number(ctx.db), user_id=winner.id, status=OrderStatus.AWAITING_ADVANCE, currency=a.currency, subtotal=a.current_price_total, total=a.current_price_total,
              receiver_name=winner.last_receiver_name or winner.full_name, receiver_phone=winner.last_receiver_phone or winner.phone or "", country=winner.country, city=winner.city,
              address=winner.last_address or "", cargo_code=winner.last_cargo_code, cargo_company=winner.last_cargo_company, admin_note=f"Auction #{a.id} winner", confirmed_at=datetime.now(UTC), source="auction")
    o.items.append(OrderItem(product_id=a.product_id, brand=a.brand, model=a.model, capacity_gb=a.capacity_gb, condition=a.condition, qty=a.qty, unit_price=unit))
    o.history.append(OrderStatusHistory(from_status=None, to_status=OrderStatus.AWAITING_ADVANCE, by_user_id=ctx.staff.id, note=f"auction #{a.id}"))
    o.payments = []
    ctx.db.add(o)
    await ctx.db.flush()
    ctx.journal.created(o)
    a.result_order_id = o.id
    dep = await asvc.user_deposit(ctx.db, a.id, winner.id)
    if dep and dep.status == DepositStatus.CONFIRMED:
        ctx.journal.track(dep)
        dep.status = DepositStatus.APPLIED
        pay = await osvc.add_payment(ctx.db, o, winner, PaymentKind.DEPOSIT, Decimal(dep.amount), "deposit", dep.proof_filename, f"auction deposit #{dep.id}")
        await osvc.confirm_payment(ctx.db, pay, ctx.staff, True, "deposit applied")
    await ctx.db.flush()
    ctx.summary, ctx.entity, ctx.entity_id = f"Order {o.number} created for the winner of auction #{a.id} ({money(o.total, o.currency)})", "order", str(o.id)
    return {"ok": True, "order": order_full(o), "admin_url": f"/admin/orders/{o.id}"}


# ---------- orders: lines and payment records ----------

@tool("delete_order_line", "Remove one line from an order that is still before payment (totals and reserved stock follow; the last line stays).", {"order": S("Order id or number"), "line_id": I("")}, required=("order", "line_id"), mutating=True)
async def delete_order_line(ctx: Ctx, order, line_id: int):
    from app.admin.orders import EDITABLE_ITEMS

    o = await _order(ctx, order)
    it = next((i for i in o.items if i.id == int(line_id)), None)
    if it is None:
        raise ToolError("line not on this order")
    if o.status not in EDITABLE_ITEMS:
        raise ToolError("lines can only change before the payment is confirmed")
    if len(o.items) < 2:
        raise ToolError("an order keeps at least one line; delete the order instead")
    ctx.journal.track(o)
    if it.product_id and (p := await ctx.db.get(Product, it.product_id)):
        ctx.journal.track(p)
    await ctx.journal.deleted(ctx.db, it)
    name = f"{it.brand} {it.model} x{it.qty}"
    await deletion.delete_order_item(ctx.db, o, it)
    ctx.summary, ctx.entity, ctx.entity_id = f"Order {o.number}: line removed — {name}", "order", str(o.id)
    return {"ok": True, "order": order_full(o)}


@tool("payment_action", "On one payment record of an order: confirm or reject a pending one (the customer is notified), or delete a mistyped record.",
      {"order": S("Order id or number"), "payment_id": I(""), "action": S("confirm | reject | delete"), "note": S("")}, required=("order", "payment_id", "action"), mutating=True)
async def payment_action(ctx: Ctx, order, payment_id: int, action: str, note=None):
    o = await _order(ctx, order)
    pay = next((p for p in o.payments if p.id == int(payment_id)), None)
    if pay is None:
        raise ToolError("payment not on this order")
    ctx.journal.track(o)
    if action == "delete":
        await ctx.journal.deleted(ctx.db, pay)
        await deletion.delete_payment(ctx.db, o, pay)
        ctx.summary = f"Order {o.number}: payment record {payment_id} deleted"
    elif action in ("confirm", "reject"):
        if pay.status != PaymentStatus.PENDING:
            raise ToolError("this payment was already processed")
        ctx.journal.track(pay)
        await osvc.confirm_payment(ctx.db, pay, ctx.staff, action == "confirm", note)
        for h in o.history[-1:]:
            ctx.journal.created(h)
        user = o.user

        async def _tell() -> None:
            from app.db import session_scope

            async with session_scope() as db:
                oo, uu = await db.get(Order, o.id), await db.get(User, user.id)
                if oo and uu:
                    await notifications.notify_order_status(db, oo, uu)
        ctx.after_commit.append(_tell)
        ctx.summary = f"Order {o.number}: payment {payment_id} {action}ed"
    else:
        raise ToolError("action: confirm | reject | delete")
    ctx.entity, ctx.entity_id = "order", str(o.id)
    return {"ok": True, "order": order_full(o)}


# ---------- currencies ----------

async def _reload_currencies() -> None:
    from app.db import session_scope
    from app.services import currencies

    async with session_scope() as db:
        await currencies.load(db)


@tool("add_currency", "Add a display currency. rate = units of it for 1 base currency.", {"code": S("3 letters, e.g. UZS"), "name": S(""), "symbol": S(""), "rate": N(""), "symbol_first": B("$40 rather than 40 so'm"), "decimals": I("0–4")}, required=("code", "name", "rate"), mutating=True)
async def add_currency(ctx: Ctx, code: str, name: str, rate, symbol=None, symbol_first=False, decimals=2):
    code = str(code).upper().strip()
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise ToolError("code: three letters")
    if await ctx.db.scalar(select(Currency.id).where(Currency.code == code)):
        raise ToolError("that currency exists")
    r = dec(rate, "rate")
    if r <= 0:
        raise ToolError("rate must be > 0")
    c = Currency(code=code, name=str(name).strip()[:40], symbol=(symbol or code)[:8], symbol_first=bool(symbol_first), rate=r, rate_at=utcnow(), decimals=max(0, min(4, int(decimals or 0))), is_base=False, is_default=False, is_active=True, sort=100)
    ctx.db.add(c)
    await ctx.db.flush()
    ctx.journal.created(c)
    ctx.after_commit.append(_reload_currencies)
    ctx.summary, ctx.entity, ctx.entity_id = f"Currency added: {code} ({r} per base)", "currency", code
    return {"ok": True}


@tool("update_currency", "Change a currency's name, symbol, symbol position or decimals (rate / active / default: set_currency).", {"code": S(""), "name": S(""), "symbol": S(""), "symbol_first": B(""), "decimals": I("")}, required=("code",), mutating=True)
async def update_currency(ctx: Ctx, code: str, name=None, symbol=None, symbol_first=None, decimals=None):
    c = (await ctx.db.execute(select(Currency).where(Currency.code == str(code).upper()))).scalar_one_or_none()
    if c is None:
        raise ToolError(f"currency {code} not found")
    ctx.journal.track(c)
    if name is not None:
        c.name = str(name).strip()[:40]
    if symbol is not None:
        c.symbol = str(symbol).strip()[:8] or c.code
    if symbol_first is not None:
        c.symbol_first = bool(symbol_first)
    if decimals is not None:
        c.decimals = max(0, min(4, int(decimals)))
    await ctx.db.flush()
    ctx.after_commit.append(_reload_currencies)
    ctx.summary, ctx.entity, ctx.entity_id = f"Currency {c.code} updated", "currency", c.code
    return {"ok": True}


@tool("delete_currency", "Delete a currency no product is priced in (never the base one).", {"code": S("")}, required=("code",), mutating=True)
async def delete_currency(ctx: Ctx, code: str):
    c = (await ctx.db.execute(select(Currency).where(Currency.code == str(code).upper()))).scalar_one_or_none()
    if c is None:
        raise ToolError(f"currency {code} not found")
    if c.is_base:
        raise ToolError("the base currency cannot be deleted")
    used = (await ctx.db.execute(select(func.count()).select_from(Product).where(Product.currency == c.code))).scalar_one()
    if used:
        raise ToolError(f"{used} products are priced in {c.code}; switch it off with set_currency instead")
    await ctx.journal.deleted(ctx.db, c)
    await ctx.db.delete(c)
    await ctx.db.flush()
    ctx.after_commit.append(_reload_currencies)
    ctx.summary, ctx.entity, ctx.entity_id = f"Currency deleted: {c.code}", "currency", c.code
    return {"ok": True}


# ---------- countries and cities ----------

@tool("add_country", "Add a delivery country.", {"code": S("2 letters"), "name": I18N, "phone_code": S("+998"), "flag": S("Emoji flag")}, required=("code", "name"), mutating=True)
async def add_country(ctx: Ctx, code: str, name, phone_code=None, flag=None):
    code = str(code).upper().strip()
    if not re.fullmatch(r"[A-Z]{2}", code):
        raise ToolError("code: two letters")
    if await ctx.db.get(Country, code):
        raise ToolError("that country exists")
    c = Country(code=code, name=i18n(name), flag=(flag or "")[:8], phone_code=(phone_code or "")[:8], sort=50, is_active=True)
    ctx.db.add(c)
    await ctx.db.flush()
    ctx.journal.created(c)
    ctx.summary, ctx.entity, ctx.entity_id = f"Country added: {pick(c.name, 'uzl')} ({code})", "country", code
    return {"ok": True}


@tool("update_country", "Change a country's names, phone code, flag or sort.", {"code": S(""), "name": I18N, "phone_code": S(""), "flag": S(""), "sort": I("")}, required=("code",), mutating=True)
async def update_country(ctx: Ctx, code: str, name=None, phone_code=None, flag=None, sort=None):
    c = await need(ctx.db, Country, str(code).upper(), "country")
    ctx.journal.track(c)
    if name is not None:
        c.name = i18n(name, c.name)
    if phone_code is not None:
        c.phone_code = str(phone_code)[:8]
    if flag is not None:
        c.flag = str(flag)[:8]
    if sort is not None:
        c.sort = int(sort)
    await ctx.db.flush()
    ctx.summary, ctx.entity, ctx.entity_id = f"Country {c.code} updated", "country", c.code
    return {"ok": True}


@tool("delete_country", "Delete a delivery country with its cities (customers and orders keep the code as text).", {"code": S("")}, required=("code",), mutating=True)
async def delete_country(ctx: Ctx, code: str):
    c = await need(ctx.db, Country, str(code).upper(), "country")
    await ctx.journal.deleted(ctx.db, c)
    name = pick(c.name, "uzl")
    await ctx.db.delete(c)
    await ctx.db.flush()
    ctx.summary, ctx.entity, ctx.entity_id = f"Country deleted: {name} ({c.code})", "country", c.code
    return {"ok": True}


@tool("update_city", "Change a city's names, region or sort.", {"city_id": I(""), "name": I18N, "region": S("Region / oblast ('' = none)"), "sort": I("")}, required=("city_id",), mutating=True)
async def update_city(ctx: Ctx, city_id: int, name=None, region=None, sort=None):
    c = await need(ctx.db, City, int(city_id), "city")
    ctx.journal.track(c)
    if name is not None:
        c.name = i18n(name, c.name)
    if region is not None:
        c.region = dict.fromkeys(("uz", "uzl", "ru", "en"), str(region).strip()) if str(region).strip() else None
    if sort is not None:
        c.sort = int(sort)
    await ctx.db.flush()
    ctx.summary, ctx.entity, ctx.entity_id = f"City updated: {pick(c.name, 'uzl')}", "city", str(c.id)
    return {"ok": True}


@tool("delete_city", "Delete a delivery city.", {"city_id": I("")}, required=("city_id",), mutating=True)
async def delete_city(ctx: Ctx, city_id: int):
    c = await need(ctx.db, City, int(city_id), "city")
    await ctx.journal.deleted(ctx.db, c)
    name = pick(c.name, "uzl")
    await ctx.db.delete(c)
    await ctx.db.flush()
    ctx.summary, ctx.entity, ctx.entity_id = f"City deleted: {name}", "city", str(city_id)
    return {"ok": True}


# ---------- model dictionary, audit, exports ----------

@tool("update_model", "Correct a dictionary model: name, capacity, interface, form factor or series.", {"id": I(""), "name": S(""), "capacity_gb": I(""), "interface": S("SATA | SAS"), "form_factor": S("3.5 | 2.5"), "series": S("Series name ('' = none)")}, required=("id",), mutating=True)
async def update_model(ctx: Ctx, id: int, name=None, capacity_gb=None, interface=None, form_factor=None, series=None):  # noqa: A002
    m = await need(ctx.db, BrandModel, int(id), "model")
    ctx.journal.track(m)
    if any(v is not None for v in (name, capacity_gb, interface, form_factor)):
        ok = await model_dict.update_model(ctx.db, m, name if name is not None else m.name, capacity_gb if capacity_gb is not None else m.capacity_gb,
                                           (str(interface).upper() if interface is not None else m.interface) or None, (str(form_factor) if form_factor is not None else m.form_factor) or None)
        if not ok:
            raise ToolError("the brand already has a model with that name")
    if series is not None:
        await model_dict.set_series(ctx.db, m, str(series) or None)
    ctx.summary, ctx.entity, ctx.entity_id = f"Dictionary model updated: {m.name}", "brand_model", str(m.id)
    return {"ok": True}


@tool("list_audit", "The audit log: who changed what (newest first).", {"entity": S("Filter: product, order, auction, banner, user, settings…"), "action": S("Filter by action prefix, e.g. product."), "limit": I("Default 20")})
async def list_audit(ctx: Ctx, entity=None, action=None, **kw):
    stmt = select(AuditLog)
    if entity:
        stmt = stmt.where(AuditLog.entity == str(entity))
    if action:
        stmt = stmt.where(AuditLog.action.like(str(action) + "%"))
    rows = (await ctx.db.execute(stmt.order_by(AuditLog.id.desc()).limit(limit(kw.get("limit"))))).scalars().all()
    return {"log": [{"at": local(r.created_at), "actor_id": r.actor_id, "action": r.action, "entity": r.entity, "entity_id": r.entity_id} for r in rows]}


@tool("export_links", "Links to the CSV exports and reports (the staff member opens them in the admin panel).")
async def export_links(ctx: Ctx):
    return {"orders_csv": "/admin/reports/orders.csv", "customers_csv": "/admin/reports/customers.csv", "reports": "/admin/reports", "audit": "/admin/audit"}


def upload_note(items: list[dict]) -> str:
    """What the model is told about pictures attached to a message."""
    return "[Attached pictures: " + "; ".join(f"upload_id={a['id']} ({a.get('name') or 'image'}, {a.get('size') or ''})" for a in items) + "]"


def upload_view(u: AssistantUpload) -> dict:
    return {"id": u.id, "name": u.name, "size": f"{u.width}x{u.height}", "thumb": storage.url(u.thumb), "url": storage.url(u.filename)}


# ---------- customer interests: what they look at, search, cart, order and bid on ----------
def _interest_event(e, products: dict) -> dict:
    p = products.get(e.product_id)
    return {"at": local(e.created_at), "kind": e.kind, "product_id": e.product_id, "product": f"{p.title} {p.capacity_label}" if p else None,
            "brand": e.brand, "model": e.model, "capacity_gb": e.capacity_gb, "condition": e.condition, "qty": e.qty, "query": e.query, "results": e.results}


@tool("customer_interests", "What a customer is interested in, from their own actions in the Mini App: weighted shares of brands, capacities, conditions and purposes (recent signs count more, nothing is forgotten), the price band, the products they keep opening, and their last signs (opened, searched, filtered, carted, ordered, bid, subscribed).",
      {"id": I("Customer id"), "limit": I("Recent signs to list (default 20)")}, required=("id",))
async def customer_interests(ctx: Ctx, id: int, limit: int = 20):  # noqa: A002
    u = await need(ctx.db, User, int(id), "customer")
    events = await interests.events_for(ctx.db, u.id)
    prof = interests.build_profile(events)
    recent = events[: max(1, min(int(limit or 20), 100))]
    ids = set(prof["products"]) | {e.product_id for e in recent if e.product_id}
    products = {p.id: p for p in (await ctx.db.execute(select(Product).where(Product.id.in_(list(ids))))).scalars().unique().all()} if ids else {}
    out = interests.to_json(prof)
    out["products"] = [{"id": pid, "title": f"{products[pid].title} {products[pid].capacity_label}", "score": round(prof["product_scores"][pid], 1), "available": products[pid].available} for pid in prof["products"] if pid in products]
    return {"customer": user_row(u), "profile": out, "recent": [_interest_event(e, products) for e in recent]}


@tool("product_interest", "Who is interested in a product: signs per kind (opened, searched, carted, ordered, bid), distinct customers, and the top customers with their signs.",
      {"id": I("Product id"), "days": I("Only the last N days (default: all time)")}, required=("id",))
async def product_interest(ctx: Ctx, id: int, days: int | None = None):  # noqa: A002
    p = await need(ctx.db, Product, int(id), "product")
    d = await interests.product_interest(ctx.db, p.id, days=int(days) if days else None)
    return {"product": product_row(p), "events": d["events"], "customers": d["customers"], "kinds": d["kinds"],
            "top": [{"customer": user_row(r["user"]), "kinds": r["kinds"], "last_at": local(r["last_at"])} for r in d["top"]]}


@tool("demand_report", "Demand analysis from customers' signs of interest (weighted: opened 1, searched 2, filtered 1.5, carted 5, bid 5, ordered 10): per brand, capacity and brand+capacity with the stock and models behind each (stock 0 with demand = a gap worth filling), per condition and purpose; the most wanted products; the most frequent searches and the ones that found nothing.",
      {"days": I("30 | 90 | 365 | 0 = all time (default 90)")})
async def demand_report(ctx: Ctx, days: int | None = 90):
    d = await interests.demand(ctx.db, days=int(days) if days else None)
    return {"days": d["days"] or "all", "events": d["events"], "customers": d["customers"], "kinds": d["kinds"],
            "brands": d["brands"], "capacities": d["capacities"],
            "brand_capacity": [{"brand": r["value"][0], "capacity_gb": r["value"][1], "score": r["score"], "share": r["share"], "customers": r["customers"], "stock": r["stock"], "models": r["models"]} for r in d["combos"]],
            "conditions": d["conditions"], "purposes": d["purposes"],
            "products": [{"id": r["product"].id, "title": f"{r['product'].title} {r['product'].capacity_label}", "score": r["score"], "customers": r["customers"], "available": r["product"].available} for r in d["products"]],
            "searches": d["searches"], "searches_with_no_result": d["misses"]}


@tool("recommendations_for", "The products the Mini App recommends to a customer right now (the 'For you' rail), best fit first; empty until the customer has shown enough interest.", {"id": I("Customer id")}, required=("id",))
async def recommendations_for(ctx: Ctx, id: int):  # noqa: A002
    u = await need(ctx.db, User, int(id), "customer")
    return [product_row(p) for p in await interests.recommend(ctx.db, u, limit=10)]


# ---------- the shop's look and defaults: the assistant's design hand ----------
@tool("get_defaults", "What a new product form and a new lot form open with (currency, warranties, min order, box, full-box rule, test status, health; lot quantity, hours, step, currency, location).")
async def get_defaults(ctx: Ctx):
    await ui_settings.ensure(ctx.db, force=True)
    return {"product": ui_settings.product_defaults(), "lot": ui_settings.lot_defaults(),
            "notes": "product.currency empty = the shop's main currency; lot.currency empty = the product's; location = a country code from the Geo settings"}


@tool("set_defaults", "Change what new product / lot forms open with. Pass only the fields to change; null puts a field back to the built-in default.",
      {"product": {"type": "object", "description": "currency, seller_warranty_months, factory_warranty_months, min_order, box_qty, full_box_only, test_status (untested|tested|refurbished…), health"},
       "lot": {"type": "object", "description": "currency, qty, hours, step_per_unit, location"}}, mutating=True)
async def set_defaults(ctx: Ctx, product=None, lot=None):
    done = []
    for key, patch, allowed in (("product_defaults", product, ui_settings.PRODUCT_DEFAULTS), ("lot_defaults", lot, ui_settings.LOT_DEFAULTS)):
        if not isinstance(patch, dict) or not patch:
            continue
        unknown = [k for k in patch if k not in allowed]
        if unknown:
            raise ToolError(f"{key}: unknown field(s) {unknown}; allowed: {list(allowed)}")
        cur = dict((await get_setting(ctx.db, key, {})) or {})
        for k, v in patch.items():
            if v is None:
                cur.pop(k, None)
            else:
                cur[k] = v
        if "currency" in cur and cur["currency"]:
            cur["currency"] = str(cur["currency"]).upper()
        await _setting_row(ctx, key, cur)
        done.append(f"{key}: {patch}")
    if not done:
        raise ToolError("product or lot is required")
    ui_settings.invalidate()
    ctx.summary, ctx.entity = "Defaults — " + "; ".join(done), "setting"
    await ui_settings.ensure(ctx.db, force=True)
    return {"ok": True, "product": ui_settings.product_defaults(), "lot": ui_settings.lot_defaults()}


@tool("get_theme", "The look settings of the Mini App and the admin panel: accent colour, corner radius scale, type scale, density — and any custom CSS in place.")
async def get_theme(ctx: Ctx):
    await ui_settings.ensure(ctx.db, force=True)
    return {"theme": ui_settings.theme(), "custom_css": {t: ui_settings.custom_css(t) for t in ui_settings.TARGETS},
            "notes": "accent #rrggbb; radius 0.5–1.6 (1 = as designed); font 0.85–1.25; density compact|normal|comfortable"}


@tool("set_theme", "Change the look of the Mini App or the admin panel: accent colour (#rrggbb), corner radius scale, type scale, density. reset=true puts that target back to the designed look. Tell the staff member what changed; it applies on the next page load.",
      {"target": S("miniapp | admin"), "accent": S("#rrggbb"), "radius": N("0.5–1.6"), "font": N("0.85–1.25"), "density": S("compact | normal | comfortable"), "reset": B("Back to the designed look")}, required=("target",), mutating=True)
async def set_theme(ctx: Ctx, target: str, accent=None, radius=None, font=None, density=None, reset=False):
    if target not in ui_settings.TARGETS:
        raise ToolError("target: miniapp | admin")
    cur = dict((await get_setting(ctx.db, "theme", {})) or {})
    t = {} if reset else dict(cur.get(target) or {})
    for k, v in (("accent", accent), ("radius", radius), ("font", font), ("density", density)):
        if v is not None:
            t[k] = v
    cur[target] = t
    clean = ui_settings.clean_theme(cur)
    if accent and not clean.get(target, {}).get("accent"):
        raise ToolError("accent must be #rrggbb")
    await _setting_row(ctx, "theme", clean)
    ui_settings.invalidate()
    ctx.summary, ctx.entity = f"Theme ({target}): " + ("reset" if reset else ", ".join(f"{k}={v}" for k, v in clean.get(target, {}).items())), "setting"
    return {"ok": True, "theme": clean}


@tool("set_custom_css", "Append or replace free CSS for the Mini App or the admin panel — the way to change the design beyond the theme (colours of parts, spacing, hiding or restyling elements). "
      "This touches the live pages: describe the change and ask the staff member first, then call with confirm=true. Keep it small and specific; an empty css with mode=replace removes it all.",
      {"target": S("miniapp | admin"), "css": S("CSS text"), "mode": S("append | replace (default append)"), "confirm": B("The staff member agreed in this chat")}, required=("target", "css", "confirm"), mutating=True)
async def set_custom_css(ctx: Ctx, target: str, css: str, mode: str = "append", confirm: bool = False):
    if target not in ui_settings.TARGETS:
        raise ToolError("target: miniapp | admin")
    if not confirm and not ctx.approved:
        raise ToolError("ask the staff member first and call again with confirm=true")
    cur = dict((await get_setting(ctx.db, "custom_css", {})) or {})
    new = ui_settings.clean_css(css) if mode == "replace" else ui_settings.clean_css((cur.get(target) or "") + "\n" + (css or ""))
    cur[target] = new
    await _setting_row(ctx, "custom_css", cur)
    ui_settings.invalidate()
    ctx.summary, ctx.entity = f"Custom CSS ({target}): {len(new)} chars", "setting"
    return {"ok": True, "chars": len(new)}


@tool("list_texts", "Find interface strings by a word in their key or text (the Mini App's and the admin panel's locale files, plus the staff's overrides) — to learn the key before set_text.",
      {"query": S("Part of the key or of the text"), "lang": S("Language to search in (default: the staff member's)"), "limit": I("Max rows (default 30)")}, required=("query",))
async def list_texts(ctx: Ctx, query: str, lang=None, limit=30):
    from app.i18n import _load, normalize_lang

    code = normalize_lang(lang or ctx.staff.lang)
    q = (query or "").strip().lower()
    rows = []

    def walk(node, prefix):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{prefix}.{k}" if prefix else k)
        elif isinstance(node, str) and (q in prefix.lower() or q in node.lower()):
            rows.append({"key": prefix, "text": node})
    walk(_load(code), "")
    over = ui_settings._cache["text_overrides"].get(code, {})
    out = [{**r, "overridden": over.get(r["key"])} for r in rows][: max(1, min(int(limit or 30), 100))]
    return {"lang": code, "rows": out, "total": len(rows)}


@tool("set_text", "Change any interface string (the Mini App or the admin panel) in a language — the staff's wording wins over the locale file. "
      "Ask the staff member first and call with confirm=true; an empty text puts the original back. Keep placeholders like {n} that the original has.",
      {"key": S("Dotted key from list_texts"), "lang": S("uz | uzl | ru | en | zh"), "text": S("The new text; empty = back to the original"), "confirm": B("The staff member agreed in this chat")}, required=("key", "lang", "text", "confirm"), mutating=True)
async def set_text(ctx: Ctx, key: str, lang: str, text: str, confirm: bool = False):
    if not confirm and not ctx.approved:
        raise ToolError("ask the staff member first and call again with confirm=true")
    if lang not in settings.langs:
        raise ToolError(f"lang: one of {settings.langs}")
    cur = dict((await get_setting(ctx.db, "text_overrides", {})) or {})
    rows = dict(cur.get(lang) or {})
    if (text or "").strip():
        rows[key] = text
    else:
        rows.pop(key, None)
    cur[lang] = rows
    await _setting_row(ctx, "text_overrides", cur)
    ui_settings.invalidate()
    await ui_settings.ensure(ctx.db, force=True)
    ctx.summary, ctx.entity = f"Text {key} ({lang}): " + (text[:60] if text else "back to the original"), "setting"
    return {"ok": True, "now": t(lang, key)}
