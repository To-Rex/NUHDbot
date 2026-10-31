"""Admin panel pages (server-rendered). Page modules register routes on `router`."""
from fastapi import APIRouter

router = APIRouter(tags=["admin"])

from app.admin import (  # noqa: E402,F401
    ads,
    articles,
    auctions,
    auth,
    banners,
    brands,
    currencies,
    customers,
    dashboard,
    models_dict,
    orders,
    products,
    reports,
    series_dict,
    settings_pages,
    staff,
    support,
)
