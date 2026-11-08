"""The bell: the kept notices (new orders and payments, deposit receipts, customers joining a lot, new customers).
The top bar's bell opens the latest ones; /admin/notices lists them all, newest first."""
from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from app.admin.common import DB, nav_badges, notice_kinds, render, staff_dep
from app.admin.router import router
from app.enums import STAFF_ROLES
from app.i18n import t
from app.models import User
from app.services import admin_notices as svc

POP_LIMIT = 12
PAGE_LIMIT = 40


def _lang(request: Request, staff: User) -> str:
    return request.cookies.get("nuhd_admin_lang") or staff.lang or "uz"


@router.get("/notices")
async def notices_page(request: Request, db: DB, staff: User = Depends(staff_dep(*STAFF_ROLES)), before: int | None = None, partial: int = 0):
    """partial=1: the bell's list (the latest few); otherwise the page, `before` paging further back."""
    kinds = notice_kinds(staff)
    if partial:
        items = await svc.recent(db, kinds, limit=POP_LIMIT)
        return render(request, staff, "admin/partials/notices_pop.html", {"items": items, "is_new": lambda n: svc.is_new(n, staff), "icons": svc.ICONS})
    items = await svc.recent(db, kinds, limit=PAGE_LIMIT + 1, before_id=before)
    more = items[PAGE_LIMIT].id if len(items) > PAGE_LIMIT else None
    items = items[:PAGE_LIMIT]
    return render(request, staff, "admin/notices/list.html", {
        "items": items, "more": more, "is_new": lambda n: svc.is_new(n, staff), "icons": svc.ICONS,
        "page_title": t(_lang(request, staff), "admin.notices.title"), "page_sub": t(_lang(request, staff), "admin.notices.sub"),
    })


@router.post("/notices/seen")
async def notices_seen(db: DB, staff: User = Depends(staff_dep(*STAFF_ROLES))):
    """The bell was opened: everything so far counts as seen for this staff member. Answers the fresh badge counts."""
    await svc.mark_seen(db, staff)
    await db.commit()
    return JSONResponse(await nav_badges(db, staff))
