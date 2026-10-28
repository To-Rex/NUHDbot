from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import OrderStatus, PaymentStatus, ThreadStatus
from app.i18n import t
from app.models import Order, Payment, SupportThread, User
from app.services import reports
from app.templating import money

router = Router(name="staff")


@router.message(Command("stats"))
async def cmd_stats(message: Message, user: User, db: AsyncSession) -> None:
    if not user.is_staff:
        await message.answer(t(user.lang, "bot.no_access"))
        return
    d = await reports.dashboard(db, days=30)
    await message.answer(
        t(user.lang, "bot.stats", days=d["days"], orders=d["orders_total"], active=d["active_orders"], awaiting=d["awaiting_admin"],
          revenue=money(d["revenue"]), pending=d["pending_payments"], disks=d["disks_sold"], customers=d["customers"],
          products=d["products"], low=d["low_stock"], live=d["live_auctions"])
    )


@router.message(Command("pending"))
async def cmd_pending(message: Message, user: User, db: AsyncSession) -> None:
    if not user.is_staff:
        await message.answer(t(user.lang, "bot.no_access"))
        return
    orders = (await db.execute(select(func.count()).select_from(Order).where(Order.status == OrderStatus.AWAITING_ADMIN))).scalar_one()
    payments = (await db.execute(select(func.count()).select_from(Payment).where(Payment.status == PaymentStatus.PENDING))).scalar_one()
    threads = (await db.execute(select(func.count()).select_from(SupportThread).where(SupportThread.status == ThreadStatus.OPEN, SupportThread.unread_for_staff > 0))).scalar_one()
    await message.answer(t(user.lang, "bot.pending", orders=orders, payments=payments, threads=threads))
