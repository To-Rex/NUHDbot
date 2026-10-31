from collections import Counter
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import func, select

from app.deps import DB, CurrentUser, Lang, redirect
from app.enums import COLOR_DIRECTION, AuctionStatus, ProductColor, Purpose
from app.models import Auction, Banner, Product
from app.services import auctions, catalog, discounts, storage
from app.services import banners as banner_service
from app.services import series as series_service
from app.services.settings_service import get_setting
from app.templating import render
from app.web.router import router


@router.get("/home")
async def home(request: Request, db: DB, user: CurrentUser, lang: Lang):
    arrivals = await catalog.new_arrivals(db, limit=10)
    lots = await auctions.list_auctions(db, statuses=(AuctionStatus.LIVE, AuctionStatus.SCHEDULED), limit=3)
    delivery = await get_setting(db, "delivery_text")
    payment = await get_setting(db, "payment_text")
    in_stock_models = (
        await db.execute(select(func.count()).select_from(Product).where(Product.is_active.is_(True), Product.stock - Product.reserved > 0))
    ).scalar_one()
    live_auctions = (await db.execute(select(func.count()).select_from(Auction).where(Auction.status == AuctionStatus.LIVE))).scalar_one()
    in_stock = (Product.is_active.is_(True), Product.stock - Product.reserved > 0)
    # shortcuts only for what is actually on the shelf
    capacities = (
        await db.execute(select(Product.capacity_gb, func.count()).where(*in_stock).group_by(Product.capacity_gb).order_by(Product.capacity_gb).limit(10))
    ).all()
    use_counts: Counter[str] = Counter()
    for (purposes,) in (await db.execute(select(Product.purposes).where(*in_stock))).all():
        use_counts.update(set(purposes or []))
    uses = sorted(((u, use_counts[u.value]) for u in Purpose if use_counts[u.value]), key=lambda x: -x[1])[:4]
    popular = (await db.execute(select(Product).where(*in_stock).order_by(Product.views.desc(), Product.id.desc()).limit(4))).scalars().unique().all()
    month_ago = datetime.now(UTC) - timedelta(days=30)
    new_count = (await db.execute(select(func.count()).select_from(Product).where(Product.is_active.is_(True), Product.arrived_at >= month_ago))).scalar_one()
    return render(
        request,
        "miniapp/home.html",
        {
            "lang": lang, "arrivals": arrivals, "lots": lots, "delivery": delivery, "payment": payment,
            "in_stock_models": in_stock_models, "live_auctions": live_auctions, "capacities": capacities, "uses": uses, "popular": popular, "new_count": new_count,
            "kind_icons": banner_service.KIND_ICONS, "directions": await _directions(db),
            "dir_style": series_service.clean_style(await get_setting(db, "dir_slider_style")),
            "dir_shape": banner_service.clean_shape(await get_setting(db, "dir_slider_shape")), **(await _slider(db)),
        },
    )


async def _directions(db) -> list[dict]:
    """The six catalogue directions for the home 3D slider: the picture set on the Series page and how many models each has."""
    counts = dict(
        (await db.execute(select(Product.color, func.count()).where(Product.is_active.is_(True), Product.color.is_not(None)).group_by(Product.color))).all()
    )
    pics = await get_setting(db, "direction_images") or {}
    return [
        {"color": c.value, "name": COLOR_DIRECTION[c], "n": counts.get(c.value, 0),
         "img": storage.url(pic.get("thumb") or pic.get("filename")) if (pic := pics.get(c.value)) else None}
        for c in ProductColor
    ]


async def _slider(db) -> dict:
    """Live banners, the products of offer banners, and old prices for single-product ones."""
    banners = await banner_service.live(db)
    offers = {b.id: await banner_service.offer(db, b) for b in banners if banner_service.is_offer(b)}
    singles = await discounts.price_drops(db, [b.product_id for b in banners if b.product_id and not banner_service.is_offer(b)])
    seconds = banner_service.clean_seconds(await get_setting(db, "slider_seconds"), banner_service.SECONDS_DEFAULT)
    style = banner_service.clean_style(await get_setting(db, "banner_slider_style"))
    shape = banner_service.clean_shape(await get_setting(db, "banner_slider_shape"))
    return {"banners": banners, "offers": offers, "single_drops": singles, "slider_seconds": seconds, "slider_style": style, "slider_shape": shape}


@router.get("/offers/{bid}")
async def offers_page(bid: int, request: Request, db: DB, user: CurrentUser, lang: Lang):
    """What a banner with several products opens: those products (or every discounted one), with their old prices."""
    b = await db.get(Banner, bid)
    if b is None or not banner_service.is_offer(b):
        return redirect(request, "/app/home")
    live = banner_service.status(b) == "live"
    products, drops = await banner_service.offer(db, b) if live else ([], {})
    return render(request, "miniapp/offers.html", {
        "lang": lang, "b": b, "live": live, "products": products, "drops": drops, "percent": discounts.percent,
        "kind_icons": banner_service.KIND_ICONS, "back_url": "/app/home",
    })


@router.get("/promo/{bid}")
async def promo_open(bid: int, request: Request, db: DB):
    """A tap on a home slider banner: count it, then open what it points to."""
    b = await db.get(Banner, bid)
    if b is None:
        return redirect(request, "/app/home")
    await banner_service.count_click(db, bid)
    await db.commit()
    return redirect(request, banner_service.target(b) or "/app/home")
