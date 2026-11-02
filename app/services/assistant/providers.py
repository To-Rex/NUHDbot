"""Model providers for the admin assistant.

Everything but Anthropic speaks the OpenAI chat-completions dialect (DeepSeek, OpenAI, Gemini's OpenAI endpoint,
OpenRouter, Groq, xAI, Ollama / any custom server); Anthropic has its own Messages API. Keys and custom base URLs live
in the `assistant_providers` setting ({provider_id: {"key": ..., "base_url": ...}}); the model to start new chats with
is `assistant_default_model` ("provider:model"). Model lists come from each provider's /models endpoint (cached for
ten minutes), with a short built-in list as a fallback.
"""
import re
import time
from dataclasses import dataclass, field

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.settings_service import get_setting, set_setting


@dataclass(frozen=True)
class Provider:
    id: str
    name: str
    base_url: str
    kind: str = "openai"  # openai | anthropic
    key_url: str = ""
    models: tuple[str, ...] = ()
    keep: str = r".*"  # which ids of the live /models list are chat models worth showing
    needs_key: bool = True


PROVIDERS: dict[str, Provider] = {p.id: p for p in (
    Provider("deepseek", "DeepSeek", "https://api.deepseek.com", key_url="https://platform.deepseek.com/api_keys", models=("deepseek-chat", "deepseek-reasoner")),
    Provider("openai", "OpenAI", "https://api.openai.com/v1", key_url="https://platform.openai.com/api-keys",
             models=("gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini", "o4-mini"), keep=r"^(gpt-5|gpt-4\.1|gpt-4o|o[1-9]|chatgpt-4o)(?!.*(audio|realtime|search|transcribe|tts|image))"),
    Provider("anthropic", "Anthropic Claude", "https://api.anthropic.com", kind="anthropic", key_url="https://console.anthropic.com/settings/keys",
             models=("claude-sonnet-4-5", "claude-opus-4-1", "claude-haiku-4-5"), keep=r"^claude"),
    Provider("google", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", key_url="https://aistudio.google.com/apikey",
             models=("gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"), keep=r"^(models/)?gemini-(2|3)(?!.*(embedding|tts|image|audio|live))"),
    Provider("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", key_url="https://openrouter.ai/settings/keys",
             models=("anthropic/claude-sonnet-4.5", "openai/gpt-5", "google/gemini-2.5-pro", "deepseek/deepseek-chat-v3.1", "qwen/qwen3-235b-a22b", "meta-llama/llama-4-maverick"), keep=r"^(anthropic|openai|google|deepseek|qwen|meta-llama|mistralai|x-ai|moonshotai|z-ai)/"),
    Provider("groq", "Groq", "https://api.groq.com/openai/v1", key_url="https://console.groq.com/keys", models=("llama-3.3-70b-versatile", "openai/gpt-oss-120b", "qwen/qwen3-32b"), keep=r"^(llama|openai/gpt-oss|qwen|moonshotai|meta-llama)"),
    Provider("xai", "xAI Grok", "https://api.x.ai/v1", key_url="https://console.x.ai", models=("grok-4", "grok-4-fast", "grok-3-mini"), keep=r"^grok-(?!.*(image|vision))"),
    Provider("custom", "Custom (OpenAI-compatible)", "", key_url="", models=(), needs_key=False),
)}
SKIP = re.compile(r"(embed|whisper|tts|dall-e|moderation|realtime|audio|image|transcri|babbage|davinci|rerank|guard|vision-preview)", re.I)
_cache: dict[str, tuple[float, list[str]]] = {}
CACHE_SECONDS = 600


@dataclass
class ProviderConfig:
    provider: Provider
    key: str = ""
    base_url: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return bool(self.base_url) and (bool(self.key) or not self.provider.needs_key)


