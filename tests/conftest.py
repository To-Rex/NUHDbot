"""Tests run against a throwaway Postgres database `nuhdbot_test` (created on demand)."""
import os
import subprocess
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest_asyncio

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://localhost:5432/nuhdbot_test")
os.environ["BOT_TOKEN"] = "123456:TEST_FAKE_TOKEN_FOR_HMAC"
os.environ["BOT_MODE"] = "off"
os.environ["DEBUG"] = "false"

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.enums import AuctionStatus, Condition, FormFactor, Interface, Role, TestStatus  # noqa: E402
from app.models import Auction, Base, Product, User  # noqa: E402


def _ensure_database() -> None:
    exists = subprocess.run(["psql", "-d", "postgres", "-tAc", "SELECT 1 FROM pg_database WHERE datname='nuhdbot_test'"], capture_output=True, text=True)
    if exists.stdout.strip() != "1":
        subprocess.run(["psql", "-d", "postgres", "-c", "CREATE DATABASE nuhdbot_test"], check=True, capture_output=True)


@pytest_asyncio.fixture(scope="session")
async def engine():
    _ensure_database()
    eng = create_async_engine(os.environ["DATABASE_URL"], poolclass=None)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await eng.dispose()


@pytest_asyncio.fixture
async def sessionmaker(engine):
    # clean tables between tests (fast truncate)
    async with engine.begin() as conn:
        tables = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
        await conn.exec_driver_sql(f"TRUNCATE {tables} RESTART IDENTITY CASCADE")
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def db(sessionmaker):
    async with sessionmaker() as s:
        yield s


async def make_user(db, tg_id: int = 1001, *, registered: bool = True, role: Role = Role.CUSTOMER) -> User:
    u = User(tg_id=tg_id, first_name=f"U{tg_id}", last_name="Test", phone=f"+99890{tg_id:07d}", country="UZ", city="Toshkent", lang="uz", role=role,
             registered_at=datetime.now(UTC) if registered else None)
    db.add(u)
    await db.flush()
    return u


async def make_product(db, *, stock: int = 50, min_order: int = 5, price: str = "40", full_box_only: bool = False, box_qty: int | None = 20) -> Product:
    p = Product(brand="Seagate", model="ST4000VX016", capacity_gb=4000, interface=Interface.SATA, form_factor=FormFactor.F35, condition=Condition.USED,
                purposes=["cctv"], price=Decimal(price), currency="USD", stock=stock, min_order=min_order, box_qty=box_qty, full_box_only=full_box_only,
                test_status=TestStatus.TESTED, seller_warranty_months=6)
    db.add(p)
    await db.flush()
    return p


async def make_auction(db, *, qty: int = 20, start: str = "500", step: str = "1", minutes: int = 30, status: AuctionStatus = AuctionStatus.LIVE) -> Auction:
    now = datetime.now(UTC)
    a = Auction(brand="WD", model="WD40PURZ", capacity_gb=4000, condition=Condition.NEW, qty=qty, currency="USD",
                start_price_total=Decimal(start), step_per_unit=Decimal(step), current_price_total=Decimal(start),
                starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(minutes=minutes), original_ends_at=now + timedelta(minutes=minutes), status=status)
    db.add(a)
    await db.flush()
    return a
