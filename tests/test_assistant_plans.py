"""The assistant asks before it acts: mutating calls become a plan, Approve runs them (undoable one by one or all together),
Decline or a new message tells the model, and confirmation mode off keeps the old act-at-once behaviour."""
import json
from decimal import Decimal

from app.enums import Role
from app.models import AssistantAction, AssistantChat, AssistantMessage, AssistantPlan
from app.services import ui_settings
from app.services.assistant import engine, llm, plans
from app.services.settings_service import set_setting
from tests.conftest import make_product, make_user


class Script:
    """Scripted model replies, one per call to llm.stream, in the OpenAI shape the engine stores."""

    def __init__(self, *replies):
        self.replies, self.seen = list(replies), []

    def stream(self):
        async def fake(cfg, model, messages, tools, *, timeout=0):
            self.seen.append(list(messages))  # the engine goes on appending to its own list
            reply = self.replies.pop(0)
            if reply.get("content"):
                yield ("delta", reply["content"])
            yield ("message", {"content": reply.get("content"), "tool_calls": reply.get("tool_calls")})
        return fake


def call(cid: str, name: str, **args) -> dict:
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


async def fake_config(db, chat=None):
    class Cfg:
        ready = True
    return Cfg(), "fake-model"


async def collect(gen) -> list[dict]:
    return [ev async for ev in gen]


async def product(db, **kw):
    """A product as a tool finds it: committed, its relationships loaded (a fresh session would have them too)."""
    p = await make_product(db, **kw)
    await db.commit()
    await db.refresh(p)
    return p


async def setup(db, monkeypatch, script: Script):
    monkeypatch.setattr(engine, "config", fake_config)
    monkeypatch.setattr(llm, "stream", script.stream())
    admin = await make_user(db, 81, role=Role.ADMIN)
    chat = AssistantChat(staff_id=admin.id, title="", provider="custom", model="fake-model")
    db.add(chat)
    await db.commit()
    await db.refresh(chat, ["messages"])
    return admin, chat


async def test_plan_waits_runs_and_undoes(db, monkeypatch):
    p = await product(db, price="40")
    script = Script(
        {"content": "Narxni 70 ga o'zgartiraman.", "tool_calls": [call("c1", "get_product", id=p.id), call("c2", "update_product", id=p.id, price=70)]},
        {"content": "Bajarildi: narx 70 USD."},
    )
    admin, chat = await setup(db, monkeypatch, script)
    evs = await collect(engine.run_turn(db, chat, admin, "narxni 70 qil"))
    # the read ran, the change waits
    assert evs[-1]["type"] == "plan" and evs[-1]["plan"].status == "pending" and [c["id"] for c in evs[-1]["plan"].calls] == ["c2"]
    assert not [e for e in evs if e["type"] == "action"]
    await db.refresh(p)
    assert p.price == Decimal("40")
    await db.refresh(chat, ["messages"])
    tool_msgs = [m for m in chat.messages if m.role == "tool"]
    assert [m.tool_call_id for m in tool_msgs] == ["c1"]  # only the read has a result so far
    plan = evs[-1]["plan"]
    items = plans.view(plan)
    assert items[0]["name"] == "update_product" and {r["key"]: r["value"] for r in items[0]["rows"]} == {"id": str(p.id), "price": "70"}
    # the model's text about the plan was told to say the plan card is the OK
    assert "wait for the staff member's OK" in script.seen[0][0]["content"]
    # approve: the change runs under the plan, the model reports
    evs = await collect(engine.resume_plan(db, chat, admin, plan, True))
    await db.refresh(p)
    assert p.price == Decimal("70")
    assert plan.status == "approved" and plan.results[0]["call_id"] == "c2" and plan.results[0]["error"] is None
    action = await db.get(AssistantAction, plan.results[0]["action_id"])
    assert action.plan_id == plan.id and action.status == "done"
    assert evs[-1]["type"] == "message" and "Bajarildi" in evs[-1]["message"].content
    await db.refresh(chat, ["messages"])
    assert [m.tool_call_id for m in chat.messages if m.role == "tool"] == ["c1", "c2"]
    # a second approve is refused
    assert (await collect(engine.resume_plan(db, chat, admin, plan, True)))[0]["code"] == "plan_closed"
    # undo the whole plan
    await db.refresh(plan, ["actions"])
    n, notes = await engine.undo_plan(db, plan, admin)
    await db.refresh(p)
    assert n == 1 and notes == [] and p.price == Decimal("40")
    await db.refresh(plan, ["actions"])
    assert plan.undoable == 0 and plan.actions[0].status == "undone"


