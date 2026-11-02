"""Admin → Assistant: a chat with the model that runs the shop through tools, plus the journal of its changes with undo."""
import json
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select

from app.admin.common import ADMIN, DB, back, f_str, render, staff_dep
from app.admin.router import router
from app.db import session_scope
from app.i18n import t
from app.models import AssistantAction, AssistantChat, User
from app.models.assistant import UNDO_DAYS
from app.models.base import utcnow
from app.services import audit
from app.services.assistant import engine
from app.services.assistant.tools import TOOLS
from app.services.settings_service import get_setting, set_setting

MODELS = ("deepseek-chat", "deepseek-reasoner")
EXAMPLES = 4


def _html(request: Request, staff: User, name: str, ctx: dict) -> str:
    return render(request, staff, name, ctx).body.decode()


async def _chats(db, staff: User) -> list[AssistantChat]:
    return list((await db.execute(select(AssistantChat).where(AssistantChat.staff_id == staff.id).order_by(AssistantChat.updated_at.desc()).limit(60))).scalars().unique().all())


async def _journal(db) -> list[AssistantAction]:
    since = utcnow() - timedelta(days=UNDO_DAYS)
    return list((await db.execute(select(AssistantAction).where(AssistantAction.created_at >= since).order_by(AssistantAction.id.desc()).limit(40))).scalars().all())


def _timeline(chat: AssistantChat, actions: list[AssistantAction]) -> list[tuple[str, object]]:
    """Messages people read (user, assistant with text) and action cards, in time order."""
    items: list[tuple[str, object]] = [("msg", m) for m in chat.messages if m.role == "user" or (m.role == "assistant" and (m.content or "").strip() and m.content != "…")]
    items += [("action", a) for a in actions if a.chat_id == chat.id]
    return sorted(items, key=lambda x: (x[1].created_at, 0 if x[0] == "action" else 1))


async def _ctx(db, request: Request, staff: User, chat: AssistantChat | None) -> dict:
    key, model, base = await engine.config(db)
    chat_actions = list((await db.execute(select(AssistantAction).where(AssistantAction.chat_id == chat.id).order_by(AssistantAction.id))).scalars().all()) if chat else []
    return {
        "page_title": t(staff.lang, "admin.asst.title"), "chats": await _chats(db, staff), "chat": chat, "timeline": _timeline(chat, chat_actions) if chat else [],
        "journal": await _journal(db), "key_set": bool(key), "key_tail": key[-4:] if key else "", "model": model, "base_url": base, "models": MODELS, "undo_days": UNDO_DAYS,
        "tool_count": len(TOOLS), "examples": [t(staff.lang, f"admin.asst.ex{i}") for i in range(1, EXAMPLES + 1)],
    }


