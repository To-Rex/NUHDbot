"""File store: S3-compatible object storage (TorexPloy TibFiles) with a local-disk fallback.

Keys are flat file names; `url(name)` returns a public link (S3 public URL), the in-app proxy `/media/<name>`
(private bucket) or the local static path when no store is configured.
"""
import asyncio
import logging
import mimetypes
from functools import lru_cache

from app.config import settings

log = logging.getLogger("nuhd.storage")


@lru_cache
def _client():
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
        region_name=settings.s3_region or "us-east-1",
        config=Config(s3={"addressing_style": "path"}, signature_version="s3v4", retries={"max_attempts": 3}),
    )


def _key(name: str) -> str:
    return f"{settings.s3_prefix.strip('/')}/{name}" if settings.s3_prefix else name


def enabled() -> bool:
    return settings.s3_enabled


def url(name: str | None) -> str | None:
    if not name:
        return None
    if settings.s3_enabled:
        if settings.s3_public_url:
            return f"{settings.s3_public_url.rstrip('/')}/{settings.s3_bucket}/{_key(name)}"
        return f"/media/{name}"
    return f"/static/uploads/{name}"


def content_type_for(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


async def put(name: str, data: bytes, content_type: str | None = None) -> None:
    ct = content_type or content_type_for(name)
    if settings.s3_enabled:
        await asyncio.to_thread(_client().put_object, Bucket=settings.s3_bucket, Key=_key(name), Body=data, ContentType=ct, CacheControl="public, max-age=31536000, immutable")
        return
    await asyncio.to_thread((settings.upload_dir / name).write_bytes, data)


async def get(name: str) -> tuple[bytes, str] | None:
    """Return (bytes, content-type) or None when the object is missing."""
    if settings.s3_enabled:
        def _fetch():
            try:
                obj = _client().get_object(Bucket=settings.s3_bucket, Key=_key(name))
            except _client().exceptions.NoSuchKey:
                return None
            except Exception as e:  # noqa: BLE001
                if getattr(e, "response", {}).get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                    return None
                raise
            return obj["Body"].read(), obj.get("ContentType") or content_type_for(name)

        return await asyncio.to_thread(_fetch)
    path = settings.upload_dir / name
    if not path.is_file():
        return None
    return await asyncio.to_thread(path.read_bytes), content_type_for(name)


async def delete(*names: str | None) -> None:
    names = [n for n in names if n]
    if not names:
        return
    if settings.s3_enabled:
        def _rm():
            _client().delete_objects(Bucket=settings.s3_bucket, Delete={"Objects": [{"Key": _key(n)} for n in names], "Quiet": True})

        try:
            await asyncio.to_thread(_rm)
        except Exception:  # noqa: BLE001
            log.exception("delete failed")
        return
    for n in names:
        try:
            (settings.upload_dir / n).unlink(missing_ok=True)
        except OSError:
            pass


def check() -> str | None:
    """Startup probe: None when the store answers, otherwise a short reason (logged, never fatal)."""
    if not settings.s3_enabled:
        return None
    try:
        _client().head_bucket(Bucket=settings.s3_bucket)
    except Exception as e:  # noqa: BLE001
        return str(e)[:200]
    return None
