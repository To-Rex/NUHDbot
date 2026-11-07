"""One turn of the admin assistant: the staff message goes to the model with the tool list; every tool call runs
against the database (its own savepoint, so a failing tool leaves nothing behind), mutating ones are written down as
AssistantActions with an undo journal, the results go back to the model, and the loop ends with the model's answer.

`run_turn` is an async generator of events the page renders as they happen:
  {"type": "title", "text"}          the chat got its title (first message)
  {"type": "status", "tool", "args"} a tool is about to run
  {"type": "delta", "text"}          a piece of the answer as it streams in
  {"type": "action", "action"}       a change was made (AssistantAction, committed)
  {"type": "message", "message"}     the assistant's answer (AssistantMessage, committed)
  {"type": "error", "code", "text"}  the turn stopped
"""
import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.enums import COLOR_DIRECTION
from app.models import AssistantAction, AssistantChat, AssistantMessage, AssistantUpload, User
from app.models.assistant import UNDO_DAYS
from app.models.base import utcnow
from app.services import audit, deletion, media
from app.services.assistant import journal as jr
from app.services.assistant import llm, providers
from app.services.assistant.tools import TOOLS, Ctx, ToolError, schemas
from app.services.assistant.tools_more import upload_note, upload_view

log = logging.getLogger("assistant")
MAX_STEPS = 12  # tool rounds per turn
HISTORY_MESSAGES = 60
TOOL_RESULT_CHARS = 8000
_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

SYSTEM = """You are the operations assistant of {app_name}, a Telegram Mini App shop selling new, used and refresh hard drives from China
(Guangzhou) to customers in Uzbekistan and nearby countries. You talk to a staff member in the admin panel and you run the shop
through the tools: products, brands, series, the model dictionary, home slider banners, orders, payments, auctions, customers,
customer chats, staff accounts, settings, currencies, delivery countries/cities, help articles, ad posts and reports.

Rules
- Answer in the language the staff member writes (Uzbek Latin, Uzbek Cyrillic, Russian or English). Be brief and concrete.
- Use the tools for every fact and every change; never invent ids, prices or stock. Look things up before changing them
  (e.g. list_products to find the id, get_order before set_order_status).
- Each change is journaled and can be undone by the staff member for {undo_days} days (they see an Undo button on each action;
  you can also call undo_action). So act directly on clear instructions. Ask one short question only when the request is
  ambiguous (which product? which of two orders?) or when it would delete many records, a customer, an order with payments,
  or a live auction with bids.
- Multilingual text (titles, descriptions, settings): write all five languages yourself — uz (Uzbek Cyrillic), uzl (Uzbek
  Latin), ru, en, zh — translating what the staff member gave you.
- Prices: the catalogue is priced in {currency}. Capacities are in GB (4TB = 4000). Times are in {tz}; now is {now}.
- Directions (catalogue colours): {directions}. Conditions: new, used, refresh. Order flow: new → awaiting_admin (staff
  confirm the offer) → awaiting_advance (payment) → paid (shipping) → shipped; cancelled.
- Pictures: the staff member attaches them with the paperclip; each message then lists them as upload_id=N. Use those ids with
  add_product_images, set_banner_image, set_direction_image, auction_images, set_brand_logo. You cannot see the picture itself —
  go by the file name and what the staff member says; ask which picture goes where when it is not clear. An upload is used once.
- The Mini App home is yours too: get_home_settings shows it; set_home_layout (block order, directions order), set_slider (looks,
  shapes, seconds, automatic slides), set_slider_looks_hidden, set_home_block (Drive conditions, Payment & delivery).
- Auction terms: customers read and accept them before a first bid or deposit (get_auction_terms / set_auction_terms;
  reaccept=true makes everyone accept again).
- Exports (CSV) cannot be produced in the chat: give the link from export_links.
- After acting, report what changed in one or two lines (names, ids, amounts). Mention admin page links as paths like
  /admin/products/12 when useful. Do not repeat the raw tool output.
- If a tool returns an error, say what went wrong and what is needed; do not retry the same call blindly.
"""


def system_prompt() -> str:
    tz = ZoneInfo(settings.timezone)
    return SYSTEM.format(app_name=settings.app_name, undo_days=UNDO_DAYS, currency=settings.default_currency, tz=settings.timezone, now=datetime.now(tz).strftime("%Y-%m-%d %H:%M (%A)"),
                         directions=", ".join(f"{c.value} = {d}" for c, d in COLOR_DIRECTION.items()))


