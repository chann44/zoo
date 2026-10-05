"""An in-memory stand-in for the Docker backend, so API tests run without Docker, Kata or VMs.

It replaces the functions server/runtime.py dispatches to for Linux sandboxes, plus the names other
modules import from server.docker directly. Tools are served by fake implementations that record calls.
"""

import base64
import itertools
from dataclasses import dataclass, field
from typing import Any

from server import docker, macos, sandbox_api
from server.registry import Tool

# a 1x1 PNG, enough for anything that decodes the screenshot
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)
APPS = [
    {"name": "Firefox", "binary": "firefox-esr"},
    {"name": "Terminal", "binary": "xfce4-terminal"},
]


@dataclass
class Container:
    sandbox_id: str
    image: str
    env: dict[str, str]
    desktop: bool
    running: bool = True
    network: tuple | None = None
    apps: dict[str, str] = field(default_factory=dict)
    dirs: dict[str, bytes] = field(default_factory=dict)
    home: bytes = b""


class FakeRuntime:
    def __init__(self):
        self.reset()

    def reset(self):
        self.containers: dict[str, Container] = {}
        self.volumes: set[str] = set()
        self.calls: list[tuple[str, str, dict]] = []
        self.fail_boot: str | None = None
        self.fail_tool: str | None = None
        self.ids = itertools.count(1)

    def install(self, mp):
        """Patches every runtime entry point; `mp` is a pytest MonkeyPatch."""
        for name in (
            "remove_container",
            "remove_volume",
            "copy_volume",
            "export_dir",
            "import_dir",
            "is_running",
            "apply_network",
            "apply_apps",
            "export_home",
            "import_home",
            "connect",
            "run_container",
            "wait_for_vnc",
        ):
            mp.setattr(docker, name, getattr(self, name))
        for name in ("run_container", "wait_for_vnc", "copy_volume"):
            mp.setattr(sandbox_api, name, getattr(self, name))
        mp.setattr(sandbox_api, "open_url", lambda runtime_id, url: self.calls.append(("open_url", runtime_id, {"url": url})))
        mp.setattr("server.servers_api.connect", self.connect)
        mp.setattr(macos, "local_zoovm", lambda: False)
        fake = self
        mp.setattr(Tool, "impl", lambda tool, runtime_id: fake.tool(tool))

    # Docker backend

    def run_container(self, name, image, sandbox_id, env, server=None, desktop=True):
        if self.fail_boot:
            raise RuntimeError(self.fail_boot)
        runtime_id = f"fake-{next(self.ids)}"
        self.containers[runtime_id] = Container(sandbox_id, image, dict(env), desktop)
        self.volumes.add(sandbox_id)
        return runtime_id, "127.0.0.1", 6080

    def wait_for_vnc(self, host, port, timeout=30):
        return True

    def remove_container(self, runtime_id):
        self.containers.pop(runtime_id, None)

    def remove_volume(self, sandbox_id, server=None):
        self.volumes.discard(sandbox_id)

    def copy_volume(self, sandbox_id, source, target, image=None):
        self.calls.append(("copy_volume", sandbox_id, {"source": source, "target": target}))

    def is_running(self, runtime_id):
        container = self.containers.get(runtime_id)
        return container is not None and container.running

    def connect(self, server_id, url):
        return None

    def apply_network(self, runtime_id, default_action, allow_dns, rules):
        self.containers[runtime_id].network = (default_action, allow_dns, list(rules))

    def apply_apps(self, runtime_id, effects):
        self.containers[runtime_id].apps = dict(effects)

    def export_dir(self, runtime_id, path):
        if path not in self.containers[runtime_id].dirs:
            raise FileNotFoundError(path)
        return self.containers[runtime_id].dirs[path]

    def import_dir(self, runtime_id, parent, data):
        self.containers[runtime_id].dirs[parent] = data

    def export_home(self, runtime_id):
        return iter([self.containers[runtime_id].home])

    def import_home(self, runtime_id, data):
        self.containers[runtime_id].home = data

    # Tools

    def tool(self, tool: Tool):
        def run(runtime_id: str, **args) -> Any:
            self.calls.append((tool.name, runtime_id, args))
            if self.fail_tool:
                raise RuntimeError(self.fail_tool)
            if tool.name == "screenshot":
                return base64.b64encode(PNG).decode()
            if tool.name == "installed_apps":
                return {"gui_apps": APPS}
            if tool.name == "execute_command":
                env = self.containers[runtime_id].env
                stdout = "\n".join(f"{k}={v}" for k, v in env.items()) if args["command"] == "env" else args["command"]
                return {"exit_code": 0, "stdout": stdout, "stderr": "", "timed_out": False}
            return {"tool": tool.name, "args": args}

        return run

    def tool_calls(self, name: str) -> list[dict]:
        return [args for tool, _, args in self.calls if tool == name]
