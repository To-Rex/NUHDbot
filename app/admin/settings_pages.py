
from fastapi import Depends, Request
from sqlalchemy import select

from app.admin.common import ADMIN, DB, back, f_i18n, f_int, f_opt, f_str, render, staff_dep
from app.admin.router import router
from app.i18n import pick, t
from app.models import City, Country, User
from app.services import audit
from app.services.settings_service import DEFAULTS, get_all_settings, set_setting

I18N_KEYS = ("working_hours", "reply_time", "delivery_text", "payment_text")
NUM_KEYS = ("advance_percent", "auction_deposit_default", "auction_extension_seconds")
STR_KEYS = ("currency", "warehouse_address", "wd_check_url", "seagate_check_url")


@router.get("/settings")
async def settings_page(request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    values = await get_all_settings(db)
    return render(request, staff, "admin/settings/index.html", {"page_title": t(staff.lang, "admin.set.title"), "v": values, "defaults": DEFAULTS, "i18n_keys": I18N_KEYS, "num_keys": NUM_KEYS, "str_keys": STR_KEYS})


@router.post("/settings")
async def settings_save(request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    form = await request.form()
    before = await get_all_settings(db)
    for k in NUM_KEYS:
        await set_setting(db, k, f_int(form, k, before.get(k)))
    for k in STR_KEYS:
        await set_setting(db, k, f_str(form, k))
    for k in I18N_KEYS:
        await set_setting(db, k, f_i18n(form, k))
    names, details = form.getlist("pm_name"), form.getlist("pm_details")
    await set_setting(db, "payment_methods", [{"name": n.strip(), "details": d.strip()} for n, d in zip(names, details, strict=False) if n.strip()])
    await set_setting(db, "free_cities", [c.strip() for c in (form.get("free_cities") or "").split(",") if c.strip()])
    sg = f_opt(form, "support_group_id")
    await set_setting(db, "support_group_id", int(sg) if sg and sg.lstrip("-").isdigit() else None)
    raw_caps = [c.strip() for c in (form.get("capacity_presets") or "").replace(";", ",").split(",") if c.strip()]
    bad = [c for c in raw_caps if not c.isdigit() or not (100 <= int(c) <= 100000)]
    if bad:
        return back(request, "/admin/settings", t(staff.lang, "admin.set.capacity_invalid", v=", ".join(bad)), "bad")
    if raw_caps:
        await set_setting(db, "capacity_presets", sorted({int(c) for c in raw_caps}))
    after = await get_all_settings(db)
    changed = {k: after[k] for k in after if before.get(k) != after[k]}
    await audit.log(db, staff.id, "settings.update", "settings", None, {k: before.get(k) for k in changed}, changed)
    await db.commit()
    return back(request, "/admin/settings", t(staff.lang, "admin.set.saved"))


@router.get("/settings/geo")
async def geo_page(request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    countries = (await db.execute(select(Country).order_by(Country.sort, Country.code))).scalars().all()
    cities = (await db.execute(select(City).order_by(City.country_code, City.sort, City.id))).scalars().all()
    by_country: dict[str, list[City]] = {}
    regions: dict[str, list[str]] = {}
    for c in cities:
        by_country.setdefault(c.country_code, []).append(c)
        if c.region:
            label = pick(c.region, staff.lang)
            if label and label not in regions.setdefault(c.country_code, []):
                regions[c.country_code].append(label)
    return render(request, staff, "admin/settings/geo.html", {"page_title": t(staff.lang, "admin.set.geo"), "countries": countries, "by_country": by_country, "regions": regions})


@router.post("/settings/geo/country")
async def geo_country(request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    form = await request.form()
    code = f_str(form, "code", maxlen=2).upper()
    action = form.get("action")
    c = await db.get(Country, code) if code else None
    if action == "toggle" and c:
        c.is_active = not c.is_active
    elif action == "add" and code and not c:
        name = f_str(form, "name", maxlen=60)
        db.add(Country(code=code, name={"uz": name, "ru": name, "en": name}, flag=f_str(form, "flag", maxlen=8), phone_code=f_str(form, "phone_code", maxlen=8), sort=f_int(form, "sort", 50) or 50))
    await audit.log(db, staff.id, f"geo.country.{action}", "country", code)
    await db.commit()
    return back(request, "/admin/settings/geo", t(staff.lang, "admin.flash.saved"))


@router.post("/settings/geo/city")
async def geo_city(request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    form = await request.form()
    action = form.get("action")
    op = form.get("op") or ""
    if ":" in op:  # compact per-country form: op=toggle:<id> | delete:<id>
        action, _, cid_raw = op.partition(":")
        form = dict(form)
        form["id"] = cid_raw
        form["action"] = action
    if action == "add":
        code = f_str(form, "country_code", maxlen=2).upper()
        name = f_str(form, "name", maxlen=100)
        region = f_str(form, "region", maxlen=100)
        if code and name:
            # reuse the stored i18n region dict when the typed label matches an existing region of this country
            region_dict = None
            if region:
                for existing in (await db.execute(select(City).where(City.country_code == code, City.region.is_not(None)))).scalars():
                    if pick(existing.region, staff.lang) == region:
                        region_dict = existing.region
                        break
                region_dict = region_dict or {"uz": region, "uzl": region, "ru": region, "en": region}
            langs_name = {"uz": name, "uzl": name, "ru": name, "en": name}
            db.add(City(country_code=code, name=langs_name, region=region_dict, sort=f_int(form, "sort", 500) or 500))
    else:
        cid = f_int(form, "id", None)
        c = await db.get(City, cid) if cid else None
        if c and action == "toggle":
            c.is_active = not c.is_active
        elif c and action == "delete":
            await db.delete(c)
    await audit.log(db, staff.id, f"geo.city.{action}", "city", form.get("id") or form.get("name"))
    await db.commit()
    return back(request, "/admin/settings/geo", t(staff.lang, "admin.flash.saved"))
