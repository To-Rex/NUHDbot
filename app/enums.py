from enum import StrEnum


class Lang(StrEnum):
    UZ = "uz"
    RU = "ru"
    EN = "en"


class Role(StrEnum):
    CUSTOMER = "customer"
    ADMIN = "admin"
    CATALOG = "catalog"
    WAREHOUSE = "warehouse"
    TESTER = "tester"
    ORDERS = "orders"
    FINANCE = "finance"
    MARKETING = "marketing"


STAFF_ROLES = {Role.ADMIN, Role.CATALOG, Role.WAREHOUSE, Role.TESTER, Role.ORDERS, Role.FINANCE, Role.MARKETING}


class Condition(StrEnum):
    NEW = "new"
    USED = "used"
    REFRESH = "refresh"


class Interface(StrEnum):
    SATA = "SATA"
    SAS = "SAS"


class FormFactor(StrEnum):
    F25 = "2.5"
    F35 = "3.5"


class Purpose(StrEnum):
    PC = "pc"
    CCTV = "cctv"
    NAS = "nas"
    SERVER = "server"
    STORAGE = "storage"


class ProductColor(StrEnum):
    """Catalogue colour by use (a shop recommendation, not an official standard); themes the product page."""
    BLUE = "blue"  # Desktop
    PURPLE = "purple"  # Surveillance
    RED = "red"  # NAS
    GOLD = "gold"  # Enterprise
    SILVER = "silver"  # Data Center
    BLACK = "black"  # Gaming


COLOR_DIRECTION = {
    ProductColor.BLUE: "Desktop", ProductColor.PURPLE: "Surveillance", ProductColor.RED: "NAS",
    ProductColor.GOLD: "Enterprise", ProductColor.SILVER: "Data Center", ProductColor.BLACK: "Gaming",
}
COLOR_EXAMPLES = {
    ProductColor.BLUE: "WD Blue, Seagate BarraCuda, Toshiba P300", ProductColor.PURPLE: "WD Purple, SkyHawk, Toshiba S300",
    ProductColor.RED: "WD Red, IronWolf, Toshiba N300", ProductColor.GOLD: "WD Gold, Seagate Exos, Ultrastar, Toshiba MG",
    ProductColor.SILVER: "WD White, Exos, Ultrastar", ProductColor.BLACK: "WD_BLACK, FireCuda HDD",
}


class TestStatus(StrEnum):
    UNTESTED = "untested"
    TESTING = "testing"
    TESTED = "tested"


class ImageKind(StrEnum):
    SAMPLE = "sample"
    REAL = "real"


class OrderStatus(StrEnum):
    NEW = "new"
    AWAITING_ADMIN = "awaiting_admin"
    AWAITING_ADVANCE = "awaiting_advance"
    ADVANCE_CONFIRMED = "advance_confirmed"
    TESTING = "testing"
    TEST_READY = "test_ready"
    AWAITING_CUSTOMER = "awaiting_customer"
    AWAITING_BALANCE = "awaiting_balance"
    PAID = "paid"
    PACKING = "packing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    RETURNED = "returned"
    DISPUTED = "disputed"


# The order journey has three stages — Order, Payment, Shipping — and a way out (cancel):
#   Order: NEW → AWAITING_ADMIN (the admin checks it and sends the offer, the customer accepts)
#   Payment: AWAITING_ADVANCE (awaiting payment of the full total; partial payments add up) → PAID
#   Shipping: PAID → SHIPPED (the end)
# The other values (testing, 30/70 balance, packing, delivered, completed, disputed, returned) only remain for old history rows;
# migration a3c9e5f1b207 moved every order out of them, and if one ever shows up it can still move on.
ORDER_FLOW: dict[OrderStatus, tuple[OrderStatus, ...]] = {
    OrderStatus.NEW: (OrderStatus.AWAITING_ADMIN,),
    OrderStatus.AWAITING_ADMIN: (OrderStatus.AWAITING_ADVANCE,),
    OrderStatus.AWAITING_ADVANCE: (OrderStatus.PAID,),
    OrderStatus.PAID: (OrderStatus.SHIPPED,),
    OrderStatus.SHIPPED: (),
    OrderStatus.CANCELLED: (),
    **{legacy: (OrderStatus.PAID,) for legacy in (OrderStatus.ADVANCE_CONFIRMED, OrderStatus.TESTING, OrderStatus.TEST_READY, OrderStatus.AWAITING_CUSTOMER, OrderStatus.AWAITING_BALANCE)},
    OrderStatus.PACKING: (OrderStatus.SHIPPED,),
    OrderStatus.DELIVERED: (),
    OrderStatus.COMPLETED: (),
    OrderStatus.RETURNED: (),
    OrderStatus.DISPUTED: (OrderStatus.CANCELLED,),
}
# the three stages and the statuses that make them up (the stepper on the admin order page, the dots in the Mini App)
ORDER_STAGES: tuple[tuple[str, tuple[OrderStatus, ...]], ...] = (
    ("order", (OrderStatus.NEW, OrderStatus.AWAITING_ADMIN)),
    ("pay", (OrderStatus.AWAITING_ADVANCE,)),
    ("ship", (OrderStatus.PAID,)),
)
PAYMENT_STAGE_STATUSES = tuple(s for s, nxt in ORDER_FLOW.items() if nxt == (OrderStatus.PAID,))  # waiting for money (incl. old 30/70 states)
FINISHED_ORDER_STATUSES = (OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.COMPLETED)  # shipped is the end of the journey
ACTIVE_ORDER_STATUSES = tuple(s for s in OrderStatus if s not in (*FINISHED_ORDER_STATUSES, OrderStatus.CANCELLED, OrderStatus.RETURNED))


def order_stage(status: OrderStatus) -> int:
    """1 Order, 2 Payment, 3 Shipping (paid, waiting to ship), 4 = all done (shipped); 0 for cancelled."""
    if status in FINISHED_ORDER_STATUSES:
        return len(ORDER_STAGES) + 1
    for n, (_, members) in enumerate(ORDER_STAGES, start=1):
        if status in members:
            return n
    return 2 if status in PAYMENT_STAGE_STATUSES else (3 if status == OrderStatus.PACKING else 0)


class PaymentKind(StrEnum):
    ADVANCE = "advance"
    BALANCE = "balance"
    DEPOSIT = "deposit"
    REFUND = "refund"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class AuctionStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    LIVE = "live"
    ENDED = "ended"
    CANCELLED = "cancelled"


class DepositStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REFUNDED = "refunded"
    APPLIED = "applied"


class ThreadStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class MessageKind(StrEnum):
    TEXT = "text"
    PHOTO = "photo"
    VIDEO = "video"
    DOCUMENT = "document"


class SubscriptionType(StrEnum):
    NEW_ARRIVALS = "new_arrivals"
    BRAND = "brand"
    CAPACITY = "capacity"
    PRICE_RANGE = "price_range"
    AUCTION = "auction"


class AdPostStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    SENT = "sent"
