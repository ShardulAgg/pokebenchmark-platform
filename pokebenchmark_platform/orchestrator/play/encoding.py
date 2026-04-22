"""JPEG encoding for play-mode frame streaming."""
import io
from PIL import Image

JPEG_QUALITY = 75


def encode_jpeg(img: Image.Image) -> bytes:
    """Encode a PIL image as JPEG bytes. Accepts RGB or RGBA input."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    return buf.getvalue()
