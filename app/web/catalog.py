from fastapi import Request

from app.deps import DB, CurrentUser, Lang
from app.enums import Condition, FormFactor, Interface, Purpose, TestStatus
from app.services import catalog
from app.services.catalog import CAPACITY_PRESETS_GB
from app.templating import render
from app.web.router import router


def _filter_ctx(f: catalog.CatalogFilters, facets: dict) -> dict:
    return {
        "f": f,
        "facets": facets,
        "capacity_presets": [g for g in CAPACITY_PRESETS_GB if any(g == c for c, _ in facets["capacities"])] or [c for c, _ in facets["capacities"]],
        "conditions": list(Condition),
        "purposes": list(Purpose),
        "interfaces": list(Interface),
        "form_factors": list(FormFactor),
        "tests": list(TestStatus),
    }


@router.get("/catalog")
async def catalog_page(request: Request, db: DB, user: CurrentUser, lang: Lang):
    f = catalog.parse_filters(request.query_params)
    products, total = await catalog.list_products(db, f)
    partial = request.query_params.get("partial")
    has_more = f.page * catalog.PAGE_SIZE < total
    ctx = {"lang": lang, "products": products, "total": total, "has_more": has_more, "next_page": f.page + 1, "page_title": None}
    if partial == "grid" or (request.headers.get("HX-Request") == "true" and request.headers.get("HX-Target") in ("grid", "grid-more")):
        ctx["f"] = f
        tpl = "miniapp/partials/product_grid.html" if request.headers.get("HX-Target") != "grid-more" and partial != "more" else "miniapp/partials/product_grid_more.html"
        return render(request, tpl, ctx)
    facets = await catalog.facets(db)
    ctx.update(_filter_ctx(f, facets))
    ctx["page_title"] = None
    return render(request, "miniapp/catalog.html", ctx)


@router.get("/new")
async def new_arrivals(request: Request, db: DB, user: CurrentUser, lang: Lang):
    products = await catalog.new_arrivals(db, limit=40)
    return render(request, "miniapp/new.html", {"lang": lang, "products": products, "page_title": None, "back_url": "/app/home"})
