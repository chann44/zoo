import json
import shlex
import time

from server import a11y
from server.macos import ENV_FILE, guest, guest_check

APP_DIRS = '/Applications /System/Applications /System/Applications/Utilities "$HOME/Applications"'


def osascript(container_id: str, script: str) -> str:
    return guest_check(container_id, f"osascript -e {shlex.quote(script)}", ssh=True).strip()


def window_ref(window_id: str) -> tuple[str, int]:
    app, _, index = str(window_id).rpartition(":")
    if not app or not index.isdigit():
        raise ValueError("window_id must look like 'App:1' (from windows_list)")
    return app, int(index)


def on_window(container_id: str, window_id: str, action: str):
    app, index = window_ref(window_id)
    osascript(
        container_id,
        f'tell application "System Events" to tell process "{app}"\nset w to window {index}\n{action}\nend tell',
    )
    return True


class MacWindows:
    @staticmethod
    def windows_list(container_id: str, display: str = ":1"):
        output = osascript(
            container_id,
            'set out to ""\n'
            'tell application "System Events"\n'
            "repeat with p in (every process whose background only is false)\n"
            "set i to 0\n"
            "repeat with w in windows of p\n"
            "set i to i + 1\n"
            'set out to out & (name of p) & ":" & i & tab & (name of w as text) & linefeed\n'
            "end repeat\nend repeat\nend tell\nreturn out",
        )
        return [
            {"id": window_id, "title": title}
            for window_id, _, title in (line.partition("\t") for line in output.splitlines() if line.strip())
        ]

    @staticmethod
    def window_focus(container_id: str, window_id: str, display: str = ":1"):
        return on_window(container_id, window_id, 'set frontmost to true\nperform action "AXRaise" of w')

    @staticmethod
    def window_minimize(container_id: str, window_id: str, display: str = ":1"):
        return on_window(container_id, window_id, 'set value of attribute "AXMinimized" of w to true')

    @staticmethod
    def window_restore(container_id: str, window_id: str, display: str = ":1"):
        return on_window(
            container_id,
            window_id,
            'set value of attribute "AXMinimized" of w to false\nset frontmost to true\nperform action "AXRaise" of w',
        )

    @staticmethod
    def window_maximize(container_id: str, window_id: str, display: str = ":1"):
        app, index = window_ref(window_id)
        osascript(
            container_id,
            'tell application "Finder" to set b to bounds of window of desktop\n'
            f'tell application "System Events" to tell process "{app}"\n'
            f"set position of window {index} to {{0, 25}}\n"
            f"set size of window {index} to {{item 3 of b, (item 4 of b) - 25}}\nend tell",
        )
        return True

    @staticmethod
    def window_unmaximize(container_id: str, window_id: str, display: str = ":1"):
        app, index = window_ref(window_id)
        osascript(
            container_id,
            'tell application "Finder" to set b to bounds of window of desktop\n'
            "set {sw, sh} to {item 3 of b, item 4 of b}\n"
            f'tell application "System Events" to tell process "{app}"\n'
            f"set size of window {index} to {{sw * 2 div 3, sh * 2 div 3}}\n"
            f"set position of window {index} to {{sw div 6, sh div 6}}\nend tell",
        )
        return True

    @staticmethod
    def window_close(container_id: str, window_id: str, display: str = ":1"):
        return on_window(container_id, window_id, 'click (first button of w whose subrole is "AXCloseButton")')


def app_path(container_id: str, name: str) -> str | None:
    bundle = name if name.endswith(".app") else f"{name}.app"
    if bundle.startswith("/"):
        return bundle if guest(container_id, f"[ -d {shlex.quote(bundle)} ]")[0] == 0 else None
    code, out, _ = guest(
        container_id,
        f'set -- {shlex.quote(bundle)}; for d in {APP_DIRS}; do [ -d "$d/$1" ] && echo "$d/$1" && exit 0; done; exit 1',
    )
    return out.decode(errors="replace").strip() if code == 0 else None


def app_running(container_id: str, name: str) -> bool:
    code, out, _ = guest(
        container_id, f"osascript -e {shlex.quote(f'application {chr(34)}{name}{chr(34)} is running')}", ssh=True
    )
    return code == 0 and out.strip() == b"true"


