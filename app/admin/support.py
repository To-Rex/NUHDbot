from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from starlette.datastructures import UploadFile

from app.admin.common import DB, SUPPORT_ROLES, back, f_opt, nav_badges, render, staff_dep
from app.admin.router import router
from app.enums import MessageKind, ThreadStatus
from app.i18n import t
from app.models import SupportThread, User
from app.services import audit, media, notifications
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
    tpl = "admin/support/_list.html" if request.headers.get("HX-Request") else "admin/support/list.html"
    return render(request, staff, tpl, {"page_title": t(staff.lang, "admin.sup.title"), "threads": threads, "status": status, "badges": await nav_badges(db)})


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
        return render(request, staff, "admin/support/_messages.html", {"th": th})
    threads = await _threads(db, "open", None)
    if th not in threads:
        threads = [th] + list(threads)
    return render(request, staff, "admin/support/thread.html", {"page_title": th.user.full_name, "th": th, "assignee": assignee, "threads": threads, "status": "open", "badges": await nav_badges(db)})


@router.post("/support/{tid}/reply")
async def support_reply(tid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*SUPPORT_ROLES))):
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
    await notifications.notify_support_reply(db, th.user, th.id, text or "📎")
    # mirror to Telegram chat as well so the customer sees it in the bot (anonymous "Admin")
    bot = __import__("app.bot.instance", fromlist=["get_bot"]).get_bot()
    if bot and th.user.tg_id:
        try:
            if attachment and kind == MessageKind.PHOTO:
                from aiogram.types import FSInputFile

                from app.config import settings as cfg

                await bot.send_photo(th.user.tg_id, FSInputFile(cfg.upload_dir / attachment), caption=text or None)
            elif text:
                await bot.send_message(th.user.tg_id, f"💬 <b>Admin</b>:\n{__import__('html').escape(text)}")
        except Exception:  # noqa: BLE001
            pass
    await audit.log(db, staff.id, "support.reply", "thread", th.id, None, {"message": msg.id})
    await db.commit()
    if request.headers.get("HX-Request"):
        return render(request, staff, "admin/support/_messages.html", {"th": th})
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
    await audit.log(db, staff.id, f"support.{action}", "thread", th.id)
    await db.commit()
    return back(request, f"/admin/support/{tid}", t(staff.lang, "admin.flash.saved"))
