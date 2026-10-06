"""screen_diff and wait_until_stable computed API-side from full screenshots, for sandboxes whose guest can't do
it: Linux sandboxes booted before the guest, and the macOS and Windows VMs."""

import io
import time
from collections.abc import Callable

from PIL import Image, ImageChops

from server.images import encode

POLL_EVERY = 0.1
# each diff session's previous frame, keyed by (runtime, display, session)
frames: dict[tuple[str, str, str], Image.Image] = {}
MAX_SESSIONS = 256


def changes(prev: Image.Image | None, cur: Image.Image) -> tuple[float, tuple[int, int, int, int] | None]:
    """The fraction of the screen inside the changed region and that region's box, as the guest reports them."""
    if prev is None or prev.size != cur.size:
        return 1.0, (0, 0, *cur.size)
    box = ImageChops.difference(prev, cur).getbbox()
    if box is None:
        return 0.0, None
    return (box[2] - box[0]) * (box[3] - box[1]) / (cur.width * cur.height), box


def decode(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGB")


def diff(key: tuple[str, str, str], png: bytes, format: str, scale: float, quality: int) -> tuple[dict, bytes]:
    cur = decode(png)
    if key not in frames and len(frames) >= MAX_SESSIONS:
        frames.pop(next(iter(frames)))
    fraction, box = changes(frames.get(key), cur)
    frames[key] = cur
    result = {"width": cur.width, "height": cur.height, "changed": fraction, "format": format, "box": None}
    if box is None:
        return result, b""
    out = io.BytesIO()
    cur.crop(box).save(out, format="PNG")
    result["box"] = {"x": box[0], "y": box[1], "width": box[2] - box[0], "height": box[3] - box[1]}
    return result, encode(out.getvalue(), format, scale, quality)


def wait_until_stable(grab: Callable[[], bytes], timeout: float, quiet_ms: int, threshold: float) -> dict:
    start = time.monotonic()
    prev, last_change = decode(grab()), start
    while True:
        now = time.monotonic()
        if now - last_change >= quiet_ms / 1000:
            return {"stable": True, "waited_ms": int((now - start) * 1000)}
        if now - start >= timeout:
            return {"stable": False, "waited_ms": int((now - start) * 1000)}
        time.sleep(POLL_EVERY)
        cur = decode(grab())
        if changes(prev, cur)[0] > threshold:
            last_change = time.monotonic()
        prev = cur


def check_wait(timeout: float, quiet_ms: int, threshold: float):
    if not 0 < timeout <= 60:
        raise ValueError("timeout must be in (0, 60] seconds")
    if quiet_ms <= 0 or not 0 <= threshold < 1:
        raise ValueError("quiet_ms must be positive and threshold in [0, 1)")
