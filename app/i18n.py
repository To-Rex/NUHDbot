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
    lang = (lang or "").lower()[:2]
    return lang if lang in settings.langs else settings.default_lang


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
    return value.get(lang) or value.get(settings.default_lang) or value.get("en") or next(iter(value.values()), "")


def reload_locales() -> None:
    _load.cache_clear()
