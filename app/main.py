import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from app.config import APP_DIR, settings
from app.db import SessionLocal, session_scope
from app.deps import RedirectException, is_secure
from app.services.cart import read_session, write_session
from app.services.users import ensure_initial_admin

logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("nuhd")


async def _auction_ticker() -> None:
    from app.services import auctions, notifications

    while True:
        try:
            async with session_scope() as db:
                ended = await auctions.tick(db)
                for a in ended:
                    users = await auctions.participants(db, a.id)
                    await notifications.notify_auction_result(db, a, users)
                    if a.winner_user_id:
                        await notifications.notify_staff(
                            db, f"🔨 Аукцион #{a.id} якунланди: {a.title} {a.capacity_label} — {a.current_price_total} {a.currency}", kind="auction_ended"
                        )
        except Exception:  # noqa: BLE001
            log.exception("auction tick failed")
        await asyncio.sleep(2)


def _run_migrations() -> None:
    from alembic.config import Config

    from alembic import command
    from app.config import BASE_DIR

    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    log.info("migrations applied")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    if settings.run_migrations:
        await asyncio.to_thread(_run_migrations)
    async with session_scope() as db:
        await ensure_initial_admin(db, settings.admin_login, settings.admin_password)
    tasks = [asyncio.create_task(_auction_ticker())]
    bot_task = None
    if settings.bot_token and settings.bot_mode != "off":
        from app.bot.runner import start_bot

        bot_task = await start_bot(app)
        if bot_task:
            tasks.append(bot_task)
    log.info(
        "started: base_url=%s bot_mode=%s token=%s https=%s",
        settings.base_url, settings.bot_mode, "set" if settings.bot_token else "MISSING", settings.base_url.startswith("https://"),
    )
    if settings.bot_token and settings.bot_mode == "off":
        log.warning("BOT_MODE=off — the Telegram bot will NOT answer. Set BOT_MODE=polling or webhook.")
    if not settings.base_url.startswith("https://"):
        log.warning("BASE_URL is not https — Telegram Mini App buttons are disabled until BASE_URL uses https.")
    try:
        yield
    finally:
        for tsk in tasks:
            tsk.cancel()
        from app.bot.instance import close_bot

        await close_bot()


app = FastAPI(title=settings.app_name, lifespan=lifespan, docs_url="/api/docs" if settings.debug else None, redoc_url=None)
app.add_middleware(GZipMiddleware, minimum_size=800)


class CachedStatic(StaticFiles):
    def file_response(self, *args, **kwargs):  # type: ignore[override]
        resp = super().file_response(*args, **kwargs)
        path = str(args[0]) if args else ""
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable" if "/uploads/" in path else "public, max-age=3600"
        return resp


app.mount("/static", CachedStatic(directory=str(APP_DIR / "static")), name="static")


@app.middleware("http")
async def session_and_security(request: Request, call_next):
    response: Response = await call_next(request)
    # persist dev-login session created in deps.current_user
    uid = getattr(request.state, "set_session_uid", None)
    if uid:
        sess = read_session(request)
        sess["uid"] = uid
        write_session(response, sess, secure=is_secure(), max_age=settings.session_max_age)
    q_theme = request.query_params.get("theme")
    if q_theme in ("auto", "light", "dark"):
        from app.deps import THEME_COOKIE, set_pref_cookie

        set_pref_cookie(response, THEME_COOKIE, q_theme)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    if request.url.path.startswith("/admin"):
        response.headers.setdefault("X-Frame-Options", "DENY")
    return response


@app.exception_handler(RedirectException)
async def _redirect_handler(request: Request, exc: RedirectException):
    if request.headers.get("HX-Request") == "true":
        return Response(status_code=204, headers={"HX-Redirect": exc.url})
    return RedirectResponse(exc.url, status_code=303)


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/app", status_code=302)


@app.get("/health", include_in_schema=False)
async def health():
    async with SessionLocal() as db:
        await db.execute(__import__("sqlalchemy").text("select 1"))
    return {"ok": True}


from app.admin.router import router as admin_router  # noqa: E402
from app.api.router import router as api_router  # noqa: E402
from app.web.router import router as web_router  # noqa: E402

app.include_router(api_router, prefix="/api")
app.include_router(web_router, prefix="/app")
app.include_router(admin_router, prefix="/admin")
