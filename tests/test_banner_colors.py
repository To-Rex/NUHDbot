"""Banner colours: the presets and any #rrggbb; the class and the inline style a template paints with."""
from app.services import banners
from app.templating import bcolor, bcolor_attr


def test_clean_color_and_paint():
    assert banners.clean_color("blue") == "blue" and banners.clean_color(" Navy ") == "navy"
    assert banners.clean_color("#1A2B3C") == "#1a2b3c" and banners.clean_color("1a2b3c") == "#1a2b3c"
    assert banners.clean_color("#12345") is None and banners.clean_color("rainbow") is None and banners.clean_color(None) is None
    assert bcolor("blue") == "c-blue" and bcolor(None) == "c-red" and bcolor("#1a2b3c") == "c-custom"
    assert str(bcolor_attr("blue")) == "" and str(bcolor_attr("#1a2b3c")) == ' style="--bc:#1a2b3c;--bi:#fff"'
    assert str(bcolor_attr("#f5f5f7")) == ' style="--bc:#f5f5f7;--bi:#1C1C1E"'  # a light background takes dark ink
