"""Admin → Assistant: a chat with the model that runs the shop through tools, plus the journal of its changes with undo."""
import json
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import select
from starlette.datastructures import UploadFile

from app.admin.common import ADMIN, DB, back, f_str, render, staff_dep
from app.admin.router import router
from app.db import session_scope
from app.i18n import t
from app.models import AssistantAction, AssistantChat, AssistantUpload, User
from app.models.assistant import UNDO_DAYS
from app.models.base import utcnow
from app.services import audit, media
from app.services.assistant import engine, providers
from app.services.assistant.tools import TOOLS
from app.services.assistant.tools_more import upload_view
from app.services.settings_service import set_setting

EXAMPLES = 6
MAX_UPLOADS = 10  # pictures per message
ERROR_KEYS = {"no_api_key": "error_no_key", "bad_api_key": "error_bad_key", "no_balance": "error_balance", "rate_limited": "error_rate", "too_many_steps": "error_steps",
              "empty_response": "error_generic", "no_model": "error_no_model"}


def _html(request: Request, staff: User, name: str, ctx: dict) -> str:
    return render(request, staff, name, ctx).body.decode()


async def _chats(db, staff: User) -> list[AssistantChat]:
    return list((await db.execute(select(AssistantChat).where(AssistantChat.staff_id == staff.id).order_by(AssistantChat.updated_at.desc()).limit(80))).scalars().unique().all())


async def _journal(db) -> list[AssistantAction]:
    since = utcnow() - timedelta(days=UNDO_DAYS)
    return list((await db.execute(select(AssistantAction).where(AssistantAction.created_at >= since).order_by(AssistantAction.id.desc()).limit(60))).scalars().all())


def _timeline(chat: AssistantChat, actions: list[AssistantAction]) -> list[tuple[str, object]]:
    """Messages people read (user, assistant with text) and action cards, in time order."""
    items: list[tuple[str, object]] = [("msg", m) for m in chat.messages if m.role == "user" or (m.role == "assistant" and (m.content or "").strip() and m.content != "…")]
    items += [("action", a) for a in actions if a.chat_id == chat.id]
    return sorted(items, key=lambda x: (x[1].created_at, 0 if x[0] == "action" else 1))


def _groups(chats: list[AssistantChat], lang: str) -> list[tuple[str, list[AssistantChat]]]:
    """Today / yesterday / last 7 days / older, like the chat apps do."""
    now = utcnow()
    buckets: dict[str, list[AssistantChat]] = {}
    for c in chats:
        age = (now - c.updated_at).days if c.updated_at else 99
        key = "today" if age < 1 and c.updated_at.date() == now.date() else ("yesterday" if age < 2 else ("week" if age < 7 else "older"))
        buckets.setdefault(key, []).append(c)
    return [(t(lang, f"admin.asst.g_{k}"), buckets[k]) for k in ("today", "yesterday", "week", "older") if buckets.get(k)]


async def _ctx(db, request: Request, staff: User, chat: AssistantChat) -> dict:
    cfgs = await providers.load(db)
    if chat.provider not in cfgs:
        chat.provider, chat.model = await providers.default_model(db, cfgs)
    cfg = cfgs[chat.provider]
    chat_actions = list((await db.execute(select(AssistantAction).where(AssistantAction.chat_id == chat.id).order_by(AssistantAction.id))).scalars().all())
    journal = await _journal(db)
    chats = await _chats(db, staff)
    default = await providers.default_model(db, cfgs)
    return {
        "page_title": t(staff.lang, "admin.asst.title"), "chats": chats, "groups": _groups(chats, staff.lang), "chat": chat, "timeline": _timeline(chat, chat_actions),
        "journal": journal, "undoable": sum(1 for a in journal if a.can_undo), "undo_days": UNDO_DAYS, "tool_count": len(TOOLS),
        "providers": list(providers.PROVIDERS.values()), "cfgs": cfgs, "ready": [c.provider.id for c in cfgs.values() if c.ready], "cfg": cfg, "key_set": cfg.ready,
        "default_model": f"{default[0]}:{default[1]}", "examples": [t(staff.lang, f"admin.asst.ex{i}") for i in range(1, EXAMPLES + 1)], "first_name": staff.first_name or staff.full_name,
    }


