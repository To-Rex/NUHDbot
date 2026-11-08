"""The Translate button's service: the source language, the model's answer parsed, the errors named."""
import json

import pytest

from app.services.assistant import llm
from app.services.assistant import translate as tr


def test_parse_and_source():
    assert tr._parse('```json\n{"ru": "Привет", "en": "Hello", "xx": "no"}\n```', ["ru", "en"]) == {"ru": "Привет", "en": "Hello"}
    assert tr._parse('Here you go: {"en": "Hello"} thanks', ["en"]) == {"en": "Hello"}
    with pytest.raises(tr.TranslateError):
        tr._parse("sorry", ["en"])
    assert tr.pick_source({"uz": "", "ru": "Текст", "en": ""}) == "ru"
    assert tr.pick_source({"ru": "Текст", "en": "Text"}, "en") == "en"  # the open tab wins when it has text
    assert tr.pick_source({"ru": "Текст", "en": "Text"}, "zh") == "ru"  # an empty open tab: the first language with text
    assert tr.pick_source({"ru": "  "}) is None


async def test_translate_calls_the_assistant_model(db, monkeypatch):
    seen = {}

    async def fake_config(db_):
        return object(), "fake-model"

    async def fake_stream(cfg, model, messages, tools, *, timeout=0):
        seen["model"], seen["messages"] = model, messages
        yield ("delta", '{"en": "4TB drive, ')
        yield ("delta", 'checked"}')
        yield ("message", {"content": '{"en": "4TB drive, checked", "zh": "4TB 硬盘，已检测"}', "tool_calls": []})

    monkeypatch.setattr(tr.engine, "config", fake_config)
    monkeypatch.setattr(llm, "stream", fake_stream)
    src, out = await tr.translate(db, {"ru": "Диск 4TB, проверен", "en": ""}, ["en", "zh", "ru"], kind="input")
    assert src == "ru" and out == {"en": "4TB drive, checked", "zh": "4TB 硬盘，已检测"}
    assert seen["model"] == "fake-model"
    body = json.loads(seen["messages"][1]["content"])
    assert body["text"] == "Диск 4TB, проверен" and set(body["translate_into"]) == {"en", "zh"}  # never into itself
    with pytest.raises(tr.TranslateError, match="no_source"):
        await tr.translate(db, {"ru": " "}, ["en"])
    assert await tr.translate(db, {"ru": "x"}, ["ru"]) == ("ru", {})  # nothing to do
