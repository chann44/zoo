import io

from PIL import Image

from server import screen


def png(color: tuple[int, int, int], dot: tuple[int, int] | None = None) -> bytes:
    image = Image.new("RGB", (40, 20), color)
    if dot:
        image.putpixel(dot, (255, 0, 0))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def test_diff_reports_only_what_changed():
    key = ("rt", ":1", "test")
    screen.frames.pop(key, None)
    first, image = screen.diff(key, png((0, 0, 0)), "png", 1.0, 80)
    assert first["changed"] == 1 and first["box"] == {"x": 0, "y": 0, "width": 40, "height": 20} and image
    same, image = screen.diff(key, png((0, 0, 0)), "png", 1.0, 80)
    assert same["changed"] == 0 and same["box"] is None and image == b""
    dot, image = screen.diff(key, png((0, 0, 0), (5, 7)), "png", 1.0, 80)
    assert dot["box"] == {"x": 5, "y": 7, "width": 1, "height": 1}
    assert Image.open(io.BytesIO(image)).size == (1, 1)


def test_wait_until_stable_waits_out_changes():
    frames = iter([png((0, 0, 0)), png((9, 9, 9))] + [png((9, 9, 9))] * 50)
    result = screen.wait_until_stable(lambda: next(frames), timeout=5, quiet_ms=300, threshold=0)
    assert result["stable"] and result["waited_ms"] >= 300
    result = screen.wait_until_stable(lambda: png((0, 0, 0), (len(str(object())) % 40, 0)), 0.3, 1000, 0)
    assert not result["stable"]