async def _own_chat(db, staff: User, cid: int) -> AssistantChat:
    chat = await db.get(AssistantChat, cid)
    if chat is None or chat.staff_id != staff.id:
        raise HTTPException(404)
    return chat


@router.get("/assistant")
async def assistant_page(request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    chats = await _chats(db, staff)
    cid = request.query_params.get("chat")
    chat = next((c for c in chats if str(c.id) == cid), None) if cid else (chats[0] if chats else None)
    if chat is None:
        cfgs = await providers.load(db)
        pid, model = await providers.default_model(db, cfgs)
        chat = AssistantChat(staff_id=staff.id, title="", provider=pid, model=model)
        db.add(chat)
        await db.commit()
        await db.refresh(chat, ["messages"])
    ctx = await _ctx(db, request, staff, chat)
    await db.commit()
    return render(request, staff, "admin/assistant/index.html", ctx)


@router.post("/assistant/new")
async def assistant_new(request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    chats = await _chats(db, staff)
    empty = next((c for c in chats if not c.messages), None)  # an unused chat is reused, not stacked
    if empty is None:
        cfgs = await providers.load(db)
        pid, model = await providers.default_model(db, cfgs)
        empty = AssistantChat(staff_id=staff.id, title="", provider=pid, model=model)
        db.add(empty)
        await db.commit()
    return back(request, f"/admin/assistant?chat={empty.id}")


@router.post("/assistant/{cid}/delete")
async def assistant_delete(cid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    chat = await _own_chat(db, staff, cid)
    await db.delete(chat)  # its actions stay (chat_id → NULL) so they can still be undone from the journal
    await db.commit()
    return back(request, "/admin/assistant", t(staff.lang, "admin.flash.deleted"))


@router.post("/assistant/{cid}/rename")
async def assistant_rename(cid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    chat = await _own_chat(db, staff, cid)
    data = await request.json()
    chat.title = str(data.get("title") or "").strip()[:120]
    await db.commit()
    return JSONResponse({"ok": True, "title": chat.title})


@router.post("/assistant/{cid}/model")
async def assistant_model(cid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    """Switch the chat to another provider / model; `default` also makes it the default for new chats."""
    chat = await _own_chat(db, staff, cid)
    data = await request.json()
    pid, model = str(data.get("provider") or ""), str(data.get("model") or "").strip()[:120]
    if pid not in providers.PROVIDERS or not model:
        raise HTTPException(400)
    chat.provider, chat.model = pid, model
    if data.get("default"):
        await set_setting(db, "assistant_default_model", f"{pid}:{model}")
    await db.commit()
    return JSONResponse({"ok": True, "provider": pid, "model": model, "provider_name": providers.PROVIDERS[pid].name})


@router.get("/assistant/models")
async def assistant_models(request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    """Model ids per configured provider (live lists, cached), for the picker."""
    cfgs = await providers.load(db)
    force = request.query_params.get("refresh") == "1"
    only = request.query_params.get("provider")
    out = []
    for pid, cfg in cfgs.items():
        if only and pid != only:
            continue
        if not cfg.ready:
            continue
        ids, err = await providers.list_models(cfg, force=force)
        out.append({"id": pid, "name": cfg.provider.name, "models": ids, "error": err})
    return JSONResponse({"providers": out})


@router.post("/assistant/{cid}/send")
async def assistant_send(cid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    """NDJSON stream of the turn: status lines while tools run, action cards as they happen, the answer as it streams."""
    try:
        payload = await request.json()
    except ValueError:
        payload = {}
    text = str(payload.get("text") or "").strip()
    upload_ids = [int(x) for x in (payload.get("uploads") or []) if str(x).isdigit()][:MAX_UPLOADS]
    if not text and not upload_ids:
        raise HTTPException(400)
    await _own_chat(db, staff, cid)
    lang = staff.lang

    async def gen():
        def line(d: dict) -> bytes:
            return (json.dumps(d, ensure_ascii=False) + "\n").encode()

        try:
            async with session_scope() as s:
                ch = await s.get(AssistantChat, cid)
                st = await s.get(User, staff.id)
                async for ev in engine.run_turn(s, ch, st, text, upload_ids):
                    if ev["type"] == "status":
                        yield line({"t": "status", "text": t(lang, "admin.asst.running", tool=ev["tool"] or "")})
                    elif ev["type"] == "delta":
                        yield line({"t": "delta", "text": ev["text"]})
                    elif ev["type"] == "action":
                        yield line({"t": "action", "id": ev["action"].id, "html": _html(request, staff, "admin/assistant/_action.html", {"a": ev["action"]})})
                    elif ev["type"] == "message":
                        yield line({"t": "message", "html": _html(request, staff, "admin/assistant/_msg.html", {"m": ev["message"]})})
                    elif ev["type"] == "title":
                        yield line({"t": "title", "text": ev["text"]})
                    elif ev["type"] == "error":
                        code = ev["code"]
                        key = ERROR_KEYS.get(code) or ("error_network" if code.startswith("network") else None)
                        yield line({"t": "error", "code": code, "text": t(lang, f"admin.asst.{key}") if key else t(lang, "admin.asst.error_generic") + f" ({code})"})
        except Exception as e:  # noqa: BLE001
            engine.log.exception("assistant turn failed")
            yield line({"t": "error", "code": "crash", "text": t(lang, "admin.asst.error_generic") + f" ({e.__class__.__name__})"})
        yield line({"t": "done"})

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/assistant/{cid}/upload")
async def assistant_upload(cid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    """Pictures attached in the chat: converted and stored now, named to the model by id with the next message."""
    await _own_chat(db, staff, cid)
    form = await request.form()
    files = [f for f in form.getlist("files") if isinstance(f, UploadFile) and f.filename][:MAX_UPLOADS]
    out, errors = [], []
    for f in files:
        try:
            meta = await media.save_image(f, prefix="ai")
        except media.MediaError as e:
            errors.append(f"{f.filename}: {t(staff.lang, 'admin.asst.upload_' + ('too_large' if str(e) == 'too_large' else 'bad_type'))}")
            continue
        u = AssistantUpload(chat_id=cid, staff_id=staff.id, filename=meta["filename"], thumb=meta["thumb"], width=meta["width"], height=meta["height"], name=(f.filename or "image")[:160])
        db.add(u)
        await db.flush()
        out.append(upload_view(u))
    await db.commit()
    return JSONResponse({"uploads": out, "errors": errors})


@router.get("/assistant/actions")
async def assistant_actions(request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    journal = await _journal(db)
    return render(request, staff, "admin/assistant/_journal.html", {"journal": journal, "undo_days": UNDO_DAYS, "undoable": sum(1 for a in journal if a.can_undo)})


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
    """Keys per provider (empty field = keep, tick = remove), custom base URL, and the default model."""
    form = await request.form()
    cfgs = await providers.load(db)
    saved = {}
    changed = []
    for pid, cfg in cfgs.items():
        key = f_str(form, f"key_{pid}", maxlen=300)
        if form.get(f"clear_{pid}"):
            key, changed = "", changed + [pid]
        elif key:
            changed.append(pid)
        else:
            key = cfg.key
        base = f_str(form, f"base_{pid}", maxlen=300).rstrip("/") if pid == "custom" else ""
        if key or base:
            saved[pid] = {"key": key, "base_url": base}
    await providers.save(db, saved)
    default = f_str(form, "default_model", maxlen=160)
    if ":" in default:
        await set_setting(db, "assistant_default_model", default)
    await audit.log(db, staff.id, "assistant.settings", "setting", "assistant", None, {"keys_changed": changed, "default_model": default})
    await db.commit()
    return back(request, "/admin/assistant", t(staff.lang, "admin.flash.saved"))


@router.post("/assistant/settings/test")
async def assistant_settings_test(request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    """Try a key before saving it: lists the provider's models with it."""
    data = await request.json()
    pid = str(data.get("provider") or "")
    if pid not in providers.PROVIDERS:
        raise HTTPException(400)
    cfgs = await providers.load(db)
    cfg = cfgs[pid]
    key = str(data.get("key") or "").strip() or cfg.key
    base = (str(data.get("base_url") or "").strip() or cfg.base_url).rstrip("/")
    test = providers.ProviderConfig(cfg.provider, key, base)
    if not test.ready:
        return JSONResponse({"ok": False, "error": t(staff.lang, "admin.asst.error_no_key")})
    ids, err = await providers.list_models(test, force=True)
    return JSONResponse({"ok": err is None, "models": ids[:200], "count": len(ids), "error": err})
