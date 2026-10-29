"""Geography dataset + Uzbek Latin→Cyrillic transliteration used by the seed."""
from collections import Counter

import pytest

from scripts.geo_data import COUNTRIES, iter_places, latin_to_cyrillic, names_for


@pytest.mark.parametrize(
    ("latin", "cyrillic"),
    [
        ("Toshkent", "Тошкент"),
        ("Farg'ona", "Фарғона"),
        ("Qo'qon", "Қўқон"),
        ("Yangiyo'l", "Янгийўл"),
        ("Yangiyer", "Янгиер"),
        ("Shahrisabz", "Шаҳрисабз"),
        ("G'ijduvon", "Ғиждувон"),
        ("Kattaqo'rg'on", "Каттақўрғон"),
        ("Xo'jayli", "Хўжайли"),
        ("Chirchiq", "Чирчиқ"),
        ("Sirdaryo viloyati", "Сирдарё вилояти"),
        ("Qoraqalpog'iston Respublikasi", "Қорақалпоғистон Республикаси"),
        ("Oqqo'rg'on", "Оққўрғон"),
        ("Jizzax", "Жиззах"),
    ],
)
def test_latin_to_cyrillic(latin, cyrillic):
    assert latin_to_cyrillic(latin) == cyrillic


def test_names_for_uses_russian_spelling_outside_uzbekistan():
    assert names_for("UZ", "Buxoro", "Бухара", "Bukhara")["uz"] == "Бухоро"
    assert names_for("RU", "Moskva", "Москва", "Moscow")["uz"] == "Москва"
    assert names_for("KZ", "Almaty", "Алматы", "Almaty") == {"uz": "Алматы", "uzl": "Almaty", "ru": "Алматы", "en": "Almaty"}


def test_dataset_is_consistent():
    codes = [c[0] for c in COUNTRIES]
    assert len(codes) == len(set(codes))
    assert codes[0] == "UZ" and codes[-1] == "OT"
    total = 0
    for code, _flag, _phone, names, regions in COUNTRIES:
        assert set(names) == {"uz", "uzl", "ru", "en", "zh"}
        en_names = Counter(city["en"] for _, city in iter_places(code, regions))
        dupes = [n for n, k in en_names.items() if k > 1]
        assert not dupes, f"{code}: duplicate cities {dupes}"
        total += sum(en_names.values())
    assert total > 400
    uz_cities = list(iter_places("UZ", dict((c[0], c[4]) for c in COUNTRIES)["UZ"]))
    assert len({r["en"] for r, _ in uz_cities if r}) == 14  # 12 regions + Tashkent city + Karakalpakstan
    assert len([c for _, c in iter_places("RU", dict((c[0], c[4]) for c in COUNTRIES)["RU"])]) >= 80
