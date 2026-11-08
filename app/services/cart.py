"""Cart lives in the signed session cookie: {"cart": {"<product_id>": qty}}. Small, fast, no DB writes on every read.

A signed-in customer's cart is also mirrored on their user row (users.cart / cart_at) whenever it changes: the staff see
it on the customer's card, and a new device (an empty session) starts from it."""
from datetime import UTC, datetime

from fastapi import Request, Response

from app.security import load_session, sign_session

COOKIE = "nuhd_session"


def read_session(request: Request) -> dict:
    return load_session(request.cookies.get(COOKIE)) or {}


def write_session(response: Response, data: dict, *, secure: bool, max_age: int) -> None:
    response.set_cookie(COOKIE, sign_session(data), max_age=max_age, httponly=True, samesite="none" if secure else "lax", secure=secure, path="/")


def _clean(raw) -> dict[int, int]:
    out: dict[int, int] = {}
    for k, v in (raw or {}).items():
        try:
            pid, qty = int(k), int(v)
        except (TypeError, ValueError):
            continue
        if qty > 0:
            out[pid] = qty
    return out


def get_cart(session: dict) -> dict[int, int]:
    return _clean(session.get("cart"))


def set_cart(session: dict, cart: dict[int, int]) -> dict:
    session["cart"] = {str(k): v for k, v in cart.items() if v > 0}
    return session


def user_cart(user) -> dict[int, int]:
    """The cart kept on the user row (empty when none)."""
    return _clean(getattr(user, "cart", None)) if user is not None else {}


def effective_cart(session: dict, user) -> dict[int, int]:
    """What this visitor's cart is: the session's, or — when the session has none — the signed-in user's kept one."""
    return get_cart(session) or user_cart(user)


def persist(user, cart: dict[int, int]) -> None:
    """Mirror the cart on the user row (the caller commits). Nothing to write when it already matches."""
    if user is None:
        return
    new = {str(k): v for k, v in cart.items() if v > 0}
    if (user.cart or {}) == new and (new or user.cart_at):
        return
    user.cart = new or None
    user.cart_at = datetime.now(UTC)
