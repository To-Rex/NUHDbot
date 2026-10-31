import asyncio
import html
from collections import defaultdict

from fastapi import BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from starlette.datastructures import UploadFile

from app.admin.common import DB, SUPPORT_ROLES, back, f_opt, nav_badges, render, staff_dep
from app.admin.router import router
from app.bot.instance import get_bot
from app.db import session_scope
from app.enums import MessageKind, ThreadStatus
from app.i18n import t
from app.models import SupportThread, User
from app.services import audit, chat_events, media, notifications
from app.services import support as ssvc


async def _threads(db, status: str, user_id: int | None):
    stmt = select(SupportThread)
    if status == "closed":
        stmt = stmt.where(SupportThread.status == ThreadStatus.CLOSED)
    elif status != "all":
        stmt = stmt.where(SupportThread.status == ThreadStatus.OPEN)
    if user_id:
        stmt = stmt.where(SupportThread.user_id == user_id)
    stmt = stmt.order_by(SupportThread.unread_for_staff.desc(), SupportThread.last_message_at.desc().nulls_last()).limit(200)
    return (await db.execute(stmt)).scalars().unique().all()


@router.get("/support")
async def support_list(request: Request, db: DB, staff: User = Depends(staff_dep(*SUPPORT_ROLES))):
    status = request.query_params.get("status") or "open"
    uid = request.query_params.get("user")
    threads = await _threads(db, status, int(uid) if uid and uid.isdigit() else None)
    cur = request.query_params.get("current")
    th = await db.get(SupportThread, int(cur)) if cur and cur.isdigit() else None  # keeps the open thread highlighted on live refresh
    tpl = "admin/support/_list.html" if request.headers.get("HX-Request") else "admin/support/list.html"
    return render(request, staff, tpl, {"page_title": t(staff.lang, "admin.sup.title"), "threads": threads, "status": status, "th": th, "badges": await nav_badges(db)})


@router.get("/support/stream")
async def support_stream(request: Request, db: DB, staff: User = Depends(staff_dep(*SUPPORT_ROLES))):
    """Live events for every thread: the inbox, the open chat and the nav badge react to them."""
    await db.close()  # the stream stays open: give the pooled connection back now
    return chat_events.stream(request, chat_events.STAFF)


@router.get("/support/badge")
async def support_badge(db: DB, staff: User = Depends(staff_dep(*SUPPORT_ROLES))):
    n = (await db.execute(select(func.count()).select_from(SupportThread).where(SupportThread.status == ThreadStatus.OPEN, SupportThread.unread_for_staff > 0))).scalar_one()
    return JSONResponse({"support": n})


@router.get("/support/{tid}")
async def support_thread(tid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*SUPPORT_ROLES))):
    th = await db.get(SupportThread, tid)
    if not th:
        raise HTTPException(404)
    if th.unread_for_staff:
        await ssvc.mark_read(db, th, by_staff=True)
        await db.commit()
    assignee = await db.get(User, th.assigned_to) if th.assigned_to else None
    if request.headers.get("HX-Request") and request.query_params.get("partial") == "messages":
        after = request.query_params.get("after", "")
        if after.isdigit():  # live chat: only what is newer than the last message on screen
            return render(request, staff, "admin/support/_msg_items.html", {"th": th, "items": [m for m in th.messages if m.id > int(after)]})
        return render(request, staff, "admin/support/_messages.html", {"th": th})
    threads = await _threads(db, "open", None)
    if th not in threads:
        threads = [th] + list(threads)
    return render(request, staff, "admin/support/thread.html", {"page_title": th.user.full_name, "th": th, "assignee": assignee, "threads": threads, "status": "open", "badges": await nav_badges(db)})


_tg_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)


async def _telegram_copies(thread_id: int, text: str | None, attachment: str | None, kind: MessageKind) -> None:
    """Telegram copies of a staff reply (notification + the message in the bot chat). Runs after the
    response, so the live chat never waits on the Bot API; one thread's copies keep their order."""
    async with _tg_locks[thread_id], session_scope() as db:
        th = await db.get(SupportThread, thread_id)
        if th is None:
            return
        await notifications.notify_support_reply(db, th.user, th.id, text or "📎")
        bot = get_bot()  # the customer also sees the reply in the bot chat (anonymous "Admin")
        if bot and th.user.tg_id:
            try:
                if attachment and kind == MessageKind.PHOTO:
                    from aiogram.types import BufferedInputFile

                    from app.services import storage

                    blob = await storage.get(attachment)
                    if blob:
                        await bot.send_photo(th.user.tg_id, BufferedInputFile(blob[0], filename=attachment), caption=text or None)
                elif text:
                    await bot.send_message(th.user.tg_id, f"💬 <b>Admin</b>:\n{html.escape(text)}")
            except Exception:  # noqa: BLE001
                pass


@router.post("/support/{tid}/reply")
async def support_reply(tid: int, request: Request, db: DB, background: BackgroundTasks, staff: User = Depends(staff_dep(*SUPPORT_ROLES))):
    th = await db.get(SupportThread, tid)
    if not th:
        raise HTTPException(404)
    form = await request.form()
    text = f_opt(form, "text")
    attachment, kind = None, MessageKind.TEXT
    f = form.get("file")
    if isinstance(f, UploadFile) and f.filename:
        try:
            attachment = await media.save_document(f, prefix=f"sup{th.id}")
            kind = MessageKind.PHOTO if attachment.endswith(".webp") else MessageKind.DOCUMENT
        except media.MediaError:
            attachment = None
    if not text and not attachment:
        return back(request, f"/admin/support/{tid}", t(staff.lang, "admin.required"), "bad")
    msg = await ssvc.add_message(db, th, sender=staff, from_staff=True, text=text, kind=kind, attachment=attachment)
    if not th.assigned_to:
        th.assigned_to = staff.id
    await audit.log(db, staff.id, "support.reply", "thread", th.id, None, {"message": msg.id})
    await db.commit()  # the live chat gets the message now
    background.add_task(_telegram_copies, th.id, text, attachment, kind)
    if request.headers.get("HX-Request"):  # the composer appends just this message (the live stream dedupes by id)
        return render(request, staff, "admin/support/_msg_items.html", {"th": th, "items": [msg]})
    return back(request, f"/admin/support/{tid}", t(staff.lang, "admin.sup.sent"))


@router.post("/support/{tid}/{action}")
async def support_action(tid: int, action: str, request: Request, db: DB, staff: User = Depends(staff_dep(*SUPPORT_ROLES))):
    th = await db.get(SupportThread, tid)
    if not th:
        raise HTTPException(404)
    if action == "close":
        th.status = ThreadStatus.CLOSED
    elif action == "reopen":
        th.status = ThreadStatus.OPEN
    elif action == "assign":
        th.assigned_to = staff.id
    else:
        raise HTTPException(400)
    ssvc.thread_changed(db, th)
    await audit.log(db, staff.id, f"support.{action}", "thread", th.id)
    await db.commit()
    return back(request, f"/admin/support/{tid}", t(staff.lang, "admin.flash.saved"))