@router.get("/assistant")
async def assistant_page(request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    chats = await _chats(db, staff)
    cid = request.query_params.get("chat")
    chat = next((c for c in chats if str(c.id) == cid), None) if cid else (chats[0] if chats else None)
    if chat is None:
        chat = AssistantChat(staff_id=staff.id, title="")
        db.add(chat)
        await db.commit()
        await db.refresh(chat, ["messages"])
    return render(request, staff, "admin/assistant/index.html", await _ctx(db, request, staff, chat))


@router.post("/assistant/new")
async def assistant_new(request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    chats = await _chats(db, staff)
    empty = next((c for c in chats if not c.messages), None)  # an unused chat is reused, not stacked
    if empty is None:
        empty = AssistantChat(staff_id=staff.id, title="")
        db.add(empty)
        await db.commit()
    return back(request, f"/admin/assistant?chat={empty.id}")


@router.post("/assistant/{cid}/delete")
async def assistant_delete(cid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    chat = await db.get(AssistantChat, cid)
    if chat is None or chat.staff_id != staff.id:
        raise HTTPException(404)
    await db.delete(chat)  # its actions stay (chat_id → NULL) so they can still be undone from the journal
    await db.commit()
    return back(request, "/admin/assistant", t(staff.lang, "admin.flash.deleted"))


@router.post("/assistant/{cid}/send")
async def assistant_send(cid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    """NDJSON stream of the turn: status lines while tools run, action cards as they happen, the answer at the end."""
    try:
        payload = await request.json()
    except ValueError:
        payload = {}
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400)
    chat = await db.get(AssistantChat, cid)
    if chat is None or chat.staff_id != staff.id:
        raise HTTPException(404)
    lang = staff.lang

    async def gen():
        def line(d: dict) -> bytes:
            return (json.dumps(d, ensure_ascii=False) + "\n").encode()

        try:
            async with session_scope() as s:
                ch = await s.get(AssistantChat, cid)
                st = await s.get(User, staff.id)
                async for ev in engine.run_turn(s, ch, st, text):
                    if ev["type"] == "status":
                        yield line({"t": "status", "text": t(lang, "admin.asst.running", tool=ev["tool"] or "")})
                    elif ev["type"] == "action":
                        yield line({"t": "action", "id": ev["action"].id, "html": _html(request, staff, "admin/assistant/_action.html", {"a": ev["action"]})})
                    elif ev["type"] == "message":
                        yield line({"t": "message", "html": _html(request, staff, "admin/assistant/_msg.html", {"m": ev["message"]})})
                    elif ev["type"] == "title":
                        yield line({"t": "title", "text": ev["text"]})
                    elif ev["type"] == "error":
                        code = ev["code"]
                        key = {"no_api_key": "error_no_key", "bad_api_key": "error_bad_key", "no_balance": "error_balance", "rate_limited": "error_rate", "too_many_steps": "error_steps", "empty_response": "error_generic"}.get(code)
                        if key is None and code.startswith("network"):
                            key = "error_network"
                        yield line({"t": "error", "code": code, "text": t(lang, f"admin.asst.{key}") if key else t(lang, "admin.asst.error_generic") + f" ({code})"})
        except Exception as e:  # noqa: BLE001
            engine.log.exception("assistant turn failed")
            yield line({"t": "error", "code": "crash", "text": t(lang, "admin.asst.error_generic") + f" ({e.__class__.__name__})"})
        yield line({"t": "done"})

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/assistant/actions")
async def assistant_actions(request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    return render(request, staff, "admin/assistant/_journal.html", {"journal": await _journal(db), "undo_days": UNDO_DAYS})


@router.post("/assistant/actions/{aid}/undo")
async def assistant_undo(aid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    a = await db.get(AssistantAction, aid)
    if a is None:
        raise HTTPException(404)
    ok, note = await engine.undo(db, a, staff)
    if request.headers.get("HX-Request") or "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"ok": ok, "note": note, "html": _html(request, staff, "admin/assistant/_action.html", {"a": a}),
                             "msg": t(staff.lang, "admin.asst.undo_done") if ok else t(staff.lang, "admin.asst.undo_failed", e=note)})
    return back(request, "/admin/assistant", t(staff.lang, "admin.asst.undo_done") if ok else t(staff.lang, "admin.asst.undo_failed", e=note), "ok" if ok else "bad")


@router.post("/assistant/settings")
async def assistant_settings(request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    form = await request.form()
    key = f_str(form, "api_key", maxlen=200)
    model = f_str(form, "model", maxlen=60) or "deepseek-chat"
    base = f_str(form, "base_url", maxlen=200) or "https://api.deepseek.com"
    if key:  # empty = keep the saved one
        await set_setting(db, "assistant_api_key", key)
    if form.get("clear_key"):
        await set_setting(db, "assistant_api_key", "")
    await set_setting(db, "assistant_model", model if model in MODELS or model else "deepseek-chat")
    await set_setting(db, "assistant_base_url", base.rstrip("/"))
    await audit.log(db, staff.id, "assistant.settings", "setting", "assistant", None, {"model": model, "base_url": base, "key": "changed" if key or form.get("clear_key") else "kept"})
    await db.commit()
    await get_setting(db, "assistant_model")
    return back(request, "/admin/assistant", t(staff.lang, "admin.flash.saved"))
