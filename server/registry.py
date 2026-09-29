import base64
import inspect
import shlex
from dataclasses import dataclass
from typing import Any, Callable

from server import macos
from server import macos_tools as mac
from server.tools import (
    AppTools,
    FileSystem,
    KeyboardTools,
    MoseTools,
    ObserveTools,
    ShellTools,
    WindowTools,
    run_x,
)

PERMISSIONS = {
    ("shell", "exec"): "Run shell commands",
    ("screen", "read"): "Take screenshots and list apps",
    ("input", "control"): "Control mouse, keyboard, windows and apps",
    ("files", "read"): "Read files",
    ("files", "write"): "Write, move and delete files",
}


@dataclass
class Tool:
    name: str
    category: str
    fn: Callable[..., Any]
    permission: str
    action: str
    mac: Callable[..., Any]

    def impl(self, runtime_id: str) -> Callable[..., Any]:
        return self.mac if macos.is_vm(runtime_id) else self.fn

    def call(self, runtime_id: str, **args) -> Any:
        return self.impl(runtime_id)(runtime_id, **args)

    @property
    def params(self) -> list[inspect.Parameter]:
        return [p for n, p in inspect.signature(self.fn).parameters.items() if n != "container_id"]

    def schema(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "permission": f"{self.permission}.{self.action}",
            "params": {
                p.name: {
                    "type": getattr(p.annotation, "__name__", str(p.annotation)),
                    "required": p.default is inspect.Parameter.empty,
                }
                for p in self.params
            },
        }


def hotkey(container_id: str, keys: list[str], display: str = ":1") -> dict:
    return KeyboardTools.hotkey(container_id, *keys, display=display)


def screenshot(container_id: str, display: str = ":1") -> str:
    return base64.b64encode(ObserveTools.screenshot(container_id, display)).decode()


def open_url(container_id: str, url: str, display: str = ":1") -> dict:
    run_x(container_id, ["sh", "-c", f"nohup firefox-esr --new-tab {shlex.quote(url)} >/dev/null 2>&1 &"], display)
    return {"opened": url}


def fetch_url(container_id: str, url: str, timeout: int = 20) -> dict:
    return ShellTools.execute_command(container_id, f"curl -sSL --max-time {int(timeout)} {shlex.quote(url)} | head -c 200000", timeout + 5)


KINDS = {
    "desktop": None,
    "browser": {"observe", "mouse", "keyboard", "windows", "browser"},
    "code": {"shell", "files", "web"},
    "macos": None,
}

INPUT = ("input", "control")
SCREEN = ("screen", "read")
READ = ("files", "read")
WRITE = ("files", "write")

TOOLS: dict[str, Tool] = {
    t.name: t
    for t in [
        Tool(name, category, fn, *perm, mac_fn)
        for name, category, fn, mac_fn, perm in [
            ("screenshot", "observe", screenshot, mac.screenshot, SCREEN),
            ("click", "mouse", MoseTools.click, mac.MacMouse.click, INPUT),
            ("double_click", "mouse", MoseTools.double_click, mac.MacMouse.double_click, INPUT),
            ("scroll", "mouse", MoseTools.scroll, mac.MacMouse.scroll, INPUT),
            ("drag", "mouse", MoseTools.drag, mac.MacMouse.drag, INPUT),
            ("type_text", "keyboard", KeyboardTools.type_text, mac.MacKeyboard.type_text, INPUT),
            ("press_key", "keyboard", KeyboardTools.press_key, mac.MacKeyboard.press_key, INPUT),
            ("hotkey", "keyboard", hotkey, mac.hotkey, INPUT),
            ("windows_list", "windows", WindowTools.windows_list, mac.MacWindows.windows_list, SCREEN),
            ("window_focus", "windows", WindowTools.window_focus, mac.MacWindows.window_focus, INPUT),
            ("window_minimize", "windows", WindowTools.window_minimize, mac.MacWindows.window_minimize, INPUT),
            ("window_restore", "windows", WindowTools.window_restore, mac.MacWindows.window_restore, INPUT),
            ("window_maximize", "windows", WindowTools.window_maximize, mac.MacWindows.window_maximize, INPUT),
            ("window_unmaximize", "windows", WindowTools.window_unmaximize, mac.MacWindows.window_unmaximize, INPUT),
            ("window_close", "windows", WindowTools.window_close, mac.MacWindows.window_close, INPUT),
            ("installed_apps", "apps", AppTools.installed_apps, mac.MacApps.installed_apps, SCREEN),
            ("open_app", "apps", AppTools.open_app, mac.MacApps.open_app, INPUT),
            ("close_app", "apps", AppTools.close_app, mac.MacApps.close_app, INPUT),
            ("open_url", "browser", open_url, mac.open_url, INPUT),
            ("fetch_url", "web", fetch_url, mac.fetch_url, ("shell", "exec")),
            ("execute_command", "shell", ShellTools.execute_command, mac.MacShell.execute_command, ("shell", "exec")),
            ("list_files", "files", FileSystem.list_files, mac.MacFiles.list_files, READ),
            ("get_file_info", "files", FileSystem.get_file_info, mac.MacFiles.get_file_info, READ),
            ("read_file", "files", FileSystem.read_file, mac.MacFiles.read_file, READ),
            ("write_file", "files", FileSystem.write_file, mac.MacFiles.write_file, WRITE),
            ("create_directory", "files", FileSystem.create_directory, mac.MacFiles.create_directory, WRITE),
            ("delete_file", "files", FileSystem.delete_file, mac.MacFiles.delete_file, WRITE),
            ("move_file", "files", FileSystem.move_file, mac.MacFiles.move_file, WRITE),
            ("copy_file", "files", FileSystem.copy_file, mac.MacFiles.copy_file, WRITE),
        ]
    ]
}
