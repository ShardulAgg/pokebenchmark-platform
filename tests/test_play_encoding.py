import io
from PIL import Image
from pokebenchmark_platform.orchestrator.play.encoding import encode_jpeg


def test_encode_jpeg_returns_bytes():
    img = Image.new("RGB", (240, 160), color=(10, 20, 30))
    data = encode_jpeg(img)
    assert isinstance(data, bytes)
    assert len(data) > 0


def test_encode_jpeg_is_valid_jpeg():
    img = Image.new("RGB", (240, 160), color=(10, 20, 30))
    data = encode_jpeg(img)
    # JPEG magic bytes
    assert data[:2] == b"\xff\xd8"
    # Round-trip: decode and verify dimensions + approximate color
    decoded = Image.open(io.BytesIO(data))
    assert decoded.size == (240, 160)
    assert decoded.mode == "RGB"
    # Pixel close to original (JPEG is lossy)
    r, g, b = decoded.getpixel((100, 100))
    assert abs(r - 10) < 15 and abs(g - 20) < 15 and abs(b - 30) < 15


def test_encode_jpeg_accepts_rgba_input():
    img = Image.new("RGBA", (240, 160), color=(0, 0, 0, 255))
    data = encode_jpeg(img)
    assert data[:2] == b"\xff\xd8"
