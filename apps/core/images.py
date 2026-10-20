"""Bilder beim Hochladen verkleinern, richtig drehen und Metadaten (EXIF/GPS) entfernen."""

from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import InMemoryUploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_SIDE = 1800
ALLOWED = {"JPEG", "PNG", "WEBP", "HEIF", "MPO"}


def process_image(upload, max_side=MAX_SIDE):
    try:
        img = Image.open(upload)
        img.load()
    except (UnidentifiedImageError, OSError):
        raise ValidationError("Die Datei ist kein gültiges Bild (erlaubt: JPG, PNG, WebP).")
    except Image.DecompressionBombError:
        raise ValidationError("Das Bild ist zu groß (Auflösung). Bitte ein kleineres Foto verwenden.")
    if img.format not in ALLOWED:
        raise ValidationError("Bildformat nicht unterstützt (erlaubt: JPG, PNG, WebP).")
    img = ImageOps.exif_transpose(img)
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    out = BytesIO()
    if img.mode in ("RGBA", "LA", "P") and upload.name.lower().endswith(".png"):
        img.save(out, "PNG", optimize=True)
        ext, ctype = "png", "image/png"
    else:
        img = img.convert("RGB")
        img.save(out, "JPEG", quality=85, optimize=True, progressive=True)
        ext, ctype = "jpg", "image/jpeg"
    out.seek(0)
    base = upload.name.rsplit(".", 1)[0][:60] or "bild"
    return InMemoryUploadedFile(out, "image", f"{base}.{ext}", ctype, out.getbuffer().nbytes, None)
