from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from app.admin.common import ADMIN, DB, back, f_int, f_str, render, staff_dep
from app.admin.router import router
from app.enums import STAFF_ROLES, Role
from app.i18n import t
from app.models import User
from app.security import hash_password
from app.services import audit


@router.get("/staff")
async def staff_list(request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    rows = (await db.execute(select(User).where(User.role.in_(list(STAFF_ROLES))).order_by(User.id))).scalars().all()
    return render(request, staff, "admin/customers/staff.html", {"page_title": t(staff.lang, "admin.staff.title"), "rows": rows, "staff_roles": sorted(STAFF_ROLES, key=lambda r: r.value)})


@router.post("/staff/new")
async def staff_create(request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    form = await request.form()
    login = f_str(form, "login", maxlen=64)
    password = form.get("password") or ""
    role = Role(form.get("role") or "orders")
    if not login or len(password) < 6 or role not in STAFF_ROLES:
        return back(request, "/admin/staff", t(staff.lang, "admin.required"), "bad")
    if (await db.execute(select(User).where(User.login == login))).scalar_one_or_none():
        return back(request, "/admin/staff", t(staff.lang, "admin.staff.login_taken"), "bad")
    tg_id = f_int(form, "tg_id", None)
    u = User(first_name=f_str(form, "first_name", maxlen=100) or login, last_name=f_str(form, "last_name", maxlen=100), login=login, password_hash=hash_password(password), role=role, tg_id=tg_id or None, lang="uz")
    db.add(u)
    await db.flush()
    await audit.log(db, staff.id, "staff.create", "user", u.id, None, {"login": login, "role": role})
    await db.commit()
    return back(request, "/admin/staff", t(staff.lang, "admin.staff.created"))


@router.post("/staff/{uid}/{action}")
async def staff_action(uid: int, action: str, request: Request, db: DB, staff: User = Depends(staff_dep(*ADMIN))):
    u = await db.get(User, uid)
    if not u or not u.is_staff:
        raise HTTPException(404)
    if u.id == staff.id and action in ("deactivate", "role"):
        return back(request, "/admin/staff", t(staff.lang, "admin.staff.self_guard"), "bad")
    form = await request.form()
    before = {"role": u.role, "is_blocked": u.is_blocked, "tg_id": u.tg_id}
    if action == "password":
        pw = form.get("password") or ""
        if len(pw) < 6:
            return back(request, "/admin/staff", t(staff.lang, "admin.required"), "bad")
        u.password_hash = hash_password(pw)
    elif action == "deactivate":
        u.is_blocked = True
    elif action == "activate":
        u.is_blocked = False
    elif action == "role":
        role = Role(form.get("role") or u.role)
        if role not in STAFF_ROLES:
            raise HTTPException(400)
        u.role = role
        u.tg_id = f_int(form, "tg_id", None) or None
    else:
        raise HTTPException(400)
    await audit.log(db, staff.id, f"staff.{action}", "user", u.id, before, {"role": u.role, "is_blocked": u.is_blocked, "tg_id": u.tg_id})
    await db.commit()
    return back(request, "/admin/staff", t(staff.lang, "admin.flash.saved"))
