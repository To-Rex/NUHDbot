"""Shared helpers for Mini App routes."""
import json

from fastapi import Request, Response

from app.config import settings
from app.deps import is_secure
from app.services.cart import effective_cart, read_session, write_session
from app.services.cart import persist as persist_cart


def hx_trigger(response: Response, **events) -> Response:
    """Attach HX-Trigger events (toast / haptic / confetti / cartUpdated)."""
    existing = response.headers.get("HX-Trigger")
    payload = json.loads(existing) if existing else {}
    payload.update(events)
    response.headers["HX-Trigger"] = json.dumps(payload)  # ASCII-only: HTTP headers are latin-1
    return response


def toast(response: Response, msg: str, type_: str = "", haptic: str | None = None) -> Response:
    ev = {"toast": {"msg": msg, "type": type_}}
    if haptic:
        ev["haptic"] = haptic
    return hx_trigger(response, **ev)


def save_cart(request: Request, response: Response, cart: dict[int, int]) -> Response:
    sess = read_session(request)
    sess["cart"] = {str(k): v for k, v in cart.items() if v > 0}
    uid = getattr(request.state, "user", None)
    if uid is not None and "uid" not in sess:
        sess["uid"] = uid.id
    write_session(response, sess, secure=is_secure(), max_age=settings.session_max_age)
    request.state.session = sess
    return response


def current_cart(request: Request) -> dict[int, int]:
    """The visitor's cart: the session's, or the signed-in user's kept one when the session has none (a new device)."""
    sess = getattr(request.state, "session", None)
    if sess is None:
        sess = read_session(request)
    return effective_cart(sess, getattr(request.state, "user", None))


async def store_cart(request: Request, response: Response, db, cart: dict[int, int]) -> Response:
    """Save the cart in the session cookie and mirror it on the signed-in user's row (committed)."""
    save_cart(request, response, cart)
    user = getattr(request.state, "user", None)
    if user is not None:
        persist_cart(user, cart)
        if db.dirty:
            await db.commit()
    return response


def safe_next(value: str | None, default: str = "/app/home") -> str:
    return value if value and value.startswith("/app") and "//" not in value else default


# ---- extra Jinja filters owned by the Mini App ----
from urllib.parse import quote_plus  # noqa: E402

from app.templating import env  # noqa: E402


def _qs(params: dict) -> str:
    parts = []
    for k, v in params.items():
        if v is None or v == "" or v is False:
            continue
        if isinstance(v, (list, tuple, set)):
            parts.extend(f"{quote_plus(str(k))}={quote_plus(str(x))}" for x in v)
        else:
            parts.append(f"{quote_plus(str(k))}={quote_plus(str(v))}")
    return "&".join(parts)


def _initials(name: str) -> str:
    parts = [p for p in (name or "").split() if p]
    return "".join(p[0].upper() for p in parts[:2]) or "?"


def _anon(user) -> str:
    """Anonymised bidder label: first name + last initial."""
    if user is None:
        return "—"
    first = (user.first_name or user.tg_username or "User").strip()
    last = (user.last_name or "").strip()
    return f"{first} {last[0]}." if last else first


env.filters["qs"] = _qs
env.filters["initials"] = _initials
env.filters["anon"] = _anon
