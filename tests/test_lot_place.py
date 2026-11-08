"""Where a lot's drives are, as the pages say it."""
from types import SimpleNamespace as NS

from app.templating import lot_place


def test_lot_place():
    assert lot_place(NS(location=None, location_name=None, location_city=None), "ru") == ""
    a = NS(location="UZ", location_name={"ru": "Узбекистан", "en": "Uzbekistan"}, location_city={"ru": "Ташкент", "en": "Tashkent", "region": {"en": "Tashkent region"}})
    assert lot_place(a, "ru") == "Узбекистан · Ташкент" and lot_place(a, "en") == "Uzbekistan · Tashkent"
    assert lot_place(NS(location="CN", location_name={"en": "China"}, location_city=None), "en") == "China"
    legacy = NS(location="cn", location_name=None, location_city=None)  # saved before the Geo names were copied
    assert lot_place(legacy, "en") in ("China", "In China")
