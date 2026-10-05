"""End to end against a real stack: real containers, real tools, real network policy.

    ZOO_RUNTIME=runc docker compose up -d --build
    scripts/e2e.sh        # signs up, makes an API key and runs this suite

runc keeps it runnable on CI machines without nested virtualisation; Kata gets the same test on a KVM runner.
ZOO_E2E_KINDS picks the sandbox kinds (default desktop,browser,code) and ZOO_E2E_SERVER_ID the server for macos and
windows ones, so the nightly Mac and Hyper-V runners run the same suite.
"""

import asyncio
import os

import httpx
import pytest
import websockets
from zoo_sdk import Zoo, ZooError

from server.registry import KINDS, TOOLS
from server.vnc import NO_AUTH, VERSION, Buffered
from tests.tool_args import SAMPLE_ARGS

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not os.environ.get("ZOO_E2E_URL"), reason="set ZOO_E2E_URL and ZOO_E2E_API_KEY to run"),
]
WINDOW_TOOLS = [
    "window_focus",
    "window_minimize",
    "window_restore",
    "window_maximize",
    "window_unmaximize",
    "window_close",
]
BOOT_TIMEOUT = int(os.environ.get("ZOO_E2E_BOOT_TIMEOUT", "240"))
KINDS_UNDER_TEST = os.environ.get("ZOO_E2E_KINDS", "desktop,browser,code").split(",")
SCREENS = [k for k in KINDS_UNDER_TEST if k != "code"]
needs_code = pytest.mark.skipif("code" not in KINDS_UNDER_TEST, reason="code sandboxes aren't under test")


@pytest.fixture(scope="module")
def zoo() -> Zoo:
    return Zoo(api_key=os.environ["ZOO_E2E_API_KEY"], base_url=os.environ["ZOO_E2E_URL"])


@pytest.fixture
def make(zoo):
    created = []

    def make(kind: str):
        server_id = os.environ.get("ZOO_E2E_SERVER_ID") if kind in ("macos", "windows") else None
        sandbox = zoo.create(name=f"e2e-{kind}", kind=kind, server_id=server_id, timeout=BOOT_TIMEOUT)
        created.append(sandbox)
        return sandbox

    yield make
    for sandbox in created:
        try:
            sandbox.delete()
        except ZooError:
            pass


def a_window(sandbox, kind: str) -> str:
    """A window the window tools can act on: a fresh terminal where apps are allowed, else Firefox."""
    if kind != "browser":
        sandbox.tool("open_app", **SAMPLE_ARGS["open_app"])
    windows = sandbox.tool("windows_list")
    match = [w for w in windows if "Terminal" in w["title"]] if kind != "browser" else windows
    assert match, f"no window to act on in {windows}"
    return match[0]["id"]


@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_every_tool_runs(make, kind):
    sandbox = make(kind)
    allowed = KINDS[kind]
    names = [n for n in SAMPLE_ARGS if n not in WINDOW_TOOLS and (allowed is None or TOOLS[n].category in allowed)]
    if "open_app" in names:
        names.remove("close_app")
        names.append("close_app")
    for name in names:
        if name == "close_app":
            sandbox.tool("open_app", **SAMPLE_ARGS["open_app"])
        result = sandbox.tool(name, **SAMPLE_ARGS[name])
        if name == "read_file":
            assert "zoo" in str(result)
        if name == "execute_command":
            assert result["exit_code"] == 0 and result["stdout"].strip() == "zoo"
    if allowed is None or "windows" in allowed:
        window_id = a_window(sandbox, kind)
        for name in WINDOW_TOOLS:
            sandbox.tool(name, window_id=window_id)


@pytest.mark.parametrize("kind", KINDS_UNDER_TEST)
def test_tools_outside_the_kind_are_refused(make, kind):
    allowed = KINDS[kind]
    if allowed is None:
        pytest.skip("desktop sandboxes allow every tool")
    sandbox = make(kind)
    refused = next(n for n, t in TOOLS.items() if t.category not in allowed)
    with pytest.raises(ZooError, match="400"):
        sandbox.tool(refused, **SAMPLE_ARGS[refused])


@needs_code
def test_deny_network_policy_blocks_traffic(make):
    sandbox = make("code")
    probe = "curl -sS -o /dev/null --max-time 8 -w '%{http_code}' https://example.com"
    assert sandbox.exec(probe, timeout=20)["exit_code"] == 0

    sandbox.set_network("deny", allow_dns=True)
    assert sandbox.exec(probe, timeout=20)["exit_code"] != 0

    sandbox.add_rule("domain", "example.com", "allow")
    assert sandbox.exec(probe, timeout=20)["exit_code"] == 0


@needs_code
def test_lifecycle(zoo, make):
    sandbox = make("code")
    sandbox.exec("echo kept > ~/kept.txt")
    sandbox.stop()
    assert sandbox.refresh().status == "stopped"
    sandbox.start()
    assert sandbox.exec("cat ~/kept.txt")["stdout"].strip() == "kept"
    sandbox.delete()
    assert sandbox.id not in [s.id for s in zoo.sandboxes()]


@pytest.mark.parametrize("kind", SCREENS)
def test_viewer_gets_the_screen_without_a_password(make, kind):
    """The API logs in to the sandbox's VNC server itself and offers the browser no auth, behind a one-time ticket."""
    sandbox = make(kind)
    url = os.environ["ZOO_E2E_URL"].rstrip("/")
    headers = {"Authorization": f"Bearer {os.environ['ZOO_E2E_API_KEY']}"}
    ticket = httpx.post(f"{url}/sandboxes/{sandbox.id}/vnc-ticket", headers=headers).json()["ticket"]
    socket = f"{url.replace('http', 'ws', 1)}/sandboxes/{sandbox.id}/ws?ticket={ticket}"

    async def handshake() -> bytes:
        async with websockets.connect(socket, max_size=None) as ws:

            async def receive() -> bytes:
                message = await ws.recv()
                return message if isinstance(message, bytes) else message.encode()

            screen = Buffered(receive)
            assert await screen.read(12) == VERSION
            await ws.send(VERSION)
            assert await screen.read(2) == bytes([1, NO_AUTH])
            await ws.send(bytes([NO_AUTH]))
            assert await screen.read(4) == b"\0\0\0\0"
            await ws.send(b"\x01")  # ClientInit, shared
            return await screen.read(4)  # ServerInit starts with the framebuffer width and height

    size = asyncio.run(asyncio.wait_for(handshake(), 30))
    assert int.from_bytes(size[:2], "big") > 0 and int.from_bytes(size[2:], "big") > 0

    async def reuse():
        async with websockets.connect(socket):
            pass

    # the ticket is spent: the API refuses the websocket before accepting it
    with pytest.raises(websockets.exceptions.InvalidStatus):
        asyncio.run(reuse())
