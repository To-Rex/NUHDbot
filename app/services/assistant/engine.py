"""One turn of the admin assistant: the staff message goes to the model with the tool list; every tool call runs
against the database (its own savepoint, so a failing tool leaves nothing behind), mutating ones are written down as
AssistantActions with an undo journal, the results go back to the model, and the loop ends with the model's answer.

With confirmation on (Settings assistant_confirm, the default) a mutating tool call does not run: the calls of one model
reply are held as an AssistantPlan and the turn ends with a card the staff member approves or declines; `resume_plan`
runs (or cancels) them and lets the model continue. A new message while a plan waits counts as a decline.

`run_turn` / `resume_plan` are async generators of events the page renders as they happen:
  {"type": "title", "text"}          the chat got its title (first message)
  {"type": "status", "tool", "args"} a tool is about to run
  {"type": "delta", "text"}          a piece of the answer as it streams in
  {"type": "action", "action"}       a change was made (AssistantAction, committed)
  {"type": "plan", "plan"}           a plan was created or changed (AssistantPlan, committed)
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
from app.models import AssistantAction, AssistantChat, AssistantMessage, AssistantPlan, AssistantUpload, User
from app.models.assistant import UNDO_DAYS
from app.models.base import utcnow
from app.services import audit, deletion, media
from app.services.assistant import journal as jr
from app.services.assistant import llm, providers
from app.services.assistant.tools import TOOLS, Ctx, ToolError, schemas
from app.services.assistant.tools_more import upload_note, upload_view
from app.services.settings_service import get_setting

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
{mode_rules}
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
- Lot rules: one common text shows on every lot page (get_auction_rules / set_auction_rules); a lot may carry its own instead
  (update_auction with rules; an empty rules object puts the common text back).
- Auction deposits: a lot may ask for a deposit (a share of the start price, Settings auction_deposit_percent, or a fixed amount)
  before the first bid. The customer pays by QR with one of the shop's payment methods (list_payment_methods /
  save_payment_method / set_payment_method_qr / delete_payment_method — Alipay, WeChat Pay, cards, USDT…; a QR is an attached
  picture or generated from a link / wallet address) and sends the receipt; list_deposits (all lots or one) shows the receipts
  waiting, deposit_action confirms (the customer may bid), rejects with a reason (they may send another), refunds or applies.
- Customer interests: every sign in the Mini App (a product opened, a search or filter with its result count, a product carted,
  ordered, a bid, a subscription) is kept for good. customer_interests profiles one customer (recent signs count more),
  recommendations_for shows what the Mini App recommends them, product_interest shows who wants a product, demand_report compares
  what customers want (brand, capacity, brand+capacity, the searches that found nothing) with the stock — the way to decide
  which models and capacities to add.
- The look and the defaults are yours too: get_defaults / set_defaults (what new product and lot forms open with — e.g.
  "new products in USD"), get_theme / set_theme (accent colour, corner radius, type size, density of the Mini App or the
  admin panel), set_custom_css (any further design change through CSS) and list_texts / set_text (any interface wording).
  Design and wording changes touch what customers see: {design_ok} Everything is journaled and can be undone.
- Exports (CSV) cannot be produced in the chat: give the link from export_links.
- After acting, report what changed in one or two lines (names, ids, amounts). Mention admin page links as paths like
  /admin/products/12 when useful. Do not repeat the raw tool output.
- If a tool returns an error, say what went wrong and what is needed; do not retry the same call blindly.
"""


CONFIRM_RULES = """- Changes wait for the staff member's OK: a tool call that changes data does not run at once. Every change call you make is shown
  to them as a plan — the calls with their arguments, with Approve and Decline buttons — and runs only when they approve; the
  results then come back to you as usual. So never ask "shall I?" in words and never describe a change instead of making the
  call: look things up with the read tools, then make all the change calls of one task together in one reply, with one or
  two lines saying what the plan does. Put every detail (ids, prices, texts in all languages) into the calls, not into the
  text. If the plan is declined you get cancelled results: ask what should be different, then make a new plan. Each approved
  change is journaled and can be undone by the staff member for {undo_days} days (an Undo button on each one and on the whole
  plan; you can also call undo_action — it waits for approval too)."""
