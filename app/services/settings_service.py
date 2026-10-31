"""Runtime settings stored in the DB (admin-editable), with sane defaults."""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Setting

DEFAULTS: dict[str, dict[str, Any]] = {
    "advance_percent": {"v": 30, "d": "Advance payment percent (30/70 rule)"},
    "currency": {"v": "USD", "d": "Default currency"},
    "working_hours": {"v": {"uz": "Душанба–Шанба, 09:00–19:00 (Пекин вақти)", "ru": "Пн–Сб, 09:00–19:00 (Пекин)", "en": "Mon–Sat, 09:00–19:00 (Beijing time)"}, "d": "Admin working hours"},
    "reply_time": {"v": {"uz": "Одатда 1–3 соат ичида жавоб берамиз", "ru": "Обычно отвечаем в течение 1–3 часов", "en": "We usually reply within 1–3 hours"}, "d": "Expected reply time"},
    "delivery_text": {"v": {
        "uz": "Гуанчжоу, Шэньчжэнь ва Иву шаҳарларидаги карго омборига етказиш бепул. Урумчи каби узоқ шаҳарларга пуллик. Ўзбекистонга етказиш тўлиқ тўловдан кейин тахминан 20 кун (кафолатланган сана эмас).",
        "ru": "Доставка до карго-складов в Гуанчжоу, Шэньчжэне и Иу бесплатна. В дальние города (например, Урумчи) — платно. Доставка в Узбекистан занимает примерно 20 дней после полной оплаты (срок не гарантирован).",
        "en": "Free delivery to cargo warehouses in Guangzhou, Shenzhen and Yiwu. Remote cities (e.g. Urumqi) are paid. Delivery to Uzbekistan takes about 20 days after full payment (not a guaranteed date)."
    }, "d": "Delivery terms shown on product and checkout"},
    "payment_text": {"v": {
        "uz": "Тўлов тартиби: 30% аванс, дисклар текширилгач ва сиз натижаларни тасдиқлагач — 70% қолдиқ. Тўлиқ тўловсиз юк жўнатилмайди. Тўлов реквизитлари буюртма тасдиқлангандан кейин юборилади.",
        "ru": "Порядок оплаты: 30% аванс, после проверки дисков и вашего подтверждения — 70% остаток. Без полной оплаты груз не отправляется. Реквизиты высылаются после подтверждения заказа.",
        "en": "Payment: 30% advance, then 70% balance after the drives are tested and you confirm the results. Nothing ships without full payment. Payment details are sent after the order is confirmed."
    }, "d": "Payment terms"},
    "payment_methods": {"v": [{"name": "USDT (TRC20)", "details": ""}, {"name": "Bank transfer", "details": ""}], "d": "Payment methods & details (sent to customer)"},
    "auction_deposit_default": {"v": 0, "d": "Default auction deposit amount (0 = no deposit)"},
    "auction_extension_seconds": {"v": 120, "d": "Anti-sniping extension"},
    "free_cities": {"v": ["Guangzhou", "Shenzhen", "Yiwu"], "d": "Free delivery cities"},
    "warehouse_address": {"v": "", "d": "Warehouse address (to be provided)"},
    "wd_check_url": {"v": "https://support-en.wd.com/app/warrantystatusweb", "d": "WD warranty check"},
    "seagate_check_url": {"v": "https://www.seagate.com/support/warranty-and-replacements/", "d": "Seagate warranty check"},
    "support_group_id": {"v": None, "d": "Telegram group id where support messages are mirrored"},
    "direction_images": {"v": {}, "d": "Series page: a picture per catalogue direction {colour: {filename, thumb}}"},
    "dir_slider_style": {"v": "coverflow", "d": "Mini App home: how the directions slider moves (coverflow | orbit | stack | fan)"},
    "slider_seconds": {"v": 7, "d": "Mini App home slider: seconds a slide stays (banners can set their own)"},
    "banner_slider_style": {"v": "parallax", "d": "Mini App home slider: how the banners change (parallax | cube | flip | stack | fade | peek)"},
    "capacity_presets": {"v": [500, 1000, 2000, 3000, 4000, 6000, 8000, 10000, 12000, 14000, 16000, 18000, 20000], "d": "Capacity chips (GB) shown in catalogue filters and product form"},
}


async def get_setting(db: AsyncSession, key: str, default: Any = None) -> Any:
    row = await db.get(Setting, key)
    if row is not None and isinstance(row.value, dict) and "v" in row.value:
        return row.value["v"]
    if key in DEFAULTS:
        return DEFAULTS[key]["v"]
    return default


async def get_all_settings(db: AsyncSession) -> dict[str, Any]:
    out = {k: v["v"] for k, v in DEFAULTS.items()}
    rows = (await db.execute(select(Setting))).scalars().all()
    for r in rows:
        if isinstance(r.value, dict) and "v" in r.value:
            out[r.key] = r.value["v"]
    return out


async def set_setting(db: AsyncSession, key: str, value: Any, description: str | None = None) -> None:
    row = await db.get(Setting, key)
    if row is None:
        row = Setting(key=key, value={"v": value}, description=description or DEFAULTS.get(key, {}).get("d"))
        db.add(row)
    else:
        row.value = {"v": value}
        if description:
            row.description = description
    await db.flush()
