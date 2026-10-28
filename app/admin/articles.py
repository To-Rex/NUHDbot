import re

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from app.admin.common import ARTICLE_ROLES, DB, back, f_bool, f_i18n, f_int, f_str, render, staff_dep
from app.admin.router import router
from app.i18n import t
from app.models import Article, User
from app.services import audit

CATEGORIES = ("choose", "tech", "conditions", "guide", "news")


@router.get("/articles")
async def articles_list(request: Request, db: DB, staff: User = Depends(staff_dep(*ARTICLE_ROLES))):
    rows = (await db.execute(select(Article).order_by(Article.sort, Article.id))).scalars().all()
    return render(request, staff, "admin/settings/articles.html", {"page_title": t(staff.lang, "admin.art.title"), "rows": rows})


@router.get("/articles/new")
async def article_new(request: Request, db: DB, staff: User = Depends(staff_dep(*ARTICLE_ROLES))):
    a = Article(slug="", category="guide", icon="💡", title={}, summary={}, body={}, sort=100, is_published=False)
    return render(request, staff, "admin/settings/article_form.html", {"page_title": t(staff.lang, "admin.art.new"), "a": a, "is_new": True, "categories": CATEGORIES})


def _apply(a: Article, form) -> list[str]:
    errors = []
    slug = re.sub(r"[^a-z0-9-]", "-", f_str(form, "slug", maxlen=80).lower()).strip("-")
    if not slug:
        errors.append("slug")
    a.slug = slug
    a.category = form.get("category") if form.get("category") in CATEGORIES else "guide"
    a.icon = f_str(form, "icon", "💡", 8)
    a.title = f_i18n(form, "title")
    if not a.title.get("uz"):
        errors.append("title_uz")
    a.summary = f_i18n(form, "summary")
    a.body = f_i18n(form, "body")
    a.sort = f_int(form, "sort", 100) or 100
    a.is_published = f_bool(form, "is_published")
    return errors


@router.post("/articles/new")
async def article_create(request: Request, db: DB, staff: User = Depends(staff_dep(*ARTICLE_ROLES))):
    form = await request.form()
    a = Article()
    errors = _apply(a, form)
    if not errors and (await db.execute(select(Article).where(Article.slug == a.slug))).scalar_one_or_none():
        errors.append("slug exists")
    if errors:
        return render(request, staff, "admin/settings/article_form.html", {"page_title": t(staff.lang, "admin.art.new"), "a": a, "is_new": True, "errors": errors, "categories": CATEGORIES}, status_code=400)
    db.add(a)
    await db.flush()
    await audit.log(db, staff.id, "article.create", "article", a.id, None, {"slug": a.slug})
    await db.commit()
    return back(request, f"/admin/articles/{a.id}", t(staff.lang, "admin.flash.saved"))


@router.get("/articles/{aid}")
async def article_edit(aid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ARTICLE_ROLES))):
    a = await db.get(Article, aid)
    if not a:
        raise HTTPException(404)
    return render(request, staff, "admin/settings/article_form.html", {"page_title": a.title.get("uz") or a.slug, "a": a, "is_new": False, "categories": CATEGORIES})


@router.post("/articles/{aid}")
async def article_update(aid: int, request: Request, db: DB, staff: User = Depends(staff_dep(*ARTICLE_ROLES))):
    a = await db.get(Article, aid)
    if not a:
        raise HTTPException(404)
    form = await request.form()
    if form.get("action") == "delete":
        await db.delete(a)
        await audit.log(db, staff.id, "article.delete", "article", aid)
        await db.commit()
        return back(request, "/admin/articles", t(staff.lang, "admin.flash.deleted"))
    if form.get("action") == "toggle":
        a.is_published = not a.is_published
        await db.commit()
        return back(request, "/admin/articles", t(staff.lang, "admin.flash.saved"))
    before = {"slug": a.slug, "published": a.is_published}
    errors = _apply(a, form)
    if errors:
        return render(request, staff, "admin/settings/article_form.html", {"page_title": a.slug, "a": a, "is_new": False, "errors": errors, "categories": CATEGORIES}, status_code=400)
    await audit.log(db, staff.id, "article.update", "article", a.id, before, {"slug": a.slug, "published": a.is_published})
    await db.commit()
    return back(request, f"/admin/articles/{a.id}", t(staff.lang, "admin.flash.saved"))