class MacApps:
    @staticmethod
    def installed_apps(container_id: str) -> dict:
        output = guest_check(container_id, f'for d in {APP_DIRS}; do ls -d "$d"/*.app 2>/dev/null; done; true')
        apps = []
        for path in output.splitlines():
            name = path.rsplit("/", 1)[-1][:-4]
            apps.append({"name": name, "binary": name, "exec": f"open -a {shlex.quote(path)}"})
        code, brew, _ = guest(container_id, "command -v brew >/dev/null && brew leaves")
        packages = brew.decode(errors="replace").split() if code == 0 else []
        return {"gui_apps": apps, "brew_packages": packages}

    @staticmethod
    def open_app(container_id: str, command: str, display: str = ":1", timeout: float = 4.0) -> dict:
        command = command.strip()
        if command.startswith("open "):
            guest_check(container_id, command)
            return {"started": True, "pid": None, "pid_alive": True, "window_found": False}
        path = app_path(container_id, command)
        if path is None:
            output = guest_check(container_id, f"nohup {command} >/dev/null 2>&1 & echo $!").strip()
            pid = int(output.splitlines()[-1]) if output else None
            alive = pid is not None and guest(container_id, f"kill -0 {pid}")[0] == 0
            return {"started": alive, "pid": pid, "pid_alive": alive, "window_found": False}
        guest_check(container_id, f"open -a {shlex.quote(path)}")
        name = path.rsplit("/", 1)[-1][:-4]
        deadline = time.time() + timeout
        running = False
        while time.time() < deadline and not running:
            running = app_running(container_id, name)
            if not running:
                time.sleep(0.3)
        return {"started": running, "pid": None, "pid_alive": running, "window_found": running}

    @staticmethod
    def close_app(container_id: str, target: str, display: str = ":1") -> bool:
        if ":" in target and target.rpartition(":")[2].isdigit():
            try:
                return MacWindows.window_close(container_id, target)
            except RuntimeError:
                return False
        quoted = target.replace('"', "")
        code, _, _ = guest(
            container_id,
            f"osascript -e {shlex.quote(f'tell application {chr(34)}{quoted}{chr(34)} to quit')}",
            ssh=True,
        )
        if code != 0:
            code, _, _ = guest(container_id, f"killall {shlex.quote(target)}")
        return code == 0


def open_url(container_id: str, url: str, display: str = ":1") -> dict:
    guest_check(container_id, f"open {shlex.quote(url)}")
    return {"opened": url}


class MacShell:
    @staticmethod
    def execute_command(container_id: str, command: str, timeout: int = 30) -> dict:
        script = (
            f"[ -f {ENV_FILE} ] && . {ENV_FILE}; "
            f"perl -e 'alarm shift; exec @ARGV' {int(timeout)} zsh -lc {shlex.quote(command)}"
        )
        code, out, err = guest(container_id, script, timeout=timeout + 15)
        return {
            "exit_code": code,
            "stdout": out.decode(errors="replace"),
            "stderr": err.decode(errors="replace"),
            "timed_out": code == 142,
        }


def fetch_url(container_id: str, url: str, timeout: int = 20) -> dict:
    return MacShell.execute_command(
        container_id, f"curl -sSL --max-time {int(timeout)} {shlex.quote(url)} | head -c 200000", timeout + 5
    )


