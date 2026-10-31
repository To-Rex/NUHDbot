from fastapi import Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

from app.deps import DB, Lang, redirect, require_user
from app.enums import MessageKind
from app.i18n import t
from app.models import Order, Product, SupportMessage, User
from app.services import chat_events
from app.services.media import ALLOWED_TYPES, MediaError, save_document
from app.services.settings_service import get_setting
from app.services.support import add_message, get_or_create_thread, mark_read, user_thread
from app.templating import render
from app.web.common import hx_trigger, toast
from app.web.router import router


async def _thread_for(db, thread_id: int, user: User):
    from app.models import SupportThread

    th = await db.get(SupportThread, thread_id)
    return th if th and th.user_id == user.id else None


@router.get("/chat")
async def chat_tab(request: Request, db: DB, lang: Lang, user: User = Depends(require_user)):
    """The Chat tab: the customer's one conversation with the admin and the message box — nothing to pick first."""
    th = await user_thread(db, user.id)
    if th is not None:
        await mark_read(db, th, by_staff=False)
        await db.commit()
    request.state.chat_unread = 0  # read now
    return render(request, "miniapp/chat.html", {
        "lang": lang, "th": th, "messages": th.messages if th else [], "page_title": t(lang, "chat.title"),
        "working_hours": await get_setting(db, "working_hours"), "reply_time": await get_setting(db, "reply_time"),
    })


@router.post("/chat/send")
async def chat_send(request: Request, db: DB, lang: Lang, user: User = Depends(require_user), text: str = Form(""), attachment: UploadFile | None = File(None)):
    """The first message from the Chat tab: starts (or reopens) the conversation; X-Thread tells the page which one to follow live."""
    text = text.strip()
    if not text and not (attachment and attachment.filename):
        return toast(HTMLResponse("", status_code=422), t(lang, "support.errors.empty"), "bad", "error")
    try:
        att, kind = await _store_attachment(attachment)
    except MediaError:
        return toast(HTMLResponse("", status_code=422), t(lang, "support.errors.file"), "bad", "error")
    th = await get_or_create_thread(db, user)
    msg = await add_message(db, th, sender=user, from_staff=False, text=text, kind=kind, attachment=att)
    await db.commit()
    await db.refresh(th, ["messages"])  # a thread made just now: the bubbles' read ticks look at its messages
    resp = render(request, "miniapp/partials/messages.html", {"lang": lang, "th": th, "messages": [msg]}, headers={"X-Thread": str(th.id)})
    return hx_trigger(resp, haptic="light", messageSent=True)


@router.get("/support")
async def support_list(request: Request, user: User = Depends(require_user)):
    """There is one conversation with the admin: it lives in the Chat tab."""
    return redirect(request, "/app/chat")


@router.get("/support/new")
async def support_new(request: Request, db: DB, lang: Lang, user: User = Depends(require_user), order_id: int | None = None, product_id: int | None = None):
    order = await db.get(Order, order_id) if order_id else None
    if order is not None and order.user_id != user.id:
        order = None
    product = await db.get(Product, product_id) if product_id else None
    return render(request, "miniapp/support_new.html", {"lang": lang, "order": order, "product": product, "page_title": t(lang, "support.new"), "back_url": f"/app/products/{product.id}" if product else (f"/app/orders/{order.id}" if order else "/app/chat"), "working_hours": await get_setting(db, "working_hours"), "reply_time": await get_setting(db, "reply_time")})


async def _store_attachment(file: UploadFile | None):
    if not file or not file.filename:
        return None, MessageKind.TEXT
    name = await save_document(file, prefix="sup")
    kind = MessageKind.PHOTO if file.content_type in ALLOWED_TYPES else MessageKind.DOCUMENT
    return name, kind


@router.post("/support/new")
async def support_create(request: Request, db: DB, lang: Lang, user: User = Depends(require_user), text: str = Form(""), order_id: int | None = Form(None), product_id: int | None = Form(None), attachment: UploadFile | None = File(None)):
    text = text.strip()
    order = await db.get(Order, order_id) if order_id else None
    if order is not None and order.user_id != user.id:
        order = None
    if order is not None:  # the one conversation, with the order named at the top of the message
        text = f"[{order.number}]\n{text}".strip()
    elif product_id:
        p = await db.get(Product, product_id)
        if p is not None:
            text = f"[{p.brand} {p.model} {p.capacity_label} · #{p.id}]\n{text}".strip()
    if not text and not (attachment and attachment.filename):
        return toast(redirect(request, request.headers.get("referer") or "/app/support/new"), t(lang, "support.errors.empty"), "bad", "error")
    try:
        att, kind = await _store_attachment(attachment)
    except MediaError:
        return toast(redirect(request, "/app/support/new"), t(lang, "support.errors.file"), "bad", "error")
    th = await get_or_create_thread(db, user, order.id if order else None)
    await add_message(db, th, sender=user, from_staff=False, text=text, kind=kind, attachment=att)
    await db.commit()
    return hx_trigger(redirect(request, "/app/chat"), toast={"msg": t(lang, "support.sent"), "type": "ok"}, haptic="success")


@router.get("/support/{thread_id}")
async def support_thread(thread_id: int, request: Request, user: User = Depends(require_user)):
    """Old links (bot notifications) to a conversation: there is one, in the Chat tab."""
    return redirect(request, "/app/chat")


@router.get("/support/{thread_id}/stream")
async def support_stream(thread_id: int, request: Request, db: DB, user: User = Depends(require_user)):
    th = await _thread_for(db, thread_id, user)
    if th is None:
        return HTMLResponse("", status_code=404)
    await db.close()  # the stream may stay open for hours: give the pooled connection back now
    return chat_events.stream(request, chat_events.thread_channel(thread_id))


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
    await db.refresh(th, ["messages"])  # with the new message in the list its tick says "sent", not "read"
    resp = render(request, "miniapp/partials/messages.html", {"lang": lang, "th": th, "messages": [msg]})
    return hx_trigger(resp, haptic="light", messageSent=True)


def _is_image(m: SupportMessage) -> bool:
    return m.kind == MessageKind.PHOTO
