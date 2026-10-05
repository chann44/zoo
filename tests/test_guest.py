import base64
import io
import json
import threading
import time
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from starlette.websockets import WebSocketDisconnect

from server import guest
from server.guest import hub, pack, token, unpack
from server.monitor import guest_usage
from server.registry import screenshot
from server.tools import FileSystem, KeyboardTools, MoseTools, ShellTools
from tests.conftest import runtime_of

SERVICES = ["exec", "pty", "files", "screen", "input", "metrics"]


def client() -> TestClient:
    app = FastAPI()
    app.websocket("/guest/connect")(hub.serve)
    return TestClient(app)


def headers(sandbox_id: str, secret: str | None = None) -> dict:
    return {"authorization": f"Bearer {secret or token(sandbox_id)}", "x-zoo-sandbox": sandbox_id}


def png(width: int = 8, height: int = 6) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "red").save(out, format="PNG")
    return out.getvalue()


class FakeGuest:
    """Connects to the hub as a sandbox's guest and answers requests with `reply(op, args, payload)`."""

    def __init__(self, sandbox_id: str, reply, services: list[str] = SERVICES):
        self.sandbox_id = sandbox_id
        self.services = services
        self.reply = reply
        self.calls: list[tuple[str, dict, bytes]] = []
        self.ws: Any = None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        deadline = time.monotonic() + 5
        while self.sandbox_id not in hub.guests:
            assert time.monotonic() < deadline, "guest never registered"
            time.sleep(0.01)
        return self

    def __exit__(self, *exc):
        hub.drop(self.sandbox_id)
        self.thread.join(5)
        assert self.sandbox_id not in hub.guests

    def run(self):
        with client().websocket_connect("/guest/connect", headers=headers(self.sandbox_id)) as ws:
            self.ws = ws
            ws.send_bytes(pack({"op": "hello", "version": guest.VERSION, "os": "linux", "services": self.services}))
            ws.send_bytes(pack({"op": "metrics", "data": {"cpu_percent": 5}}))
            while True:
                try:
                    header, payload = unpack(ws.receive_bytes())
                except WebSocketDisconnect:
                    return
                self.calls.append((header["op"], header["args"], payload))
                if "id" not in header:
                    # a notification: no reply
                    self.reply(header["op"], header["args"], payload)
                    continue
                try:
                    result, out = self.reply(header["op"], header["args"], payload)
                    ws.send_bytes(pack({"id": header["id"], "ok": True, "result": result}, out))
                except Exception as e:
                    ws.send_bytes(pack({"id": header["id"], "ok": False, "error": str(e)}))


def test_frames_round_trip():
    assert unpack(pack({"id": 1, "op": "exec"}, b"\x00data")) == ({"id": 1, "op": "exec"}, b"\x00data")
    with pytest.raises(ValueError):
        unpack(b"\x00\x00\x00\x09{}")


def test_tokens_are_per_sandbox(monkeypatch):
    assert token("a") == token("a") != token("b")
    monkeypatch.setattr(guest, "LOCAL_URL", "ws://api:8000/guest/connect")
    assert guest.guest_env("a", remote=False)["ZOO_GUEST_TOKEN"] == token("a")
    assert guest.guest_env("a", remote=True) == {}


def test_hub_rejects_bad_tokens_and_old_guests():
    with (
        pytest.raises(WebSocketDisconnect),
        client().websocket_connect("/guest/connect", headers=headers("sb", "wrong")) as ws,
    ):
        ws.receive_bytes()
    with client().websocket_connect("/guest/connect", headers=headers("sb")) as ws:
        ws.send_bytes(pack({"op": "hello", "version": 0, "services": SERVICES}))
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_bytes()
        assert closed.value.code == 1008
    assert "sb" not in hub.guests


def test_tools_go_through_the_guest():
    def reply(op, args, payload):
        if op == "exec":
            return {"exit_code": 0, "stdout_len": 3}, b"hi\nwarn"
        if op == "screenshot":
            return {}, png(4, 3)
        return {}, b""

    hub.bind("rt-guest", "sb-guest")
    with FakeGuest("sb-guest", reply) as fake:
        assert ShellTools.execute_command("rt-guest", "echo hi") == {
            "exit_code": 0,
            "stdout": "hi\n",
            "stderr": "warn",
            "timed_out": False,
        }
        MoseTools.click("rt-guest", 10, 20)
        MoseTools.scroll("rt-guest", "down", 2)
        FileSystem.write_file("rt-guest", "notes/a.txt", "hello")
        webp = base64.b64decode(screenshot("rt-guest", format="webp", scale=0.5))
        assert webp[:4] == b"RIFF" and webp[8:12] == b"WEBP"
        assert hub.status("sb-guest")["metrics"] == {"cpu_percent": 5}

    (op, args, _), (_, click, _), (_, scroll, _), (_, write, data), (_, shot, _) = fake.calls
    assert op == "exec" and args["argv"] == ["timeout", "-k", "2", "30", "sh", "-lc", "echo hi"] and not args["merge"]
    assert click == {"display": ":1", "steps": [{"move": [10, 20]}, {"press": 1}, {"release": 1}]}
    assert scroll["steps"] == [{"press": 5}, {"release": 5}, {"sleep": 80}, {"press": 5}, {"release": 5}]
    assert write == {"path": "/home/zoo/notes/a.txt"} and data == b"hello"
    assert shot == {"display": ":1", "format": "png", "scale": 0.5, "quality": 80}