async def test_decline_and_new_message_tell_the_model(db, monkeypatch):
    p = await product(db)
    script = Script(
        {"content": "O'chiraman.", "tool_calls": [call("d1", "delete_products", ids=[p.id])]},
        {"content": "Xo'p, o'chirmadim. Nima qilay?"},
        {"content": "", "tool_calls": [call("d2", "update_product", id=p.id, stock=5)]},
        {"content": "Yangi xabaringizni o'qidim."},
    )
    admin, chat = await setup(db, monkeypatch, script)
    evs = await collect(engine.run_turn(db, chat, admin, "mahsulotni o'chir"))
    plan = evs[-1]["plan"]
    evs = await collect(engine.resume_plan(db, chat, admin, plan, False))
    assert plan.status == "declined" and plan.note == "staff"
    await db.refresh(chat, ["messages"])
    cancelled = [m for m in chat.messages if m.role == "tool" and m.tool_call_id == "d1"]
    assert len(cancelled) == 1 and "did not approve" in cancelled[0].content
    assert evs[-1]["type"] == "message" and "o'chirmadim" in evs[-1]["message"].content
    assert await db.get(type(p), p.id) is not None
    # a new message while a plan waits: the plan is superseded, the model hears it and reads the new message
    evs = await collect(engine.run_turn(db, chat, admin, "qoldiqni 5 qil"))
    plan2 = evs[-1]["plan"]
    assert plan2.status == "pending" and plan2.calls[0]["id"] == "d2"
    evs = await collect(engine.run_turn(db, chat, admin, "yo'q, hech narsa qilma"))
    assert evs[0]["type"] == "plan" and evs[0]["plan"].id == plan2.id and evs[0]["plan"].status == "declined" and evs[0]["plan"].note == "superseded"
    await db.refresh(chat, ["messages"])
    sup = [m for m in chat.messages if m.role == "tool" and m.tool_call_id == "d2"]
    assert len(sup) == 1 and "new message" in sup[0].content
    assert evs[-1]["type"] == "message"
    # the model saw the superseded result right before the new message
    roles = [m["role"] for m in script.seen[-1]]
    assert roles[-2:] == ["tool", "user"]


async def test_confirm_off_acts_at_once_and_approved_plan_counts_as_ok(db, monkeypatch):
    p = await product(db, price="40")
    await set_setting(db, "assistant_confirm", False)
    await db.commit()
    script = Script(
        {"content": "", "tool_calls": [call("e1", "update_product", id=p.id, price=55)]},
        {"content": "Narx 55."},
    )
    admin, chat = await setup(db, monkeypatch, script)
    evs = await collect(engine.run_turn(db, chat, admin, "narx 55"))
    kinds = [e["type"] for e in evs]
    assert "action" in kinds and "plan" not in kinds and evs[-1]["type"] == "message"
    await db.refresh(p)
    assert p.price == Decimal("55") and evs[kinds.index("action")]["action"].plan_id is None
    assert "act directly" in script.seen[0][0]["content"]
    # back on: a design change under an approved plan needs no confirm=true of its own
    await set_setting(db, "assistant_confirm", True)
    await db.commit()
    script.replies += [
        {"content": "Admin panelni yashil qilaman.", "tool_calls": [call("f1", "set_custom_css", target="admin", css=".topbar{background:#0a0}", confirm=False)]},
        {"content": "Tayyor."},
    ]
    evs = await collect(engine.run_turn(db, chat, admin, "admin panel yashil bo'lsin"))
    plan = evs[-1]["plan"]
    assert plan.status == "pending"
    await collect(engine.resume_plan(db, chat, admin, plan, True))
    assert plan.status == "approved" and plan.results[0]["error"] is None
    await ui_settings.ensure(db, force=True)
    assert ".topbar{background:#0a0}" in ui_settings.ui_css("admin")
    await db.refresh(plan, ["actions"])
    await engine.undo_plan(db, plan, admin)
    await ui_settings.ensure(db, force=True)
    assert ".topbar" not in ui_settings.ui_css("admin")


def test_plan_rows_are_readable():
    rows = plans.rows({"id": 5, "price": 70.5, "active": True, "title": {"uzl": "Salom", "ru": "Привет", "zh": ""}, "ids": [1, 2], "lines": [{"a": 1}], "skip": None, "empty": ""})
    by = {r["key"]: r for r in rows}
    assert set(by) == {"id", "price", "active", "title", "ids", "lines"}
    assert by["price"]["value"] == "70.5" and by["active"]["value"] == "yes" and by["ids"]["value"] == "1, 2" and by["lines"]["value"] == '[{"a": 1}]'
    assert by["title"]["lines"] == [("uzl", "Salom"), ("ru", "Привет")]
    assert plans.title("update_product").startswith("Change fields of a product") and plans.title("nope_tool") == "nope tool"
    assert engine.held("update_product") and engine.held("undo_action") and not engine.held("get_product") and not engine.held("nope")


async def test_pending_plan_message_shape_for_the_model(db, monkeypatch):
    """What the model is sent after a plan: every tool call of its message has a result before the next assistant turn."""
    p = await product(db)
    script = Script(
        {"content": "", "tool_calls": [call("g1", "get_product", id=p.id), call("g2", "update_product", id=p.id, stock=9), call("g3", "update_product", id=p.id, price=41)]},
        {"content": "ok"},
    )
    admin, chat = await setup(db, monkeypatch, script)
    evs = await collect(engine.run_turn(db, chat, admin, "ikkita o'zgarish"))
    plan = evs[-1]["plan"]
    assert len(plan.calls) == 2
    await collect(engine.resume_plan(db, chat, admin, plan, True))
    sent = script.seen[-1]
    am = next(m for m in sent if m["role"] == "assistant" and m.get("tool_calls"))
    results = {m["tool_call_id"] for m in sent if m["role"] == "tool"}
    assert {c["id"] for c in am["tool_calls"]} == {"g1", "g2", "g3"} == results
    assert len(plan.actions) == 2 and plan.undoable == 2
    msgs = (await db.execute(AssistantMessage.__table__.select().where(AssistantMessage.chat_id == chat.id))).all()
    assert len(msgs) == 1 + 1 + 3 + 1  # user, assistant(with calls), three tool results, the answer
    assert (await db.get(AssistantPlan, plan.id)).status == "approved"