def _as_llm(m: AssistantMessage) -> dict:
    if m.role == "tool":
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content or ""}
    out: dict = {"role": m.role, "content": m.content or ""}
    if m.role == "user" and m.attachments:  # the model works with pictures by their upload ids
        out["content"] = (out["content"] + "\n\n" + upload_note(m.attachments)).strip()
    if m.role == "assistant" and m.tool_calls:
        out["tool_calls"] = m.tool_calls
    return out


def history(chat: AssistantChat) -> list[dict]:
    """The last messages, cut so the window never starts inside a tool exchange."""
    msgs = chat.messages[-HISTORY_MESSAGES:]
    while msgs and msgs[0].role != "user":
        msgs = msgs[1:]
    return [_as_llm(m) for m in msgs]


async def config(db: AsyncSession, chat: AssistantChat | None = None) -> tuple[providers.ProviderConfig, str]:
    """The provider configuration and model a chat talks to (the saved default for a chat without one)."""
    cfgs = await providers.load(db)
    if chat is not None and chat.provider in cfgs and chat.model:
        return cfgs[chat.provider], chat.model
    pid, model = await providers.default_model(db, cfgs)
    return cfgs[pid], model


def _json(v) -> str:
    s = json.dumps(v, ensure_ascii=False, default=str)
    return s if len(s) <= TOOL_RESULT_CHARS else s[:TOOL_RESULT_CHARS] + '…"]} (truncated)'


async def run_tool(db: AsyncSession, chat: AssistantChat, staff: User, call: dict, step: int) -> tuple[dict, AssistantAction | None]:
    """Run one tool call inside a savepoint. Returns (result for the model, the recorded action or None)."""
    name = (call.get("function") or {}).get("name") or ""
    tool = TOOLS.get(name)
    if tool is None:
        return {"error": f"unknown tool {name}"}, None
    try:
        args = json.loads((call.get("function") or {}).get("arguments") or "{}")
        if not isinstance(args, dict):
            args = {}
    except ValueError:
        return {"error": "arguments are not valid JSON"}, None
    ctx = Ctx(db=db, staff=staff)
    files: list[str] = []
    token = deletion.keep_files.set(files) if tool.mutating else None
    try:
        try:
            async with db.begin_nested():
                result = await tool.handler(ctx, **args)
                if tool.mutating:
                    await db.flush()
                    await ctx.journal.settle(db)
        except ToolError as e:
            return {"error": str(e)}, None
        except TypeError as e:  # wrong / missing arguments
            return {"error": f"bad arguments: {e}"}, None
        except Exception as e:  # noqa: BLE001
            log.exception("assistant tool %s failed", name)
            return {"error": f"{e.__class__.__name__}: {str(e)[:300]}"}, None
    finally:
        if token is not None:
            deletion.keep_files.reset(token)
    action = None
    if tool.mutating:
        entries = ctx.journal.entries()
        action = AssistantAction(chat_id=chat.id, staff_id=staff.id, tool=name, args=args, summary=(ctx.summary or name)[:300], entity=ctx.entity, entity_id=ctx.entity_id,
                                 journal=entries, files=files, status="done", undo_until=utcnow() + timedelta(days=UNDO_DAYS), step=step)
        db.add(action)
        await audit.log(db, staff.id, f"assistant.{name}", ctx.entity or "assistant", ctx.entity_id, None, {"summary": action.summary, "args": args})
    await db.commit()
    for fn in ctx.after_commit:
        try:
            r = fn()
            if asyncio.iscoroutine(r):
                await r
        except Exception:  # noqa: BLE001
            log.exception("assistant after-commit hook failed (%s)", name)
    if action is not None:
        result = dict(result) | {"action_id": action.id, "undo": f"undoable until {action.undo_until.astimezone(ZoneInfo(settings.timezone)).strftime('%Y-%m-%d %H:%M')}"}
    return result, action


