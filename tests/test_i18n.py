import json
import re
from pathlib import Path

import pytest

from app.config import settings
from app.i18n import LOCALES_DIR, normalize_lang, pick, t

PLACEHOLDER = re.compile(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}")


def _flatten(d: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in d.items():
        full = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, full + "."))
        else:
            out[full] = str(v)
    return out


def _file(lang: str, name: str) -> dict[str, str]:
    path = LOCALES_DIR / lang / f"{name}.json"
    assert path.exists(), f"missing locale file {lang}/{name}.json"
    return _flatten(json.loads(Path(path).read_text(encoding="utf-8")))


FILES = sorted(p.stem for p in (LOCALES_DIR / "uz").glob("*.json"))
OTHER_LANGS = [lang for lang in settings.langs if lang != "uz"]


def test_five_languages_configured():
    assert set(settings.langs) == {"uz", "uzl", "ru", "en", "zh"}
    for lang in settings.langs:
        assert (LOCALES_DIR / lang).is_dir(), f"locale folder missing: {lang}"


@pytest.mark.parametrize("name", FILES)
@pytest.mark.parametrize("lang", OTHER_LANGS)
def test_keys_match_uz(name: str, lang: str):
    uz = _file("uz", name)
    other = _file(lang, name)
    assert uz, f"uz/{name}.json is empty"
    missing = sorted(set(uz) - set(other))
    extra = sorted(set(other) - set(uz))
    assert not missing, f"{lang}/{name}.json missing keys: {missing[:10]}"
    assert not extra, f"{lang}/{name}.json has extra keys: {extra[:10]}"


@pytest.mark.parametrize("name", FILES)
@pytest.mark.parametrize("lang", OTHER_LANGS)
def test_placeholders_match_uz(name: str, lang: str):
    uz = _file("uz", name)
    other = _file(lang, name)
    bad = [k for k in uz if k in other and set(PLACEHOLDER.findall(uz[k])) != set(PLACEHOLDER.findall(other[k]))]
    assert not bad, f"{lang}/{name}.json placeholder mismatch in: {bad[:10]}"


def test_no_empty_strings():
    for lang in settings.langs:
        for name in FILES:
            empty = [k for k, v in _file(lang, name).items() if not v.strip()]
            assert not empty, f"{lang}/{name}.json empty values: {empty[:10]}"


def test_normalize_lang():
    assert normalize_lang("uz") == "uz"
    assert normalize_lang("uz-Latn") == "uzl"
    assert normalize_lang("uzl") == "uzl"
    assert normalize_lang("zh-CN") == "zh"
    assert normalize_lang("ru-RU,ru;q=0.9") == "ru"
    assert normalize_lang("de") == settings.default_lang
    assert normalize_lang(None) == settings.default_lang


def test_translate_and_fallback():
    assert t("ru", "nav.catalog") == "Каталог"
    assert t("uzl", "nav.catalog") == "Katalog"
    assert t("zh", "nav.catalog") == "商品"
    assert t("en", "bot.btn_catalog") == "🛒 Catalog"
    assert t("de", "common.price") == t("uz", "common.price")  # unknown lang -> default
    assert t("uz", "no.such.key") == "no.such.key"
    assert t("uz", "bot.order_line", number="N1", qty=2, total="$5", status="ok").startswith("<b>N1</b>")
    assert t("uzl", "order_status.awaiting_customer") == "Sizning tasdig'ingiz kutilmoqda"
    assert pick({"ru": "Р", "uz": "У"}, "en") == "У" and pick("plain", "ru") == "plain" and pick(None, "uz") == ""


def test_language_names_keep_native_script():
    for lang in settings.langs:
        names = _file(lang, "common")
        assert names["lang.uz"] == "Ўзбекча (кирилл)"
        assert names["lang.uzl"] == "O'zbekcha (lotin)"
        assert names["lang.ru"] == "Русский"
        assert names["lang.zh"] == "中文"
