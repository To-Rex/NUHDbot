"""Image uploads: validation, WebP conversion, thumbnails; files go to the configured store (S3 or local disk)."""
import io
import secrets
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, ImageOps

from app.config import settings
from app.services import storage

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
MAX_SIDE = 1600
THUMB_SIDE = 480


class MediaError(ValueError):
    pass


def _variant(img: Image.Image, max_side: int, quality: int) -> tuple[bytes, tuple[int, int]]:
    im = img.copy()
    im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=quality, method=4)
    return buf.getvalue(), im.size


def _decode(raw: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        return img
    except Exception as e:  # noqa: BLE001
        raise MediaError("invalid_image") from e


async def store_image(img: Image.Image, prefix: str) -> dict:
    """Write the main WebP and its thumbnail to the store; returns the ProductImage-style meta dict."""
    token = secrets.token_urlsafe(10)
    name, thumb = f"{prefix}_{token}.webp", f"{prefix}_{token}_t.webp"
    main, (w, h) = _variant(img, MAX_SIDE, 84)
    small, _ = _variant(img, THUMB_SIDE, 78)
    await storage.put(name, main, "image/webp")
    await storage.put(thumb, small, "image/webp")
    return {"filename": name, "thumb": thumb, "width": w, "height": h}


async def save_image(file: UploadFile, prefix: str = "p") -> dict:
    if file.content_type not in ALLOWED_TYPES:
        raise MediaError("unsupported_type")
    raw = await file.read()
    if len(raw) > settings.max_image_mb * 1024 * 1024:
        raise MediaError("too_large")
    return await store_image(_decode(raw), prefix)


async def save_bytes_image(raw: bytes, prefix: str = "p") -> dict:
    """Same as save_image for bytes already in memory (bot downloads, generated samples)."""
    if len(raw) > settings.max_image_mb * 1024 * 1024:
        raise MediaError("too_large")
    return await store_image(_decode(raw), prefix)


async def save_document(file: UploadFile, prefix: str = "d") -> str:
    """Store payment proofs / support attachments as-is (images converted to webp)."""
    if file.content_type in ALLOWED_TYPES:
        meta = await save_image(file, prefix)
        return meta["filename"]
    raw = await file.read()
    if len(raw) > settings.max_image_mb * 1024 * 1024:
        raise MediaError("too_large")
    ext = Path(file.filename or "file.bin").suffix.lower()[:8] or ".bin"
    if ext in (".exe", ".sh", ".bat", ".js", ".html", ".php"):
        raise MediaError("unsupported_type")
    name = f"{prefix}_{secrets.token_urlsafe(10)}{ext}"
    await storage.put(name, raw, file.content_type or None)
    return name


async def delete_files(*names: str | None) -> None:
    await storage.delete(*names)


def url(name: str | None) -> str | None:
    return storage.url(name)