class MacFiles:
    @staticmethod
    def list_files(container_id: str, path: str = "."):
        output = guest_check(
            container_id,
            f"find {shlex.quote(path)} -mindepth 1 -maxdepth 1 -exec stat -f '%N%t%HT%t%z' {{}} +",
        )
        files = []
        for line in output.splitlines():
            parts = line.split("\t")
            if len(parts) == 3:
                name, kind, size = parts
                files.append(
                    {
                        "name": name.rsplit("/", 1)[-1],
                        "type": "directory" if kind == "Directory" else "file",
                        "size": int(size),
                    }
                )
        return files

    @staticmethod
    def get_file_info(container_id: str, path: str):
        output = guest_check(container_id, f"stat -f '%N|%HT|%z|%Lp|%m' {shlex.quote(path)}").strip()
        name, kind, size, mode, mtime = output.split("|", 4)
        return {"path": name, "type": kind.lower(), "size": int(size), "permissions": mode, "modified_at": int(mtime)}

    @staticmethod
    def create_directory(container_id: str, path: str):
        guest_check(container_id, f"mkdir -p {shlex.quote(path)}")
        return {"success": True, "path": path}

    @staticmethod
    def delete_file(container_id: str, path: str):
        guest_check(container_id, f"rm -rf -- {shlex.quote(path)}")
        return {"success": True, "path": path}

    @staticmethod
    def move_file(container_id: str, source: str, destination: str):
        guest_check(container_id, f"mv -- {shlex.quote(source)} {shlex.quote(destination)}")
        return {"success": True, "source": source, "destination": destination}

    @staticmethod
    def copy_file(container_id: str, source: str, destination: str):
        guest_check(container_id, f"cp -a -- {shlex.quote(source)} {shlex.quote(destination)}")
        return {"success": True, "source": source, "destination": destination}

    @staticmethod
    def read_file(container_id: str, path: str):
        return guest_check(container_id, f"cat -- {shlex.quote(path)}")

    @staticmethod
    def write_file(container_id: str, path: str, content: str):
        name = path.rstrip("/").rsplit("/", 1)[-1]
        if name in ("", ".", ".."):
            raise ValueError("A filename is required")
        data = content.encode("utf-8")
        guest_check(container_id, f"cat > {shlex.quote(path)}", stdin=data)
        return {"success": True, "path": path, "size": len(data)}


# The fallback when the guest can't read AX itself: System Events over SSH, where the older Accessibility grant
# lives. One Apple event per element for its properties and one for its children, so it takes seconds.
A11Y = r"""
function run(argv) {
  const args = JSON.parse(argv[0]);
  const lower = (s) => String(s || "").toLowerCase();
  const se = Application("System Events");
  let procs = se.processes.whose({ backgroundOnly: false })();
  if (args.app) procs = procs.filter((p) => lower(p.name()).includes(lower(args.app)));
  else if (!args.title) procs = procs.filter((p) => p.frontmost());
  let proc = null, win = null;
  for (const p of procs) {
    win = p.windows().find((w) => !args.title || lower(w.name()).includes(lower(args.title)));
    if (win) { proc = p; break; }
  }
  if (!win) throw new Error("no matching window; pass app or title (see windows_list)");
  const nodes = [];
  let truncated = false;
  const text = (v) => (v === null || v === undefined || typeof v === "object") ? "" : String(v);
  function walk(el, d) {
    if (nodes.length >= args.max_nodes) { truncated = true; return; }
    let p;
    try { p = el.properties(); } catch (e) { return; }
    const states = [];
    if (p.focused) states.push("focused");
    if (p.selected) states.push("selected");
    if (p.enabled === false) states.push("disabled");
    const box = p.position && p.size ? [p.position[0], p.position[1], p.size[0], p.size[1]] : null;
    const role = p.roleDescription || p.role || "";
    const secure = p.subrole === "AXSecureTextField";
    nodes.push({ d, role, name: text(p.name || p.title || p.description), value: secure ? "" : text(p.value), states, box });
    if (d >= 40) return;
    let kids = [];
    try { kids = el.uiElements(); } catch (e) {}
    for (const k of kids) walk(k, d + 1);
  }
  walk(win, 0);
  return JSON.stringify({ app: proc.name(), window: text(win.name()), nodes, truncated });
}
"""


def accessibility_tree(container_id: str, app: str = "", title: str = "", max_nodes: int = a11y.DEFAULT_NODES) -> dict:
    a11y.check(max_nodes)
    tree = a11y.native(container_id, app, title, max_nodes)
    if tree is not None:
        return tree
    args = json.dumps({"app": app, "title": title, "max_nodes": max_nodes})
    out = guest_check(
        container_id, f"osascript -l JavaScript -e {shlex.quote(A11Y)} {shlex.quote(args)}", ssh=True, timeout=120
    )
    return a11y.render(json.loads(out))
