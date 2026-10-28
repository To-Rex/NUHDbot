import json
from pathlib import Path

from app.i18n import LOCALES_DIR, pick, t


def _flatten(d: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for k, v in d.items():
        full = f"{prefix}{k}"
        if isinstance(v, dict):
            keys |= _flatten(v, full + ".")
        else:
            keys.add(full)
    return keys


def _keys(lang: str) -> set[str]:
    keys: set[str] = set()
    for f in sorted((LOCALES_DIR / lang).glob("*.json")):
        keys |= _flatten(json.loads(Path(f).read_text(encoding="utf-8")))
    return keys


def test_all_languages_have_same_keys():
    uz, ru, en = _keys("uz"), _keys("ru"), _keys("en")
    assert uz, "uz locale empty"
    assert uz - ru == set(), f"missing in ru: {sorted(uz - ru)[:10]}"
    assert uz - en == set(), f"missing in en: {sorted(uz - en)[:10]}"
    assert ru - uz == set() and en - uz == set()


def test_translate_and_fallback():
    assert t("ru", "nav.catalog") == "Каталог"
    assert t("en", "bot.btn_catalog") == "🛒 Catalog"
    assert t("de", "common.price") == t("uz", "common.price")  # unknown lang -> default
    assert t("uz", "no.such.key") == "no.such.key"
    assert t("uz", "bot.order_line", number="N1", qty=2, total="$5", status="ok").startswith("<b>N1</b>")
    assert pick({"ru": "Р", "uz": "У"}, "en") == "У" and pick("plain", "ru") == "plain" and pick(None, "uz") == ""
