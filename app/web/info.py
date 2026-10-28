from fastapi import Request
from sqlalchemy import select

from app.deps import DB, CurrentUser, Lang
from app.i18n import t
from app.models import Article
from app.services.settings_service import get_setting
from app.templating import render
from app.web.router import router

CATEGORY_ORDER = ["choose", "conditions", "tech", "guide"]


@router.get("/info")
async def info_page(request: Request, db: DB, user: CurrentUser, lang: Lang):
    arts = (await db.execute(select(Article).where(Article.is_published.is_(True)).order_by(Article.sort, Article.id))).scalars().all()
    groups: dict[str, list] = {}
    for a in arts:
        groups.setdefault(a.category, []).append(a)
    ordered = [(c, groups[c]) for c in CATEGORY_ORDER if c in groups] + [(c, v) for c, v in groups.items() if c not in CATEGORY_ORDER]
    return render(request, "miniapp/info.html", {"lang": lang, "groups": ordered, "wd": await get_setting(db, "wd_check_url"), "seagate": await get_setting(db, "seagate_check_url"), "page_title": t(lang, "info.title"), "back_url": "/app/home"})


@router.get("/info/{slug}")
async def article_page(slug: str, request: Request, db: DB, user: CurrentUser, lang: Lang):
    a = (await db.execute(select(Article).where(Article.slug == slug, Article.is_published.is_(True)))).scalar_one_or_none()
    if a is None:
        return render(request, "miniapp/not_found.html", {"lang": lang, "message_key": "info.not_found", "back_url": "/app/info"}, status_code=404)
    others = (await db.execute(select(Article).where(Article.is_published.is_(True), Article.category == a.category, Article.id != a.id).order_by(Article.sort).limit(4))).scalars().all()
    return render(request, "miniapp/article.html", {"lang": lang, "a": a, "others": others, "page_title": t(lang, "info.title"), "back_url": "/app/info"})
