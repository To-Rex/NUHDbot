"""Image uploads: validation, WebP conversion, thumbnails. Videos are out of scope for v1."""
import io
import secrets
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, ImageOps

from app.config import settings

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
MAX_SIDE = 1600
THUMB_SIDE = 480


class MediaError(ValueError):
    pass


def _save_variant(img: Image.Image, max_side: int, path: Path, quality: int) -> tuple[int, int]:
    im = img.copy()
    im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    im.save(path, "WEBP", quality=quality, method=4)
    return im.size


async def save_image(file: UploadFile, prefix: str = "p") -> dict:
    if file.content_type not in ALLOWED_TYPES:
        raise MediaError("unsupported_type")
    raw = await file.read()
    if len(raw) > settings.max_image_mb * 1024 * 1024:
        raise MediaError("too_large")
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
    except Exception as e:  # noqa: BLE001
        raise MediaError("invalid_image") from e
    token = secrets.token_urlsafe(10)
    name = f"{prefix}_{token}.webp"
    thumb = f"{prefix}_{token}_t.webp"
    w, h = _save_variant(img, MAX_SIDE, settings.upload_dir / name, 84)
    _save_variant(img, THUMB_SIDE, settings.upload_dir / thumb, 78)
    return {"filename": name, "thumb": thumb, "width": w, "height": h}


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
    (settings.upload_dir / name).write_bytes(raw)
    return name


def delete_files(*names: str | None) -> None:
    for n in names:
        if not n:
            continue
        p = settings.upload_dir / n
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
