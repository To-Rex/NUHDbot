"""Mini App pages (server-rendered). Each module registers its routes on `router` at import time."""
from fastapi import APIRouter

router = APIRouter(tags=["miniapp"])

from app.web import (  # noqa: E402,F401
    auctions,
    auth,
    cart,
    catalog,
    checkout,
    home,
    info,
    orders,
    products,
    profile,
    register,
    support,
)
