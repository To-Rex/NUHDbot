import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import APP_DIR, settings

LOCALES_DIR = APP_DIR / "locales"


def _deep_merge(dst: dict, src: dict) -> dict:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


@lru_cache
def _load(lang: str) -> dict[str, Any]:
    """Merge every JSON file in locales/<lang>/ (common.json, miniapp.json, admin.json, bot.json ...)."""
    folder: Path = LOCALES_DIR / lang
    merged: dict[str, Any] = {}
    if not folder.is_dir():
        return merged
    for path in sorted(folder.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            _deep_merge(merged, json.load(f))
    return merged


def normalize_lang(lang: str | None) -> str:
    """Map any language tag to one of settings.langs: uz (Cyrillic), uzl (Latin), ru, en, zh."""
    raw = (lang or "").strip().lower().replace("_", "-")
    if not raw:
        return settings.default_lang
    first = raw.split(",")[0].split(";")[0].strip()
    if first in settings.langs:
        return first
    if first.startswith("uz"):
        return "uzl" if "latn" in first or first in ("uz-latn", "uzl") else "uz"
    if first.startswith("zh"):
        return "zh"
    short = first[:2]
    return short if short in settings.langs else settings.default_lang


def t(lang: str, key: str, **kwargs: Any) -> str:
    """Translate a dotted key. Falls back to uz, then to the key itself."""
    lang = normalize_lang(lang)
    for candidate in (lang, settings.default_lang, "en"):
        node: Any = _load(candidate)
        for part in key.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                node = None
                break
        if isinstance(node, str):
            try:
                return node.format(**kwargs) if kwargs else node
            except (KeyError, IndexError):
                return node
    return key


def pick(value: dict | str | None, lang: str) -> str:
    """Pick a language from an i18n JSON dict like {"uz": "...", "ru": "..."}."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    lang = normalize_lang(lang)
    order = {"uzl": ("uzl", "uz", "en"), "zh": ("zh", "en", "ru", "uz")}.get(lang, (lang, settings.default_lang, "en"))
    for code in order:
        if value.get(code):
            return value[code]
    return next((v for v in value.values() if v), "")


def reload_locales() -> None:
    _load.cache_clear()
