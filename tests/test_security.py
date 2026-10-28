import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from app.config import settings
from app.security import hash_password, load_session, sign_session, verify_password, verify_telegram_init_data


def _signed(payload: dict, token: str) -> str:
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(payload.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urlencode({**payload, "hash": h})


def test_init_data_roundtrip():
    user = json.dumps({"id": 777, "first_name": "Ali", "language_code": "uz"}, separators=(",", ":"))
    payload = {"auth_date": str(int(time.time())), "query_id": "AAE", "user": user}
    ok = verify_telegram_init_data(_signed(payload, settings.bot_token))
    assert ok and ok["user"]["id"] == 777
    assert verify_telegram_init_data(_signed(payload, "999:WRONG")) is None
    tampered = _signed(payload, settings.bot_token).replace("Ali", "Vali")
    assert verify_telegram_init_data(tampered) is None
    old = {"auth_date": str(int(time.time()) - 10 * 86400), "user": user}
    assert verify_telegram_init_data(_signed(old, settings.bot_token)) is None
    assert verify_telegram_init_data("") is None


def test_session_and_passwords():
    tok = sign_session({"uid": 5, "cart": {"1": 2}})
    assert load_session(tok) == {"uid": 5, "cart": {"1": 2}}
    assert load_session(tok + "x") is None
    h = hash_password("S3cret!")
    assert verify_password("S3cret!", h) and not verify_password("nope", h) and not verify_password("x", None)