DIRECT_RULES = """- Each change is journaled and can be undone by the staff member for {undo_days} days (they see an Undo button on each action;
  you can also call undo_action). So act directly on clear instructions. Ask one short question only when the request is
  ambiguous (which product? which of two orders?) or when it would delete many records, a customer, an order with payments,
  or a live auction with bids."""


def held(name: str) -> bool:
    """Whether a tool call waits for the staff member's OK in confirmation mode: everything that changes data, and undo."""
    tool = TOOLS.get(name)
    return tool is not None and (tool.mutating or name == "undo_action")


def system_prompt(confirm: bool = True) -> str:
    tz = ZoneInfo(settings.timezone)
    mode = (CONFIRM_RULES if confirm else DIRECT_RULES).format(undo_days=UNDO_DAYS)
    design_ok = ("the plan card is the staff member's OK, so make the call (confirm=true) and explain in a line." if confirm
                 else "say exactly what you will change and wait for the staff member's OK in this chat, then call with confirm=true.")
    return SYSTEM.format(app_name=settings.app_name, undo_days=UNDO_DAYS, currency=settings.default_currency, tz=settings.timezone, now=datetime.now(tz).strftime("%Y-%m-%d %H:%M (%A)"),
                         directions=", ".join(f"{c.value} = {d}" for c, d in COLOR_DIRECTION.items()), mode_rules=mode, design_ok=design_ok)


async def confirm_mode(db: AsyncSession) -> bool:
    return bool(await get_setting(db, "assistant_confirm", True))


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


def call_args(call: dict) -> dict | None:
    """The arguments of a tool call, or None when they are not a JSON object."""
    try:
        args = json.loads((call.get("function") or {}).get("arguments") or "{}")
    except ValueError:
        return None
    return args if isinstance(args, dict) else {}


async def run_tool(db: AsyncSession, chat: AssistantChat, staff: User, call: dict, step: int, *, plan: AssistantPlan | None = None) -> tuple[dict, AssistantAction | None]:
    """Run one tool call inside a savepoint. Returns (result for the model, the recorded action or None).
    Under an approved `plan` the action carries the plan id and the tools that ask for an OK have it."""
    name = (call.get("function") or {}).get("name") or ""
    tool = TOOLS.get(name)
    if tool is None:
        return {"error": f"unknown tool {name}"}, None
    args = call_args(call)
    if args is None:
        return {"error": "arguments are not valid JSON"}, None
    ctx = Ctx(db=db, staff=staff, approved=plan is not None)
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
                                 journal=entries, files=files, status="done", undo_until=utcnow() + timedelta(days=UNDO_DAYS), step=step, plan_id=plan.id if plan else None)
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


def _tool_msg(chat: AssistantChat, call: dict, result: dict) -> AssistantMessage:
    return AssistantMessage(chat_id=chat.id, role="tool", content=_json(result), tool_call_id=call.get("id"), name=(call.get("function") or {}).get("name"))


CANCELLED = {"cancelled": True, "reason": "the staff member did not approve this change; nothing was done"}
SUPERSEDED = {"cancelled": True, "reason": "the staff member sent a new message instead of approving this plan; nothing was done. Read their message and go on from there"}


async def _pending(db: AsyncSession, chat: AssistantChat) -> list[AssistantPlan]:
    return list((await db.execute(select(AssistantPlan).where(AssistantPlan.chat_id == chat.id, AssistantPlan.status == "pending").order_by(AssistantPlan.id))).scalars().all())


async def _decline(db: AsyncSession, chat: AssistantChat, plan: AssistantPlan, note: str) -> None:
    """Tell the model the held calls were not approved; the plan is closed."""
    for call in plan.calls:
        db.add(_tool_msg(chat, call, SUPERSEDED if note == "superseded" else CANCELLED))
    plan.status, plan.note, plan.decided_at = "declined", note, utcnow()
    await db.commit()


