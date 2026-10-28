from fastapi import Request
from sqlalchemy import func, select

from app.deps import DB, CurrentUser, Lang
from app.enums import AuctionStatus
from app.models import Auction, Product
from app.services import auctions, catalog
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
    return render(
        request,
        "miniapp/home.html",
        {
            "lang": lang, "arrivals": arrivals, "lots": lots, "delivery": delivery, "payment": payment,
            "in_stock_models": in_stock_models, "live_auctions": live_auctions,
        },
    )
