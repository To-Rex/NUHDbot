"""The Translate button of every multilingual field: one language in, the others out of the assistant's model."""
import re

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from app.admin.common import DB, staff_dep
from app.admin.router import router
from app.config import settings
from app.enums import STAFF_ROLES
from app.i18n import t
from app.models import User
from app.services.assistant import llm
from app.services.assistant import translate as svc

ERRORS = {"no_api_key": "no_model", "bad_api_key": "no_model", "no_model": "no_model", "no_balance": "no_balance", "rate_limited": "rate_limited",
          "no_source": "no_source", "too_long": "too_long", "bad_answer": "bad_answer"}


@router.post("/translate")
async def translate_field(request: Request, db: DB, staff: User = Depends(staff_dep(*STAFF_ROLES))):
    """JSON in: {texts: {lang: text}, targets: [lang], source?: lang, kind?: input|textarea|code}. Out: {source, translations} or {error, message}."""
    try:
        payload = await request.json()
    except ValueError:
        payload = {}
    texts = {k: str(v or "") for k, v in (payload.get("texts") or {}).items() if k in settings.langs}
    targets = [c for c in (payload.get("targets") or []) if c in settings.langs]
    source = payload.get("source") if payload.get("source") in settings.langs else None
    kind = payload.get("kind") if payload.get("kind") in ("input", "textarea", "code") else "input"
    if not texts or not targets:
        return JSONResponse({"error": "no_source", "message": t(staff.lang, "admin.i18n.err_no_source")}, status_code=400)
    try:
        src, out = await svc.translate(db, texts, targets, source=source, kind=kind)
    except (svc.TranslateError, llm.LLMError) as e:
        code = ERRORS.get(str(e), "failed")
        detail = re.sub(r"<[^>]+>|\s+", " ", str(e)).strip()[:120]  # a provider's HTML error page must not land in the toast
        msg = t(staff.lang, f"admin.i18n.err_{code}", err=detail) if code != "failed" else t(staff.lang, "admin.i18n.err_failed", err=detail)
        return JSONResponse({"error": code, "message": msg}, status_code=200 if code != "no_source" else 400)
    return JSONResponse({"source": src, "translations": out})
