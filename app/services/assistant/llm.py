"""OpenAI-compatible chat completions (DeepSeek by default), with function calling."""
import httpx


class LLMError(Exception):
    pass


async def chat(base_url: str, api_key: str, model: str, messages: list[dict], tools: list[dict] | None = None, *, timeout: float = 180) -> dict:
    """One completion. Returns the assistant message dict: {"content": str|None, "tool_calls": [...]|None}."""
    if not api_key:
        raise LLMError("no_api_key")
    body: dict = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 4096}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    url = base_url.rstrip("/") + ("" if base_url.rstrip("/").endswith("/v1") or "api.deepseek.com" in base_url else "/v1") + "/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=timeout) as cl:
            r = await cl.post(url, json=body, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    except httpx.HTTPError as e:
        raise LLMError(f"network: {e.__class__.__name__}") from e
    if r.status_code == 401:
        raise LLMError("bad_api_key")
    if r.status_code == 402:
        raise LLMError("no_balance")
    if r.status_code == 429:
        raise LLMError("rate_limited")
    if r.status_code >= 400:
        detail = ""
        try:
            detail = (r.json().get("error") or {}).get("message") or ""
        except ValueError:
            detail = r.text[:200]
        raise LLMError(f"http {r.status_code}: {detail}")
    data = r.json()
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError) as e:
        raise LLMError("empty_response") from e
    return {"content": msg.get("content"), "tool_calls": msg.get("tool_calls") or None, "usage": data.get("usage") or {}}
