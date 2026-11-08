"""The assistant's design hand: defaults, theme, custom CSS and wording — each asks before touching what customers see."""
import pytest

from app import i18n
from app.enums import Role
from app.services import ui_settings
from app.services.assistant import tools_more as tm
from app.services.assistant.tools import Ctx, ToolError
from tests.conftest import make_user


async def test_theme_defaults_css_and_text_tools(db):
    admin = await make_user(db, 71, role=Role.ADMIN)
    ctx = Ctx(db=db, staff=admin)
    # defaults: new products in USD, boxes of 10
    out = await tm.set_defaults(ctx, product={"currency": "usd", "box_qty": 10})
    assert out["product"]["currency"] == "USD" and out["product"]["box_qty"] == 10
    with pytest.raises(ToolError):
        await tm.set_defaults(ctx, product={"nope": 1})
    # theme: an accent for the Mini App
    out = await tm.set_theme(ctx, "miniapp", accent="#1E8C4E", radius=1.2)
    assert out["theme"]["miniapp"] == {"accent": "#1e8c4e", "radius": 1.2}
    await ui_settings.ensure(db, force=True)
    assert "--accent:#1e8c4e" in ui_settings.ui_css("miniapp") and ui_settings.theme_css("admin") == ""
    with pytest.raises(ToolError):
        await tm.set_theme(ctx, "miniapp", accent="green")
    # custom css and wording ask first
    with pytest.raises(ToolError):
        await tm.set_custom_css(ctx, "admin", ".x{}", confirm=False)
    await tm.set_custom_css(ctx, "admin", ".topbar{background:#000}<script>x</script>", confirm=True)
    await ui_settings.ensure(db, force=True)
    assert ".topbar{background:#000}" in ui_settings.ui_css("admin") and "<script" not in ui_settings.ui_css("admin")
    found = await tm.list_texts(ctx, "cart.title", lang="uzl")
    assert any(r["key"] == "cart.title" for r in found["rows"])
    with pytest.raises(ToolError):
        await tm.set_text(ctx, "cart.title", "uzl", "Savatcha", confirm=False)
    assert (await tm.set_text(ctx, "cart.title", "uzl", "Savatcha", confirm=True))["now"] == "Savatcha"
    assert i18n.t("uzl", "cart.title") == "Savatcha"
    # back to the originals
    await tm.set_text(ctx, "cart.title", "uzl", "", confirm=True)
    await tm.set_custom_css(ctx, "admin", "", mode="replace", confirm=True)
    await tm.set_theme(ctx, "miniapp", reset=True)
    await tm.set_defaults(ctx, product={"currency": None, "box_qty": None})
    await db.commit()
    await ui_settings.ensure(db, force=True)
    assert i18n.t("uzl", "cart.title") != "Savatcha" and ui_settings.ui_css("miniapp").strip() == "" and ui_settings.product_defaults()["box_qty"] == 20
