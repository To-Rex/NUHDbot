from fastapi import Request

from app.deps import DB, CurrentUser, Lang
from app.enums import AuctionStatus
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
    return render(
        request,
        "miniapp/home.html",
        {"lang": lang, "arrivals": arrivals, "lots": lots, "delivery": delivery, "payment": payment},
    )
