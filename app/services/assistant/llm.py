"""Talking to the model: OpenAI chat completions (streamed) for most providers, Anthropic Messages for Claude.

`stream(cfg, model, messages, tools)` is an async generator: ("delta", text) while the answer arrives, then one
("message", {"content", "tool_calls"}) in the OpenAI shape the engine stores. Messages in = OpenAI shape too; the
Anthropic adapter converts both ways.
"""
import json
from collections.abc import AsyncIterator

import httpx

from app.services.assistant.providers import ProviderConfig


class LLMError(Exception):
    pass


def _status_error(r: httpx.Response) -> LLMError:
    if r.status_code in (401, 403):
        return LLMError("bad_api_key")
    if r.status_code == 402:
        return LLMError("no_balance")
    if r.status_code == 429:
        return LLMError("rate_limited")
    if r.status_code == 404:
        return LLMError("no_model")
    detail = ""
    try:
        err = r.json().get("error")
        detail = (err.get("message") if isinstance(err, dict) else str(err)) or ""
    except ValueError:
        detail = r.text[:200]
    return LLMError(f"http {r.status_code}: {detail[:200]}")


def _url(cfg: ProviderConfig, path: str) -> str:
    base = cfg.base_url.rstrip("/")
    if cfg.provider.kind == "anthropic":
        return base + "/v1" + path if not base.endswith("/v1") else base + path
    return base + path


async def stream(cfg: ProviderConfig, model: str, messages: list[dict], tools: list[dict] | None, *, timeout: float = 240) -> AsyncIterator[tuple[str, object]]:
    if not cfg.ready:
        raise LLMError("no_api_key")
    if cfg.provider.kind == "anthropic":
        async for ev in _anthropic(cfg, model, messages, tools, timeout):
            yield ev
        return
    async for ev in _openai(cfg, model, messages, tools, timeout):
        yield ev


# ---------- OpenAI dialect, streamed ----------

async def _openai(cfg: ProviderConfig, model: str, messages: list[dict], tools: list[dict] | None, timeout: float) -> AsyncIterator[tuple[str, object]]:
    body: dict = {"model": model, "messages": messages, "stream": True}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if not model.startswith(("o1", "o3", "o4", "gpt-5")):  # reasoning models refuse a temperature
        body["temperature"] = 0.2
    headers = {"Authorization": f"Bearer {cfg.key}", "Content-Type": "application/json", "Accept": "text/event-stream"}
    if cfg.provider.id == "openrouter":
        headers |= {"HTTP-Referer": "https://nuhd.shop", "X-Title": "New & Used Hard Disk admin assistant"}
    content, calls, got_any = [], {}, False
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=20)) as cl, cl.stream("POST", _url(cfg, "/chat/completions"), json=body, headers=headers) as r:
            if r.status_code >= 400:
                await r.aread()
                raise _status_error(r)
            ctype = r.headers.get("content-type", "")
            if "text/event-stream" not in ctype:  # a server that ignored stream=true: one JSON answer
                await r.aread()
                msg = _pick_message(r.json())
                if msg.get("content"):
                    yield "delta", msg["content"]
                yield "message", msg
                return
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                if chunk.get("error"):
                    err = chunk["error"]
                    raise LLMError(f"api: {(err.get('message') if isinstance(err, dict) else str(err))[:200]}")
                for ch in chunk.get("choices") or []:
                    d = ch.get("delta") or {}
                    got_any = True
                    if d.get("content"):
                        content.append(d["content"])
                        yield "delta", d["content"]
                    for tc in d.get("tool_calls") or []:
                        i = tc.get("index", len(calls))
                        slot = calls.setdefault(i, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["function"]["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["function"]["arguments"] += fn["arguments"]
    except httpx.HTTPError as e:
        raise LLMError(f"network: {e.__class__.__name__}") from e
    if not got_any and not content and not calls:
        raise LLMError("empty_response")
    tool_calls = [calls[i] for i in sorted(calls)] or None
    if tool_calls:
        for n, c in enumerate(tool_calls):
            c["id"] = c["id"] or f"call_{n}"
    yield "message", {"content": "".join(content) or None, "tool_calls": tool_calls}


def _pick_message(data: dict) -> dict:
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError("empty_response") from e
    return {"content": msg.get("content"), "tool_calls": msg.get("tool_calls") or None}


# ---------- Anthropic Messages API ----------

def _to_anthropic(messages: list[dict]) -> tuple[str, list[dict]]:
    system, out = "", []
    for m in messages:
        if m["role"] == "system":
            system += (m.get("content") or "") + "\n"
        elif m["role"] == "user":
            out.append({"role": "user", "content": m.get("content") or ""})
        elif m["role"] == "assistant":
            blocks = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls") or []:
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except ValueError:
                    args = {}
                blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["function"]["name"], "input": args})
            if blocks:
                out.append({"role": "assistant", "content": blocks})
        elif m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m.get("tool_call_id"), "content": m.get("content") or ""}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
    return system.strip(), out


async def _anthropic(cfg: ProviderConfig, model: str, messages: list[dict], tools: list[dict] | None, timeout: float) -> AsyncIterator[tuple[str, object]]:
    system, msgs = _to_anthropic(messages)
    body: dict = {"model": model, "max_tokens": 4096, "messages": msgs}
    if system:
        body["system"] = system
    if tools:
        body["tools"] = [{"name": t["function"]["name"], "description": t["function"].get("description", ""), "input_schema": t["function"]["parameters"]} for t in tools]
    headers = {"x-api-key": cfg.key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=20)) as cl:
            r = await cl.post(_url(cfg, "/messages"), json=body, headers=headers)
    except httpx.HTTPError as e:
        raise LLMError(f"network: {e.__class__.__name__}") from e
    if r.status_code >= 400:
        raise _status_error(r)
    data = r.json()
    text, calls = [], []
    for b in data.get("content") or []:
        if b.get("type") == "text":
            text.append(b.get("text") or "")
        elif b.get("type") == "tool_use":
            calls.append({"id": b["id"], "type": "function", "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {}, ensure_ascii=False)}})
    content = "".join(text)
    if content:
        yield "delta", content
    yield "message", {"content": content or None, "tool_calls": calls or None}
