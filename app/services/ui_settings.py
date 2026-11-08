"""What the staff (mostly through the assistant) may change about the shop's look and defaults without touching code.

Four settings, cached in this process for a short while (every request calls `ensure`):
* `theme`        — per target (miniapp / admin): the accent colour, the corner radius, the type size, the density.
                   Rendered as CSS-variable overrides on :root after tokens.css, so every component follows.
* `custom_css`   — per target: free CSS appended last (the assistant's "change the design" hand, with the staff's OK).
* `text_overrides` — {lang: {dotted key: text}}: any interface string, read by i18n.t before the locale files.
* `product_defaults` / `lot_defaults` — what a new product / lot form opens with.
"""
import re
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app import i18n
from app.config import settings
from app.services.settings_service import get_setting

TTL = 20
TARGETS = ("miniapp", "admin")
THEME_KEYS = {"accent": "colour", "radius": "number", "font": "number", "density": "choice"}
DENSITIES = ("compact", "normal", "comfortable")
HEX_RE = re.compile(r"^#([0-9a-fA-F]{6})$")

PRODUCT_DEFAULTS = {"currency": None, "seller_warranty_months": 12, "factory_warranty_months": 36, "min_order": 0, "box_qty": 20, "full_box_only": True, "test_status": "tested", "health": "Good / 100%"}
LOT_DEFAULTS = {"currency": None, "qty": 10, "hours": 24, "step_per_unit": 1, "location": None}

_cache: dict = {"theme": {}, "custom_css": {}, "text_overrides": {}, "product_defaults": {}, "lot_defaults": {}}
_loaded_at = 0.0


def _hex(v) -> str | None:
    v = str(v or "").strip()
    return v.lower() if HEX_RE.match(v) else None


def _mix(hex_color: str, white: float) -> str:
    """The accent lightened towards white: the soft background behind chips and selections."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    r, g, b = (round(c + (255 - c) * white) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def _darken(hex_color: str, k: float) -> str:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "#{:02x}{:02x}{:02x}".format(*(round(c * (1 - k)) for c in (r, g, b)))


def _ink(hex_color: str) -> str:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "#1C1C1E" if (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 > 0.62 else "#ffffff"


def clean_theme(value) -> dict:
    """{target: {accent, radius, font, density}} with only valid, non-default entries kept."""
    out: dict = {}
    for target in TARGETS:
        raw = (value or {}).get(target) or {}
        if not isinstance(raw, dict):
            continue
        t: dict = {}
        if (a := _hex(raw.get("accent"))):
            t["accent"] = a
        for k, lo, hi in (("radius", 0.5, 1.6), ("font", 0.85, 1.25)):
            try:
                n = float(raw.get(k))
                if lo <= n <= hi and abs(n - 1.0) > 0.001:
                    t[k] = round(n, 2)
            except (TypeError, ValueError):
                pass
        if raw.get("density") in DENSITIES and raw["density"] != "normal":
            t["density"] = raw["density"]
        if t:
            out[target] = t
    return out


def clean_css(value: str | None) -> str:
    css = str(value or "").strip()
    css = re.sub(r"</?script[^>]*>", "", css, flags=re.I)  # a style block cannot carry a script
    css = css.replace("</style", "<\\/style")
    return css[:20000]


def clean_overrides(value) -> dict:
    out: dict = {}
    for lang, rows in (value or {}).items():
        if lang in settings.langs and isinstance(rows, dict):
            clean = {str(k)[:120]: str(v)[:2000] for k, v in rows.items() if k and v is not None and str(v) != ""}
            if clean:
                out[lang] = clean
    return out


async def ensure(db: AsyncSession, *, force: bool = False) -> None:
    global _loaded_at
    if not force and _loaded_at and time.monotonic() - _loaded_at < TTL:
        return
    _cache["theme"] = clean_theme(await get_setting(db, "theme", {}) or {})
    _cache["custom_css"] = {t: clean_css((await get_setting(db, "custom_css", {}) or {}).get(t)) for t in TARGETS}
    _cache["text_overrides"] = clean_overrides(await get_setting(db, "text_overrides", {}) or {})
    _cache["product_defaults"] = {**PRODUCT_DEFAULTS, **{k: v for k, v in ((await get_setting(db, "product_defaults", {}) or {}).items()) if k in PRODUCT_DEFAULTS}}
    _cache["lot_defaults"] = {**LOT_DEFAULTS, **{k: v for k, v in ((await get_setting(db, "lot_defaults", {}) or {}).items()) if k in LOT_DEFAULTS}}
    i18n.set_overrides(_cache["text_overrides"])
    _loaded_at = time.monotonic()


def invalidate() -> None:
    global _loaded_at
    _loaded_at = 0.0


def theme() -> dict:
    return _cache["theme"]


def theme_css(target: str) -> str:
    """The :root overrides for a target, empty when the theme is untouched."""
    t = _cache["theme"].get(target) or {}
    decl = []
    if (a := t.get("accent")):
        decl += [f"--accent:{a}", f"--accent-ink:{_ink(a)}", f"--accent-soft:{_mix(a, 0.86)}", f"--accent-press:{_darken(a, 0.14)}"]
    if (r := t.get("radius")):
        decl.append(f"--r-scale:{r}")
    if (f := t.get("font")):
        decl.append(f"--font-scale:{f}")
    css = ":root{" + ";".join(decl) + "}" if decl else ""
    if t.get("radius"):
        css += ":root{--r-card:calc(18px * var(--r-scale));--r-ctl:calc(12px * var(--r-scale));--r-chip:calc(10px * var(--r-scale));--r-sm:calc(8px * var(--r-scale))}"
    if t.get("font"):
        css += "html{font-size:calc(100% * var(--font-scale))}"
    if t.get("density") == "compact":
        css += ":root{--density:.86}.card,.fsection,.tile-body{padding-block:calc(14px * .86)}"
    elif t.get("density") == "comfortable":
        css += ":root{--density:1.15}.card,.fsection,.tile-body{padding-block:calc(16px * 1.15)}"
    return css


def custom_css(target: str) -> str:
    return _cache["custom_css"].get(target) or ""


def ui_css(target: str) -> str:
    """Everything a page injects after its stylesheets: the theme overrides, then the staff's own CSS."""
    return theme_css(target) + "\n" + custom_css(target)


def product_defaults() -> dict:
    return dict(_cache["product_defaults"] or PRODUCT_DEFAULTS)


def lot_defaults() -> dict:
    return dict(_cache["lot_defaults"] or LOT_DEFAULTS)
