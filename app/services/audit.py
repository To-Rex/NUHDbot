from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


def _clean(d: dict | None) -> dict | None:
    if d is None:
        return None
    out = {}
    for k, v in d.items():
        if k.startswith("_"):
            continue
        try:
            out[k] = v if isinstance(v, (int, float, str, bool, type(None), list, dict)) else str(v)
        except Exception:
            out[k] = repr(v)
    return out


async def log(
    db: AsyncSession,
    actor_id: int | None,
    action: str,
    entity: str,
    entity_id: Any = None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id) if entity_id is not None else None,
            before=_clean(before),
            after=_clean(after),
        )
    )
