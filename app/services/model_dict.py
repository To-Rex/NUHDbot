"""Model dictionary: drive models per brand, entered in bulk (one per line) and offered in the product form autocomplete."""
import re

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import FormFactor, Interface
from app.models import Brand, BrandModel, Product

MAX_LINES = 500
_SEP = re.compile(r"\s*[|;,\t]\s*")
_CAP = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(tb|gb|тб|гб)$", re.I)


def norm_key(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip()).upper()


def parse_capacity_token(tok: str) -> int | None:
    """'4TB' → 4000, '1.5 TB' → 1500, '500GB' → 500; None when the token is not a capacity."""
    m = _CAP.match(tok.strip())
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    gb = value * (1000 if m.group(2).lower() in ("tb", "тб") else 1)
    return int(round(gb)) if 0 < gb <= 1_000_000 else None


def parse_line(line: str) -> dict | None:
    """`MODEL | 4TB | SATA | 3.5 | Series` in any order after the name; separators: | ; , or tab.

    A bare `MODEL 4TB SkyHawk` also works: a trailing capacity token is picked out, the rest becomes the series.
    """
    line = line.strip().lstrip("-•*· ").strip()
    if not line or line.startswith("#"):
        return None
    parts = [p for p in _SEP.split(line) if p]
    name, extras = parts[0], parts[1:]
    if not extras:  # space-separated: name + optional specs
        words = name.split()
        name, rest = words[0], words[1:]
        extras = rest
    spec: dict = {"name": name[:120], "capacity_gb": None, "interface": None, "form_factor": None, "series": None}
    series_words: list[str] = []
    for tok in extras:
        cap = parse_capacity_token(tok)
        if cap:
            spec["capacity_gb"] = cap
        elif tok.upper() in Interface.__members__ or tok.upper() in [i.value for i in Interface]:
            spec["interface"] = Interface(tok.upper()).value
        elif tok.replace('"', "").replace("″", "") in [f.value for f in FormFactor]:
            spec["form_factor"] = tok.replace('"', "").replace("″", "")
        else:
            series_words.append(tok)
    if series_words:
        spec["series"] = " ".join(series_words)[:60]
    return spec


async def list_models(db: AsyncSession, brand_id: int | None = None) -> list[BrandModel]:
    stmt = select(BrandModel).order_by(BrandModel.brand_id, BrandModel.name)
    if brand_id is not None:
        stmt = stmt.where(BrandModel.brand_id == brand_id)
    return list((await db.execute(stmt)).scalars().all())


async def counts(db: AsyncSession) -> dict[int, int]:
    rows = (await db.execute(select(BrandModel.brand_id, func.count()).group_by(BrandModel.brand_id))).all()
    return {bid: n for bid, n in rows}


async def bulk_add(db: AsyncSession, brand: Brand, text: str) -> tuple[list[BrandModel], int]:
    """Add every parsable line that is not already in the brand's dictionary. Returns (added, skipped)."""
    existing = {m.key: m for m in await list_models(db, brand.id)}
    added: list[BrandModel] = []
    skipped = 0
    for raw in text.splitlines()[:MAX_LINES]:
        spec = parse_line(raw)
        if not spec:
            continue
        key = norm_key(spec["name"])
        if key in existing:
            cur = existing[key]  # fill specs that were empty before; never overwrite
            for f in ("capacity_gb", "interface", "form_factor", "series"):
                if spec[f] and not getattr(cur, f):
                    setattr(cur, f, spec[f])
            skipped += 1
            continue
        m = BrandModel(brand_id=brand.id, key=key, **spec)
        db.add(m)
        existing[key] = m
        added.append(m)
    await db.flush()
    return added, skipped


async def get_model(db: AsyncSession, mid: int) -> BrandModel | None:
    return await db.get(BrandModel, mid)


async def delete_model(db: AsyncSession, m: BrandModel) -> None:
    await db.delete(m)
    await db.flush()


def as_dict(m: BrandModel) -> dict:
    return {"id": m.id, "b": m.brand_id, "m": m.name, "cap": m.capacity_gb, "if": m.interface, "ff": m.form_factor, "series": m.series, "src": "dict"}


async def known_models(db: AsyncSession) -> list[dict]:
    """Distinct real models already entered, newest first, with the specs of their latest product (for autocomplete + prefill)."""
    seen, out = set(), []
    for m in await list_models(db):  # staff-entered dictionary first
        seen.add((m.brand_id, m.key))
        out.append({**as_dict(m), "rpm": None, "cache": None})
    rows = (await db.execute(select(Product.brand_id, Product.model, Product.capacity_gb, Product.interface, Product.form_factor, Product.rpm, Product.cache_mb, Product.series).order_by(Product.updated_at.desc(), Product.id.desc()))).all()
    for brand_id, model, cap, iface, ff, rpm, cache, series in rows:
        key = (brand_id, norm_key(model))
        if not model.strip() or key in seen:
            continue
        seen.add(key)
        out.append({"b": brand_id, "m": model.strip(), "cap": cap, "if": iface.value, "ff": ff.value, "rpm": rpm, "cache": cache, "series": series, "src": "prod"})
    return out
