"""Bilder: Upload verarbeiten (auch iPhone-HEIC), verkleinern, Vorschaubild erzeugen."""
import io
import os
import uuid

from PIL import Image, ImageOps

from . import db

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover - HEIC optional
    pillow_heif = None

MAX_SIDE = 2400
THUMB_SIDE = 480


def save_upload(data: bytes):
    """Speichert ein Bild als JPEG + Vorschau. Gibt den Dateinamen zurück."""
    try:
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im)
    except Exception as e:
        raise ValueError("Kein lesbares Bild (erlaubt: JPG, PNG, HEIC, WebP, GIF)") from e
    if im.mode not in ("RGB", "L"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        try:
            bg.paste(im, mask=im.convert("RGBA").split()[-1])
        except Exception:
            bg.paste(im.convert("RGB"))
        im = bg
    name = uuid.uuid4().hex[:16]
    big = im.copy()
    big.thumbnail((MAX_SIDE, MAX_SIDE))
    big.convert("RGB").save(os.path.join(db.BILDER_DIR, name + ".jpg"), "JPEG", quality=86, optimize=True)
    th = im.copy()
    th.thumbnail((THUMB_SIDE, THUMB_SIDE))
    th.convert("RGB").save(os.path.join(db.BILDER_DIR, name + "_t.jpg"), "JPEG", quality=80, optimize=True)
    return name + ".jpg"


def delete_files(datei):
    base = os.path.splitext(os.path.basename(datei))[0]
    for fn in (base + ".jpg", base + "_t.jpg"):
        try:
            os.remove(os.path.join(db.BILDER_DIR, fn))
        except OSError:
            pass