async def load(db: AsyncSession) -> dict[str, ProviderConfig]:
    """Every provider with what is saved for it. The first version kept one DeepSeek key in `assistant_api_key`."""
    saved = await get_setting(db, "assistant_providers", {}) or {}
    legacy_key = (await get_setting(db, "assistant_api_key", "") or "").strip() or settings.deepseek_api_key
    legacy_base = (await get_setting(db, "assistant_base_url", "") or "").strip()
    out = {}
    for pid, p in PROVIDERS.items():
        s = saved.get(pid) or {}
        key, base = (s.get("key") or "").strip(), (s.get("base_url") or "").strip() or p.base_url
        if pid == "deepseek" and not key and legacy_key and (not legacy_base or "deepseek" in legacy_base):
            key = legacy_key
        if pid == "custom" and not s and legacy_base and "deepseek" not in legacy_base:
            key, base = legacy_key, legacy_base
        out[pid] = ProviderConfig(p, key, base)
    return out


async def save(db: AsyncSession, values: dict[str, dict]) -> None:
    await set_setting(db, "assistant_providers", values)


def parse_model(ref: str | None) -> tuple[str, str]:
    """'provider:model' → (provider, model); a bare model is DeepSeek's."""
    if not ref:
        return "deepseek", "deepseek-chat"
    pid, _, model = ref.partition(":")
    if not model or pid not in PROVIDERS:
        return "deepseek", ref
    return pid, model


async def default_model(db: AsyncSession, configs: dict[str, ProviderConfig]) -> tuple[str, str]:
    """What a new chat uses: the saved default, else the first provider with a key."""
    pid, model = parse_model(await get_setting(db, "assistant_default_model", None) or ("deepseek:" + (await get_setting(db, "assistant_model", "deepseek-chat") or "deepseek-chat")))
    if configs.get(pid) and configs[pid].ready:
        return pid, model
    for cid, c in configs.items():
        if c.ready:
            return cid, (c.provider.models[0] if c.provider.models else model)
    return pid, model


def _filter(p: Provider, ids: list[str]) -> list[str]:
    keep = re.compile(p.keep)
    out = [i[7:] if i.startswith("models/") else i for i in ids]
    out = [i for i in out if keep.search(i) and not SKIP.search(i)]
    return sorted(dict.fromkeys(out)) if p.id in ("openrouter", "groq") else list(dict.fromkeys(out))


async def list_models(cfg: ProviderConfig, *, force: bool = False) -> tuple[list[str], str | None]:
    """Live model ids of a provider (filtered to chat models) and an error text when the call failed."""
    p = cfg.provider
    if not cfg.ready:
        return list(p.models), None
    ck = f"{p.id}|{cfg.base_url}|{cfg.key[-6:]}"
    hit = _cache.get(ck)
    if hit and not force and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1], None
    url = cfg.base_url.rstrip("/") + ("/v1/models" if p.kind == "anthropic" else "/models")
    headers = {"x-api-key": cfg.key, "anthropic-version": "2023-06-01"} if p.kind == "anthropic" else {"Authorization": f"Bearer {cfg.key}"}
    try:
        async with httpx.AsyncClient(timeout=20) as cl:
            r = await cl.get(url, headers=headers)
    except httpx.HTTPError as e:
        return list(p.models), f"network: {e.__class__.__name__}"
    if r.status_code >= 400:
        try:
            detail = (r.json().get("error") or {}).get("message") or ""
        except ValueError:
            detail = r.text[:120]
        return list(p.models), f"http {r.status_code}: {detail}" if detail else f"http {r.status_code}"
    try:
        data = r.json()
        raw = data.get("data") if isinstance(data, dict) else data
        ids = [m.get("id") or m.get("name") for m in raw if isinstance(m, dict)]
    except (ValueError, AttributeError, TypeError):
        return list(p.models), "bad response"
    ids = _filter(p, [i for i in ids if i]) or list(p.models)
    _cache[ck] = (time.time(), ids)
    return ids, None
