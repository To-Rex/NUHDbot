from fastapi import Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

from app.deps import DB, Lang, redirect, require_user
from app.enums import MessageKind
from app.i18n import t
from app.models import Order, Product, SupportMessage, User
from app.services.media import ALLOWED_TYPES, MediaError, save_document
from app.services.settings_service import get_setting
from app.services.support import add_message, get_or_create_thread, mark_read, user_threads
from app.templating import render
from app.web.common import hx_trigger, toast
from app.web.router import router


async def _thread_for(db, thread_id: int, user: User):
    from app.models import SupportThread

    th = await db.get(SupportThread, thread_id)
    return th if th and th.user_id == user.id else None


@router.get("/support")
async def support_list(request: Request, db: DB, lang: Lang, user: User = Depends(require_user)):
    threads = await user_threads(db, user.id)
    return render(request, "miniapp/support_list.html", {"lang": lang, "threads": threads, "working_hours": await get_setting(db, "working_hours"), "reply_time": await get_setting(db, "reply_time"), "page_title": t(lang, "support.title"), "back_url": "/app/profile"})


@router.get("/support/new")
async def support_new(request: Request, db: DB, lang: Lang, user: User = Depends(require_user), order_id: int | None = None, product_id: int | None = None):
    order = await db.get(Order, order_id) if order_id else None
    if order is not None and order.user_id != user.id:
        order = None
    product = await db.get(Product, product_id) if product_id else None
    return render(request, "miniapp/support_new.html", {"lang": lang, "order": order, "product": product, "page_title": t(lang, "support.new"), "back_url": "/app/support", "working_hours": await get_setting(db, "working_hours"), "reply_time": await get_setting(db, "reply_time")})


async def _store_attachment(file: UploadFile | None):
    if not file or not file.filename:
        return None, MessageKind.TEXT
    name = await save_document(file, prefix="sup")
    kind = MessageKind.PHOTO if file.content_type in ALLOWED_TYPES else MessageKind.DOCUMENT
    return name, kind


@router.post("/support/new")
async def support_create(request: Request, db: DB, lang: Lang, user: User = Depends(require_user), text: str = Form(""), order_id: int | None = Form(None), product_id: int | None = Form(None), attachment: UploadFile | None = File(None)):
    text = text.strip()
    if product_id and not order_id:
        p = await db.get(Product, product_id)
        if p is not None:
            text = f"[{p.brand} {p.model} {p.capacity_label} · #{p.id}]\n{text}".strip()
    if not text and not (attachment and attachment.filename):
        return toast(redirect(request, request.headers.get("referer") or "/app/support/new"), t(lang, "support.errors.empty"), "bad", "error")
    try:
        att, kind = await _store_attachment(attachment)
    except MediaError:
        return toast(redirect(request, "/app/support/new"), t(lang, "support.errors.file"), "bad", "error")
    th = await get_or_create_thread(db, user, order_id)
    if order_id and not th.subject:
        o = await db.get(Order, order_id)
        th.subject = o.number if o else None
    await add_message(db, th, sender=user, from_staff=False, text=text, kind=kind, attachment=att)
    await db.commit()
    return hx_trigger(redirect(request, f"/app/support/{th.id}"), toast={"msg": t(lang, "support.sent"), "type": "ok"}, haptic="success")


@router.get("/support/{thread_id}")
async def support_thread(thread_id: int, request: Request, db: DB, lang: Lang, user: User = Depends(require_user)):
    th = await _thread_for(db, thread_id, user)
    if th is None:
        return redirect(request, "/app/support")
    await mark_read(db, th, by_staff=False)
    await db.commit()
    title = t(lang, "support.about_order", number=th.order.number) if th.order else t(lang, "support.general")
    return render(request, "miniapp/support_thread.html", {"lang": lang, "th": th, "messages": th.messages, "page_title": title, "back_url": "/app/support", "hide_nav": True, "working_hours": await get_setting(db, "working_hours"), "reply_time": await get_setting(db, "reply_time")})


@router.get("/support/{thread_id}/messages")
async def support_messages(thread_id: int, request: Request, db: DB, lang: Lang, user: User = Depends(require_user), after: int = 0):
    th = await _thread_for(db, thread_id, user)
    if th is None:
        return HTMLResponse("", status_code=404)
    new = [m for m in th.messages if m.id > after]
    if new:
        await mark_read(db, th, by_staff=False)
        await db.commit()
    return render(request, "miniapp/partials/messages.html", {"lang": lang, "th": th, "messages": new})


@router.post("/support/{thread_id}/send")
async def support_send(thread_id: int, request: Request, db: DB, lang: Lang, user: User = Depends(require_user), text: str = Form(""), attachment: UploadFile | None = File(None)):
    th = await _thread_for(db, thread_id, user)
    if th is None:
        return HTMLResponse("", status_code=404)
    text = text.strip()
    if not text and not (attachment and attachment.filename):
        return toast(HTMLResponse("", status_code=422), t(lang, "support.errors.empty"), "bad", "error")
    try:
        att, kind = await _store_attachment(attachment)
    except MediaError:
        return toast(HTMLResponse("", status_code=422), t(lang, "support.errors.file"), "bad", "error")
    msg = await add_message(db, th, sender=user, from_staff=False, text=text, kind=kind, attachment=att)
    await db.commit()
    resp = render(request, "miniapp/partials/messages.html", {"lang": lang, "th": th, "messages": [msg]})
    return hx_trigger(resp, haptic="light", messageSent=True)


def _is_image(m: SupportMessage) -> bool:
    return m.kind == MessageKind.PHOTO
