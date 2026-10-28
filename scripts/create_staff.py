"""Create or update a staff account for the admin panel.

    uv run python -m scripts.create_staff --login manager1 --password 'S3cret!' --role orders [--tg-id 123456789] [--name "Ali"]
Roles: admin, catalog, warehouse, tester, orders, finance, marketing
"""
import argparse
import asyncio

from sqlalchemy import select

from app.db import session_scope
from app.enums import Role
from app.models import User
from app.security import hash_password


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--role", required=True, choices=[r.value for r in Role if r != Role.CUSTOMER])
    ap.add_argument("--tg-id", type=int, default=None)
    ap.add_argument("--name", default=None)
    a = ap.parse_args()
    async with session_scope() as db:
        user = None
        if a.tg_id:
            user = (await db.execute(select(User).where(User.tg_id == a.tg_id))).scalar_one_or_none()
        if user is None:
            user = (await db.execute(select(User).where(User.login == a.login))).scalar_one_or_none()
        if user is None:
            user = User(first_name=a.name or a.login, lang="uz")
            db.add(user)
        user.login = a.login
        user.password_hash = hash_password(a.password)
        user.role = Role(a.role)
        if a.tg_id:
            user.tg_id = a.tg_id
        if a.name:
            user.first_name = a.name
        await db.flush()
        print(f"staff ready: id={user.id} login={user.login} role={user.role} tg_id={user.tg_id}")


if __name__ == "__main__":
    asyncio.run(main())
