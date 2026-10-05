import io

from PIL import Image

MEDIA_TYPES = {"png": "image/png", "webp": "image/webp", "jpeg": "image/jpeg"}


def encode(png: bytes, format: str = "png", scale: float = 1.0, quality: int = 80) -> bytes:
    """Re-encodes a PNG screenshot, optionally scaled down. WebP and JPEG are a fraction of the size, which is most
    of a screenshot's latency over the network and its token cost for a model."""
    if format not in MEDIA_TYPES:
        raise ValueError(f"format must be one of {', '.join(MEDIA_TYPES)}")
    if not 0 < scale <= 1:
        raise ValueError("scale must be in (0, 1]")
    if format == "png" and scale == 1:
        return png
    image = Image.open(io.BytesIO(png))
    if scale < 1:
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.Resampling.LANCZOS
        )
    if format == "jpeg":
        image = image.convert("RGB")
    out = io.BytesIO()
    image.save(out, format=format.upper(), quality=max(1, min(int(quality), 100)))
    return out.getvalue()
