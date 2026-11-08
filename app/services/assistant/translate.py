"""Translating the panel's multilingual fields with the assistant's model.

Every i18n field (UZ Кир · UZ Lot · RU · EN · ZH) has a Translate button: the staff member writes one language, the model
fills the others — through the same provider, key and default model the assistant chat uses (/admin/assistant)."""
import json
import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.assistant import engine, llm

LANG_NAMES = {
    "uz": "Uzbek in Cyrillic script (ўзбекча, кирилл)",
    "uzl": "Uzbek in Latin script (o'zbekcha, lotin)",
    "ru": "Russian",
    "en": "English",
    "zh": "Simplified Chinese",
}
MAX_CHARS = 6000

SYSTEM = (
    "You translate texts for the admin panel of an online shop that sells new and used hard drives (HDD) to businesses in "
    "Uzbekistan, Russia and China. Translate faithfully and naturally, in the register of the source. Keep numbers, units "
    "(TB, GB, rpm, MB), brand and model names, prices, line breaks, Markdown/HTML tags and placeholders such as {n} or {amount} "
    "exactly as they are. Uzbek Cyrillic and Uzbek Latin are one language in two scripts: between them, transliterate the "
    "same wording rather than rephrasing. Never add explanations, notes or quotation marks around the text. Answer with one "
    "JSON object only — the target language codes as keys, the translations as string values."
)


class TranslateError(Exception):
    pass


def _parse(answer: str, targets: list[str]) -> dict[str, str]:
    """The model's JSON, with or without a code fence; anything else is an error."""
    s = (answer or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.S).strip()
    data = None
    try:
        data = json.loads(s)
    except ValueError:
        a, b = s.find("{"), s.rfind("}")
        if a >= 0 and b > a:
            try:
                data = json.loads(s[a:b + 1])
            except ValueError:
                data = None
    if not isinstance(data, dict):
        raise TranslateError("bad_answer")
    out = {k: str(v).strip() for k, v in data.items() if k in targets and isinstance(v, str) and v.strip()}
    if not out:
        raise TranslateError("bad_answer")
    return out


def pick_source(texts: dict[str, str], preferred: str | None = None) -> str | None:
    """The language to translate from: the preferred one when it has text, else the first that does (in the shop's order)."""
    if preferred and (texts.get(preferred) or "").strip():
        return preferred
    return next((code for code in settings.langs if (texts.get(code) or "").strip()), None)


async def translate(db: AsyncSession, texts: dict[str, str], targets: list[str], *, source: str | None = None, kind: str = "input") -> tuple[str, dict[str, str]]:
    """Returns (source language, {target: translation}). Raises TranslateError (no_source, too_long, bad_answer) or llm.LLMError."""
    src = pick_source(texts, source)
    if not src:
        raise TranslateError("no_source")
    text = texts[src].strip()
    if len(text) > MAX_CHARS:
        raise TranslateError("too_long")
    targets = [c for c in targets if c in LANG_NAMES and c != src]
    if not targets:
        return src, {}
    cfg, model = await engine.config(db)
    shape = "a single line (a title, a name or a short label)" if kind == "input" else ("HTML / Markdown markup: keep every tag and its placement" if kind == "code" else "a text of one or more paragraphs")
    user = json.dumps({"source_language": LANG_NAMES[src], "text": text, "translate_into": {c: LANG_NAMES[c] for c in targets}, "text_kind": shape}, ensure_ascii=False)
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    answer, parts = "", []
    async for ev_kind, payload in llm.stream(cfg, model, messages, None, timeout=90):
        if ev_kind == "delta":
            parts.append(str(payload))
        elif ev_kind == "message":
            answer = (payload or {}).get("content") or ""
    return src, _parse(answer or "".join(parts), targets)