async def _loop(db: AsyncSession, chat: AssistantChat, staff: User, cfg, model: str, messages: list[dict], step: int, confirm: bool):
    """The model ↔ tools rounds of one turn, from the current `messages`, until the model answers or a plan waits."""
    tools = schemas()
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
        waiting = []
        for call in calls:
            fn = call.get("function") or {}
            if confirm and held(fn.get("name") or ""):
                waiting.append(call)  # shown to the staff member, run on their OK
                continue
            step += 1
            yield {"type": "status", "tool": fn.get("name"), "args": fn.get("arguments")}
            result, action = await run_tool(db, chat, staff, call, step)
            tm = _tool_msg(chat, call, result)
            db.add(tm)
            await db.commit()
            messages.append(_as_llm(tm))
            if action is not None:
                yield {"type": "action", "action": action}
        if waiting:
            plan = AssistantPlan(chat_id=chat.id, staff_id=staff.id, message_id=am.id, calls=waiting, results=[], status="pending")
            db.add(plan)
            await db.commit()
            await db.refresh(plan, ["actions"])
            yield {"type": "plan", "plan": plan}
            return


async def run_turn(db: AsyncSession, chat: AssistantChat, staff: User, text: str, upload_ids: list[int] | None = None):
    async with _locks[chat.id]:
        cfg, model = await config(db, chat)
        if not cfg.ready:
            yield {"type": "error", "code": "no_api_key", "text": ""}
            return
        confirm = await confirm_mode(db)
        for plan in await _pending(db, chat):  # a new message instead of an answer to the plan: not approved
            await _decline(db, chat, plan, "superseded")
            yield {"type": "plan", "plan": plan}
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
        messages = [{"role": "system", "content": system_prompt(confirm)}, *history(chat)]
        async for ev in _loop(db, chat, staff, cfg, model, messages, 0, confirm):
            yield ev


async def resume_plan(db: AsyncSession, chat: AssistantChat, staff: User, plan: AssistantPlan, approve: bool):
    """The staff member's answer to a plan: run its calls (each journaled under the plan) or cancel them, then let the
    model go on — report, or ask what should be different."""
    async with _locks[chat.id]:
        if plan.status != "pending":
            yield {"type": "error", "code": "plan_closed", "text": ""}
            return
        cfg, model = await config(db, chat)
        if not cfg.ready:
            yield {"type": "error", "code": "no_api_key", "text": ""}
            return
        confirm = await confirm_mode(db)
        if not approve:
            await _decline(db, chat, plan, "staff")
            yield {"type": "plan", "plan": plan}
        else:
            plan.status, plan.decided_at, results = "running", utcnow(), []
            await db.commit()
            yield {"type": "plan", "plan": plan}
            for n, call in enumerate(plan.calls, start=1):
                fn = call.get("function") or {}
                yield {"type": "status", "tool": fn.get("name"), "args": fn.get("arguments")}
                result, action = await run_tool(db, chat, staff, call, n, plan=plan)
                db.add(_tool_msg(chat, call, result))
                results.append({"call_id": call.get("id"), "action_id": action.id if action else None, "error": result.get("error") if isinstance(result, dict) else None})
                plan.results = list(results)
                await db.commit()
                await db.refresh(plan, ["actions"])
                yield {"type": "plan", "plan": plan}
            plan.status = "approved"
            await db.commit()
            yield {"type": "plan", "plan": plan}
        chat.updated_at = utcnow()
        await db.commit()
        await db.refresh(chat, ["messages"])
        messages = [{"role": "system", "content": system_prompt(confirm)}, *history(chat)]
        async for ev in _loop(db, chat, staff, cfg, model, messages, len(plan.calls), confirm):
            yield ev


async def undo_plan(db: AsyncSession, plan: AssistantPlan, staff: User) -> tuple[int, list[str]]:
    """Put a whole approved plan back, last change first. Returns (how many were undone, what could not be)."""
    n, notes = 0, []
    async with _locks[plan.chat_id or 0]:
        for a in reversed(plan.actions):
            if not a.can_undo:
                continue
            ok, note = await undo(db, a, staff, in_turn=True)
            if ok:
                n += 1
            elif note:
                notes.append(note)
        await db.commit()
    return n, notes


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
