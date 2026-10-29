"""Admin panel pages (server-rendered). Page modules register routes on `router`."""
from fastapi import APIRouter

router = APIRouter(tags=["admin"])

from app.admin import (  # noqa: E402,F401
    ads,
    articles,
    auctions,
    auth,
    brands,
    customers,
    dashboard,
    orders,
    products,
    reports,
    settings_pages,
    staff,
    support,
)