async def run_turn(db: AsyncSession, chat: AssistantChat, staff: User, text: str, upload_ids: list[int] | None = None):
    async with _locks[chat.id]:
        cfg, model = await config(db, chat)
        if not cfg.ready:
            yield {"type": "error", "code": "no_api_key", "text": ""}
            return
        text = text.strip()
        ups = []
        if upload_ids:
            ups = [u for u in (await db.execute(select(AssistantUpload).where(AssistantUpload.id.in_(upload_ids), AssistantUpload.staff_id == staff.id).order_by(AssistantUpload.id))).scalars().all()]
        db.add(AssistantMessage(chat_id=chat.id, role="user", content=text, attachments=[upload_view(u) for u in ups] or None))
        if not chat.title:
            chat.title = (text[:60].rstrip() + ("…" if len(text) > 60 else "")) or (ups[0].name[:60] if ups else "")
            yield {"type": "title", "text": chat.title}
        chat.updated_at = utcnow()
        await db.commit()
        await db.refresh(chat, ["messages"])
        messages = [{"role": "system", "content": system_prompt()}, *history(chat)]
        tools = schemas()
        step = 0
        while True:
            reply, partial = None, []
            try:
                async for kind, payload in llm.stream(cfg, model, messages, tools):
                    if kind == "delta":
                        partial.append(payload)
                        yield {"type": "delta", "text": payload}
                    else:
                        reply = payload
            except llm.LLMError as e:
                yield {"type": "error", "code": str(e), "text": str(e)}
                return
            except asyncio.CancelledError:  # the staff member pressed Stop or left: keep what already arrived
                if partial:
                    db.add(AssistantMessage(chat_id=chat.id, role="assistant", content="".join(partial), model=model))
                    await db.commit()
                raise
            if reply is None:
                yield {"type": "error", "code": "empty_response", "text": ""}
                return
            calls = reply.get("tool_calls")
            am = AssistantMessage(chat_id=chat.id, role="assistant", content=reply.get("content") or ("" if calls else "…"), tool_calls=calls, model=model)
            db.add(am)
            await db.commit()
            messages.append(_as_llm(am))
            if not calls or step >= MAX_STEPS:
                if calls:
                    yield {"type": "error", "code": "too_many_steps", "text": ""}
                yield {"type": "message", "message": am}
                return
            for call in calls:
                step += 1
                fn = call.get("function") or {}
                yield {"type": "status", "tool": fn.get("name"), "args": fn.get("arguments")}
                result, action = await run_tool(db, chat, staff, call, step)
                tm = AssistantMessage(chat_id=chat.id, role="tool", content=_json(result), tool_call_id=call.get("id"), name=fn.get("name"))
                db.add(tm)
                await db.commit()
                messages.append(_as_llm(tm))
                if action is not None:
                    yield {"type": "action", "action": action}


async def undo(db: AsyncSession, action: AssistantAction, staff: User, *, in_turn: bool = False) -> tuple[bool, str]:
    """Put an action back. Returns (ok, note). From the undo_action tool (`in_turn`) the turn already holds the chat
    lock and commits after the tool, so neither happens here."""
    if action.status != "done":
        return False, "already undone"
    if action.undo_until < utcnow():
        return False, "undo window closed"
    if not action.journal:
        return False, "nothing to put back"

    async def work() -> tuple[bool, str]:
        try:
            async with db.begin_nested():
                notes = await jr.undo(db, action.journal)
        except Exception as e:  # noqa: BLE001
            log.exception("assistant undo %s failed", action.id)
            return False, f"{e.__class__.__name__}: {str(e)[:200]}"
        action.status, action.undone_at, action.note = "undone", utcnow(), "; ".join(notes) or None
        await audit.log(db, staff.id, "assistant.undo", action.entity or "assistant", action.entity_id, {"summary": action.summary}, {"notes": notes})
        if not in_turn:
            await db.commit()
        return True, "; ".join(notes)

    if in_turn:
        return await work()
    async with _locks[action.chat_id or 0]:
        return await work()


async def purge_files(db: AsyncSession) -> int:
    """Files freed by assistant deletions whose undo window has closed (an undone deletion keeps its files)."""
    rows = (await db.execute(select(AssistantAction).where(AssistantAction.undo_until < utcnow(), func.json_array_length(AssistantAction.files) > 0))).scalars().all()
    n = 0
    for a in rows:
        if a.status == "done":
            await media.delete_files(*a.files)
            n += len(a.files)
        a.files = []
    if rows:
        await db.commit()
    return n


async def purge_uploads(db: AsyncSession) -> int:
    """Pictures attached in the chat and never used, older than the undo window: the rows and their files."""
    old = utcnow() - timedelta(days=UNDO_DAYS)
    rows = (await db.execute(select(AssistantUpload).where(AssistantUpload.used.is_(False), AssistantUpload.created_at < old))).scalars().all()
    for u in rows:
        await media.delete_files(u.filename, u.thumb)
        await db.delete(u)
    if rows:
        await db.commit()
    return len(rows)
