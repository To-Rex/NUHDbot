"""Cart lives in the signed session cookie: {"cart": {"<product_id>": qty}}. Small, fast, no DB writes."""
from fastapi import Request, Response

from app.security import load_session, sign_session

COOKIE = "nuhd_session"


def read_session(request: Request) -> dict:
    return load_session(request.cookies.get(COOKIE)) or {}


def write_session(response: Response, data: dict, *, secure: bool, max_age: int) -> None:
    response.set_cookie(COOKIE, sign_session(data), max_age=max_age, httponly=True, samesite="none" if secure else "lax", secure=secure, path="/")


def get_cart(session: dict) -> dict[int, int]:
    raw = session.get("cart") or {}
    out: dict[int, int] = {}
    for k, v in raw.items():
        try:
            pid, qty = int(k), int(v)
        except (TypeError, ValueError):
            continue
        if qty > 0:
            out[pid] = qty
    return out


def set_cart(session: dict, cart: dict[int, int]) -> dict:
    session["cart"] = {str(k): v for k, v in cart.items() if v > 0}
    return session
