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


# Allowed forward transitions for staff. Admin may also jump to CANCELLED/DISPUTED from any active state.
ORDER_FLOW: dict[OrderStatus, tuple[OrderStatus, ...]] = {
    OrderStatus.NEW: (OrderStatus.AWAITING_ADMIN,),
    OrderStatus.AWAITING_ADMIN: (OrderStatus.AWAITING_ADVANCE,),
    OrderStatus.AWAITING_ADVANCE: (OrderStatus.ADVANCE_CONFIRMED,),
    OrderStatus.ADVANCE_CONFIRMED: (OrderStatus.TESTING,),
    OrderStatus.TESTING: (OrderStatus.TEST_READY,),
    OrderStatus.TEST_READY: (OrderStatus.AWAITING_CUSTOMER,),
    OrderStatus.AWAITING_CUSTOMER: (OrderStatus.AWAITING_BALANCE,),
    OrderStatus.AWAITING_BALANCE: (OrderStatus.PAID,),
    OrderStatus.PAID: (OrderStatus.PACKING,),
    OrderStatus.PACKING: (OrderStatus.SHIPPED,),
    OrderStatus.SHIPPED: (OrderStatus.DELIVERED,),
    OrderStatus.DELIVERED: (OrderStatus.COMPLETED,),
    OrderStatus.COMPLETED: (OrderStatus.RETURNED,),
    OrderStatus.CANCELLED: (),
    OrderStatus.RETURNED: (),
    OrderStatus.DISPUTED: (OrderStatus.CANCELLED, OrderStatus.RETURNED, OrderStatus.COMPLETED),
}

ACTIVE_ORDER_STATUSES = tuple(
    s for s in OrderStatus if s not in (OrderStatus.COMPLETED, OrderStatus.CANCELLED, OrderStatus.RETURNED)
)


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
