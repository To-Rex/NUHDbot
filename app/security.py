import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

import bcrypt
from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import settings

_serializer = URLSafeTimedSerializer(settings.secret_key, salt="nuhd-session")


def sign_session(data: dict) -> str:
    return _serializer.dumps(data)


def load_session(token: str | None, max_age: int | None = None) -> dict | None:
    if not token:
        return None
    try:
        return _serializer.loads(token, max_age=max_age or settings.session_max_age)
    except BadSignature:
        return None


def verify_telegram_init_data(init_data: str, max_age_seconds: int = 60 * 60 * 24) -> dict | None:
    """Validate Telegram WebApp initData (HMAC-SHA256). Returns parsed dict with 'user' or None."""
    if not init_data or not settings.bot_token:
        return None
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", settings.bot_token.encode(), hashlib.sha256).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, received_hash):
        return None
    auth_date = int(pairs.get("auth_date", "0") or 0)
    if auth_date and time.time() - auth_date > max_age_seconds:
        return None
    try:
        pairs["user"] = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError:
        pairs["user"] = {}
    return pairs


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False