def test_input_falls_back_to_xdotool_through_guest_exec():
    hub.bind("rt-old", "sb-old")
    with FakeGuest("sb-old", lambda op, args, payload: ({"exit_code": 0, "stdout_len": 0}, b""), ["exec"]) as fake:
        MoseTools.click("rt-old", 10, 20)
    ((op, args, _),) = fake.calls
    assert op == "exec" and args["argv"][:2] == ["xdotool", "mousemove"] and args["env"] == {"DISPLAY": ":1"}


def test_guest_errors_surface_and_disconnects_fall_back():
    def reply(op, args, payload):
        raise RuntimeError("permission denied")

    hub.bind("rt-err", "sb-err")
    with FakeGuest("sb-err", reply), pytest.raises(guest.GuestError, match="permission denied"):
        FileSystem.write_file("rt-err", "/etc/passwd", "x")
    assert hub.for_runtime("rt-err") is None
    assert hub.status("sb-err") == {"connected": False}


def test_keyboard_goes_through_the_guest():
    hub.bind("rt-keys", "sb-keys")
    with FakeGuest("sb-keys", lambda op, args, payload: ({}, b"")) as fake:
        KeyboardTools.type_text("rt-keys", "héllo\n", delay=5)
        KeyboardTools.press_key("rt-keys", "ctrl+c")
        KeyboardTools.hotkey("rt-keys", "ctrl", "shift", "t")
    assert [args for _, args, _ in fake.calls] == [
        {"display": ":1", "text": "héllo\n", "delay": 5},
        {"display": ":1", "keys": "ctrl+c"},
        {"display": ":1", "keys": "ctrl+shift+t"},
    ]


def test_terminal_streams_through_the_guest(client, alice, sandbox):
    sid = sandbox["id"]
    assert client.post(f"/sandboxes/{sid}/terminal-ticket", headers=alice).status_code == 409

    def reply(op, args, payload):
        if op == "pty_open":
            return {"stream": args["stream"]}, b""
        if op == "pty_input":
            fake.ws.send_bytes(pack({"op": "pty_data", "stream": args["stream"]}, payload.upper()))
            if payload == b"exit\n":
                fake.ws.send_bytes(pack({"op": "pty_exit", "stream": args["stream"], "exit_code": 3}))
        return None

    hub.bind(runtime_of(sid), sid)
    with FakeGuest(sid, reply) as fake:
        ticket = client.post(f"/sandboxes/{sid}/terminal-ticket", headers=alice).json()["ticket"]
        url = f"/sandboxes/{sid}/terminal?ticket={ticket}&cols=100&rows=30"
        with client.websocket_connect(url) as term:
            term.send_bytes(b"ls\n")
            assert term.receive_bytes() == b"LS\n"
            term.send_text(json.dumps({"type": "resize", "cols": 120, "rows": 40}))
            term.send_bytes(b"exit\n")
            assert term.receive_bytes() == b"EXIT\n"
            assert json.loads(term.receive_text()) == {"type": "exit", "code": 3}
        # a ticket opens one terminal
        with pytest.raises(WebSocketDisconnect), client.websocket_connect(url) as again:
            again.receive_bytes()
    ops = [(op, {k: v for k, v in args.items() if k != "stream"}) for op, args, _ in fake.calls]
    assert ops[:4] == [
        ("pty_open", {"argv": [], "cols": 100, "rows": 30}),
        ("pty_input", {}),
        ("pty_resize", {"cols": 120, "rows": 40}),
        ("pty_input", {}),
    ]


def test_monitoring_falls_back_to_guest_metrics():
    hub.bind("rt-metrics", "sb-metrics")
    assert guest_usage("sb-metrics") is None
    with FakeGuest("sb-metrics", lambda op, args, payload: ({}, b"")):
        assert guest_usage("sb-metrics") == {
            "cpu_percent": 5,
            "memory_usage": 0,
            "memory_limit": 0,
            "memory_percent": 0.0,
            "network_rx": 0,
            "network_tx": 0,
            "pids": 0,
            "status": "running",
        }
