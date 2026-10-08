"""The connection gateway (server/gateway.py): a process that holds the guest and node connections, and the remote
hubs other processes reach them through. A real uvicorn server plays the gateway; a websocket client plays the
sandbox's guest, and a socket pair plays a node's tunnel."""

import asyncio
import socket
import threading
import time

import pytest
import uvicorn
from fastapi import FastAPI
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from server import gateway, guest, nodes
from server.guest import RemoteHub, Terminal, Tunnel, hub, pack, token, unpack


@pytest.fixture
def gateway_url(monkeypatch):
    app = FastAPI()
    app.websocket("/guest/connect")(hub.serve)
    gateway.register(app)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline
        time.sleep(0.02)
    url = f"http://127.0.0.1:{port}"
    monkeypatch.setattr(gateway, "URL", url)
    yield url
    server.should_exit = True
    thread.join(10)


class Guest:
    """A sandbox's guest dialing the gateway: answers exec, echoes tunnel writes back, runs a fake pty."""

    def __init__(self, url: str, sandbox_id: str):
        self.sandbox_id = sandbox_id
        self.ws = connect(
            url.replace("http", "ws") + "/guest/connect",
            additional_headers={"authorization": f"Bearer {token(sandbox_id)}", "x-zoo-sandbox": sandbox_id},
        )
        services = ["exec", "pty", "tunnel", "metrics"]
        self.ws.send(pack({"op": "hello", "version": guest.VERSION, "os": "linux", "services": services}))
        self.ws.send(pack({"op": "metrics", "data": {"cpu_percent": 7}}))
        self.notes: list[tuple[str, dict]] = []
        threading.Thread(target=self.serve, daemon=True).start()
        deadline = time.monotonic() + 5
        while sandbox_id not in hub.guests:
            assert time.monotonic() < deadline, "guest never registered"
            time.sleep(0.01)

    def serve(self):
        try:
            for frame in self.ws:
                assert isinstance(frame, bytes)
                header, payload = unpack(frame)
                op, args = header["op"], header.get("args") or {}
                if "id" not in header:
                    self.notes.append((op, args))
                    if op == "tunnel_write":
                        self.ws.send(pack({"op": "tunnel_data", "stream": args["stream"]}, payload.upper()))
                    elif op == "pty_input":
                        self.ws.send(pack({"op": "pty_data", "stream": args["stream"]}, b"$ " + payload))
                        if payload == b"exit\n":
                            self.ws.send(pack({"op": "pty_exit", "stream": args["stream"], "exit_code": 0}))
                    continue
                if op == "exec":
                    out = " ".join(args["argv"]).encode()
                    self.ws.send(
                        pack({"id": header["id"], "ok": True, "result": {"exit_code": 0, "stdout_len": len(out)}}, out)
                    )
                elif op in ("tunnel_open", "pty_open"):
                    self.ws.send(pack({"id": header["id"], "ok": True, "result": {}}))
                    if op == "tunnel_open":
                        self.ws.send(pack({"op": "tunnel_data", "stream": args["stream"]}, b"RFB 003.008\n"))
                else:
                    self.ws.send(pack({"id": header["id"], "ok": False, "error": f"no {op}"}))
        except Exception:
            return

    def close(self):
        self.ws.close()


def test_a_remote_hub_reaches_guests_through_the_gateway(gateway_url):
    remote = RemoteHub()
    assert remote.for_sandbox("sb-gw") is None
    assert remote.status("sb-gw") == {"connected": False}

    connected = Guest(gateway_url, "sb-gw")
    remote.status_of.answers.clear()
    found = remote.for_sandbox("sb-gw")
    assert found is not None and found.has("exec") and found.os == "linux"
    # the same relay serves later calls
    assert remote.for_sandbox("sb-gw") is found
    assert found.exec_run(["echo", "hi"]) == (0, b"echo hi", b"")
    with pytest.raises(guest.GuestError, match="no screenshot"):
        found.screenshot(":1", "png", 1.0, 80)
    status = remote.status("sb-gw")
    assert status["connected"] and status["services"] == ["exec", "metrics", "pty", "tunnel"]
    assert status["metrics"] == {"cpu_percent": 7}
    assert remote.heartbeat("sb-gw")
    assert found.probe_tunnel(5900)

    async def streams():
        tunnel = Tunnel(found)
        await tunnel.open(5900)
        assert await tunnel.read() == b"RFB 003.008\n"
        await tunnel.write(b"hello")
        assert await tunnel.read() == b"HELLO"
        await tunnel.close()
        terminal = Terminal(found)
        await terminal.open(80, 24)
        await terminal.write(b"exit\n")
        assert await terminal.events.get() == ("data", b"$ exit\n")
        assert await terminal.events.get() == ("exit", 0)

    asyncio.run(streams())
    assert ("tunnel_close", {"stream": next(a["stream"] for o, a in connected.notes if o == "tunnel_write")}) in (
        connected.notes
    )

    # the guest goes away: the gateway closes the relay and the remote hub forgets it
    connected.close()
    deadline = time.monotonic() + 10
    while "sb-gw" in remote.guests:
        assert time.monotonic() < deadline, "relay never closed"
        time.sleep(0.05)
    remote.status_of.answers.clear()
    assert remote.for_sandbox("sb-gw") is None


def test_the_gateway_refuses_without_its_token(gateway_url, monkeypatch):
    Guest(gateway_url, "sb-locked").close()
    monkeypatch.setattr(gateway, "token", lambda: "wrong")
    remote = RemoteHub()
    assert remote.status("sb-locked") == {"connected": False}
    with pytest.raises(InvalidStatus):
        connect(
            gateway_url.replace("http", "ws") + "/internal/guests/sb-locked/relay", additional_headers=gateway.headers()
        )


def test_a_remote_node_hub_tunnels_through_the_gateway(gateway_url, monkeypatch):
    opened: list[tuple[str, str]] = []
    dropped: list[str] = []

    def open_(server_id: str, target: str) -> socket.socket:
        if server_id != "srv":
            raise nodes.Closed("the server's zoo-node is not connected")
        opened.append((server_id, target))
        ours, theirs = socket.socketpair()

        def echo():
            while data := ours.recv(1024):
                ours.sendall(data[::-1])
            ours.close()

        threading.Thread(target=echo, daemon=True).start()
        return theirs

    monkeypatch.setattr(nodes.hub, "open", open_)
    monkeypatch.setattr(nodes.hub, "connected", lambda server_id: server_id == "srv")
    monkeypatch.setattr(nodes.hub, "targets", lambda server_id: {"docker"} if server_id == "srv" else set())
    monkeypatch.setattr(nodes.hub, "drop", dropped.append)

    remote = nodes.RemoteNodeHub()
    assert remote.connected("srv") and remote.targets("srv") == {"docker"}
    assert not remote.connected("other")
    sock = remote.open("srv", "docker")
    sock.sendall(b"abc")
    assert sock.recv(10) == b"cba"
    sock.close()
    assert opened == [("srv", "docker")]
    with pytest.raises(nodes.Closed):
        remote.open("other", "docker")

    # docker-py's unix socket bridge works the same through the gateway
    path = remote.docker_socket("srv")
    with socket.socket(socket.AF_UNIX) as client:
        client.connect(path)
        client.sendall(b"ping")
        assert client.recv(10) == b"gnip"

    remote.drop("srv")
    assert dropped == ["srv"]
