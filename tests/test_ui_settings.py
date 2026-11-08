"""The staff's look and wording: theme CSS, custom CSS hygiene, text overrides read by t(), the form defaults."""
from app import i18n
from app.services import ui_settings
from app.services.settings_service import set_setting


def test_theme_and_css_cleaning():
    th = ui_settings.clean_theme({"miniapp": {"accent": "#1E8C4E", "radius": 1.2, "font": 1.0, "density": "compact"}, "admin": {"accent": "red"}, "x": {}})
    assert th == {"miniapp": {"accent": "#1e8c4e", "radius": 1.2, "density": "compact"}}  # font 1.0 is the design; a bad accent is dropped
    ui_settings._cache["theme"] = th
    css = ui_settings.theme_css("miniapp")
    assert "--accent:#1e8c4e" in css and "--accent-ink:#ffffff" in css and "--r-scale:1.2" in css and "--density:.86" in css
    assert ui_settings.theme_css("admin") == ""
    assert "<script" not in ui_settings.clean_css("a{color:red}<script>alert(1)</script>") and "</style" not in ui_settings.clean_css("b{}</style><p>")


async def test_overrides_and_defaults_from_settings(db):
    await set_setting(db, "text_overrides", {"uzl": {"cart.title": "Savatcha"}, "xx": {"a": "b"}})
    await set_setting(db, "product_defaults", {"currency": "usd", "box_qty": 10, "bogus": 1})
    await set_setting(db, "lot_defaults", {"hours": 72})
    await db.commit()
    await ui_settings.ensure(db, force=True)
    assert i18n.t("uzl", "cart.title") == "Savatcha" and i18n.t("ru", "cart.title") != "Savatcha"
    d = ui_settings.product_defaults()
    assert d["currency"] == "usd" and d["box_qty"] == 10 and "bogus" not in d and d["seller_warranty_months"] == 12  # the rest stays built-in
    assert ui_settings.lot_defaults()["hours"] == 72 and ui_settings.lot_defaults()["qty"] == 10
    # cleanup for the other tests
    await set_setting(db, "text_overrides", {})
    await set_setting(db, "product_defaults", {})
    await set_setting(db, "lot_defaults", {})
    await db.commit()
    await ui_settings.ensure(db, force=True)
    assert i18n.t("uzl", "cart.title") != "Savatcha"
