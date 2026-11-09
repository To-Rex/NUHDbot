"""Ad posts for real: the message and its button, the address book of chats, sending with per-chat results, clicks counted."""
from types import SimpleNamespace

import pytest

from app.enums import AdPostStatus
from app.models import AdPost
from app.services import ads
from app.services.settings_service import set_setting
from tests.conftest import make_product


class FakeBot:
    """Records what it is asked to send; a chat id in `fail` raises like Telegram would."""

    def __init__(self, fail=()):
        self.sent, self.fail = [], set(fail)

    async def send_photo(self, chat_id, photo, caption=None, reply_markup=None):
        return await self._send("photo", chat_id, caption, reply_markup, photo=photo)

    async def send_message(self, chat_id, text, reply_markup=None, disable_web_page_preview=None):
        return await self._send("text", chat_id, text, reply_markup)

    async def _send(self, kind, chat_id, text, markup, **kw):
        if chat_id in self.fail:
            raise RuntimeError("Forbidden: bot is not a member of the channel chat")
        self.sent.append({"kind": kind, "chat_id": chat_id, "text": text, "markup": markup, **kw})
        return SimpleNamespace(message_id=100 + len(self.sent))

    async def get_chat(self, ref):
        if ref in (-1001, "@nuhd_news"):
            return SimpleNamespace(id=-1001, type="channel", title="NUHD news", username="nuhd_news")
        raise RuntimeError("Bad Request: chat not found")

    async def get_me(self):
        return SimpleNamespace(id=777)

    async def get_chat_member(self, chat_id, user_id):
        return SimpleNamespace(status="administrator", can_post_messages=True)

    async def get_chat_member_count(self, chat_id):
        return 1234


async def _post(db, products, targets=(-1001, -1002)):
    p = AdPost(title="Hafta", text="Chegirma <b>haftasi</b>", product_ids=[x.id for x in products], target_chat_ids=list(targets), campaign="week1", deliveries=[], status=AdPostStatus.APPROVED)
    db.add(p)
    await db.flush()
    return p


def test_message_and_refs():
    post = AdPost(title="x", text="Salom <dunyo>", product_ids=[], target_chat_ids=[], campaign="abc")
    text = ads.render_post(post, [])
    assert "Salom &lt;dunyo&gt;" in text and "startapp=src_abc" in text
    assert ads.parse_ids("-1001, -1002\n5 x -3") == [-1001, -1002, 5, -3]
    assert ads.parse_ref("-1001234567890") == -1001234567890 and ads.parse_ref("@nuhd_news") == "@nuhd_news" and ads.parse_ref("https://t.me/nuhd_news/") == "@nuhd_news"
    assert ads.parse_ref("nuhd_news") == "@nuhd_news" and ads.parse_ref("??") is None and ads.parse_ref("") is None


async def test_targets_book(db):
    bot = FakeBot()
    row = await ads.check_target(db, bot, "@nuhd_news")
    assert row["id"] == -1001 and row["title"] == "NUHD news" and row["type"] == "channel" and row["members"] == 1234 and row["can_post"] is True
    await ads.upsert_target(db, {"id": -2002, "title": "Sotuvchilar", "type": "supergroup"})
    rows = await ads.targets(db)
    assert [r["id"] for r in rows] == [-1001, -2002]
    # the same chat again only refreshes
    await ads.upsert_target(db, {"id": -1001, "title": "NUHD news 2", "type": "channel"})
    assert len(await ads.targets(db)) == 2 and (await ads.targets(db))[0]["title"] == "NUHD news 2"
    await ads.mark_left(db, -2002)
    assert (await ads.targets(db))[1]["left"] is True
    assert await ads.remove_target(db, -2002) and not await ads.remove_target(db, -2002)
    with pytest.raises(ads.TargetError, match="not_found"):
        await ads.check_target(db, bot, "@nobody")
    with pytest.raises(ads.TargetError, match="bad_ref"):
        await ads.check_target(db, bot, "!!")
    with pytest.raises(ads.TargetError, match="bot_off"):
        await ads.check_target(db, None, "@nuhd_news")


async def test_send_keeps_results_and_counts_clicks(db, monkeypatch):
    p1 = await make_product(db)
    p2 = await make_product(db, price="55")
    p3 = await make_product(db, price="60")
    await db.commit()
    for p in (p1, p2, p3):
        await db.refresh(p)
    await set_setting(db, "ad_targets", [{"id": -1001, "title": "NUHD news", "type": "channel"}])
    post = await _post(db, [p1, p2, p3])
    bot = FakeBot(fail={-1002})
    # no picture on these products → text with the button
    results = await ads.send_post(db, bot, post)
    assert [r["ok"] for r in results] == [True, False] and results[0]["title"] == "NUHD news" and results[0]["message_id"] == 101 and "Forbidden" in results[1]["error"]
    assert bot.sent[0]["kind"] == "text" and bot.sent[0]["markup"].inline_keyboard[0][0].url.endswith("startapp=src_week1")
    assert post.status == AdPostStatus.SENT and post.sent_at is not None and len(post.deliveries) == 2
    assert ads.summary(post) == {"ok": 1, "bad": 1, "tests": 0}
    # a picture, when the shop has an https address, goes as a photo with the post as caption
    monkeypatch.setattr(ads, "photo_url", lambda products: "https://shop.example/static/uploads/a.jpg")
    r = await ads.send_test(db, bot, post, 555)
    assert r["ok"] and r["test"] and bot.sent[-1]["kind"] == "photo" and bot.sent[-1]["photo"].endswith("a.jpg") and ads.summary(post)["tests"] == 1
    # clicks: a start parameter from the post's link
    await db.commit()
    assert await ads.count_click(db, "src_week1") and not await ads.count_click(db, "src_nothing") and not await ads.count_click(db, "")
    await db.refresh(post)
    assert post.clicks == 1


def test_photo_needs_public_https(monkeypatch):
    from app.config import settings

    cover = SimpleNamespace(filename="x.jpg")
    prod = SimpleNamespace(cover=cover)
    monkeypatch.setattr(ads.storage, "url", lambda name: "/static/uploads/" + name)
    monkeypatch.setattr(settings, "base_url", "http://localhost:8000")
    assert ads.photo_url([prod]) is None  # Telegram cannot fetch a localhost picture
    monkeypatch.setattr(settings, "base_url", "https://shop.example")
    assert ads.photo_url([SimpleNamespace(cover=None), prod]) == "https://shop.example/static/uploads/x.jpg"
