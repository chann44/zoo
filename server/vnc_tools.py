"""Screen, mouse and keyboard tools for VMs driven over VNC (macOS and Windows sandboxes)."""

import base64

from server.runtime import vnc

pointers: dict[str, tuple[int, int]] = {}


class Mouse:
    @staticmethod
    def click(container_id: str, x: int, y: int, display: str = ":1", button: str = "left"):
        with vnc(container_id) as v:
            v.click(x, y, button)
        pointers[container_id] = (x, y)
        return {"success": True, "x": x, "y": y, "button": button}

    @staticmethod
    def move(container_id: str, x: int, y: int, display: str = ":1"):
        with vnc(container_id) as v:
            v.pointer(x, y)
        pointers[container_id] = (x, y)
        return {"success": True, "x": x, "y": y}

    @staticmethod
    def double_click(container_id: str, x: int, y: int, display: str = ":1", button: str = "left"):
        with vnc(container_id) as v:
            v.click(x, y, button, count=2)
        pointers[container_id] = (x, y)
        return {"success": True, "x": x, "y": y, "button": button}

    @staticmethod
    def scroll(container_id: str, direction: str, amount: int = 3, x: int = None, y: int = None, display: str = ":1"):
        if amount < 1:
            raise ValueError("Amount must be >= 1")
        if (x is None) != (y is None):
            raise ValueError("Both x and y must be provided")
        if x is not None:
            pointers[container_id] = (x, y)
        with vnc(container_id) as v:
            v.pointer(*pointers.get(container_id, (v.width // 2, v.height // 2)))
            v.scroll(direction, amount)
        return {"success": True, "direction": direction, "amount": amount}

    @staticmethod
    def drag(
        container_id: str,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        display: str = ":1",
        button: str = "left",
        duration: float = 0.5,
    ):
        with vnc(container_id) as v:
            v.drag((start_x, start_y), (end_x, end_y), button, duration)
        pointers[container_id] = (end_x, end_y)
        return {"success": True, "start": [start_x, start_y], "end": [end_x, end_y], "button": button}


class Keyboard:
    @staticmethod
    def type_text(container_id: str, text: str, display: str = ":1", delay: int = 12):
        with vnc(container_id) as v:
            v.type(text, delay / 1000)
        return {"success": True, "length": len(text)}

    @staticmethod
    def press_key(container_id: str, key: str, display: str = ":1"):
        with vnc(container_id) as v:
            v.combo(key.split("+") if len(key) > 1 else [key])
        return {"success": True, "key": key}


def hotkey(container_id: str, keys: list[str], display: str = ":1") -> dict:
    if not keys:
        raise ValueError("At least one key is required")
    with vnc(container_id) as v:
        v.combo(keys)
    return {"success": True, "keys": list(keys)}


def screenshot(container_id: str, display: str = ":1") -> str:
    with vnc(container_id) as v:
        return base64.b64encode(v.screenshot()).decode()
