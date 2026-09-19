import asyncio
import docker
import io
import os
import re
import tarfile
import time

from pathlib import PurePosixPath


client = docker.from_env()


def get_container(container_id: str):
    return client.containers.get(container_id)


def run_x(container_id: str, args: list[str], display: str = ":1"):
    container = get_container(container_id)
    result = container.exec_run(
        args,
        environment={"DISPLAY": display},
    )

    if result.exit_code != 0:
        output = result.output
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        raise RuntimeError(output)

    return result


def screenshot(container_id: str, display: str = ":1"):
    container = get_container(container_id)

    result = container.exec_run(
        ["import", "-display", display, "-window", "root", "png:-"],
        stdout=True,
        stderr=True,
    )

    if result.exit_code != 0:
        raise RuntimeError(result.output.decode(errors="replace"))

    return result.output


async def execute_command(
    container_id: str,
    command: str,
    timeout: int = 30,
) -> dict:
    process = await asyncio.create_subprocess_exec(
        "docker",
        "exec",
        container_id,
        "sh",
        "-lc",
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout,
        )

        return {
            "exit_code": process.returncode,
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
            "timed_out": False,
        }

    except asyncio.TimeoutError:
        process.kill()
        stdout, stderr = await process.communicate()

        return {
            "exit_code": 124,
            "stdout": stdout.decode(errors="replace"),
            "stderr": stderr.decode(errors="replace"),
            "timed_out": True,
        }


def click(
    container_id: str,
    x: int,
    y: int,
    display: str = ":1",
    button: str = "left",
):
    buttons = {"left": 1, "middle": 2, "right": 3}

    if button not in buttons:
        raise ValueError("Invalid button")

    run_x(
        container_id,
        [
            "xdotool",
            "mousemove",
            "--sync",
            str(x),
            str(y),
            "click",
            str(buttons[button]),
        ],
        display,
    )

    return {
        "success": True,
        "x": x,
        "y": y,
        "button": button,
    }


def double_click(
    container_id: str,
    x: int,
    y: int,
    display: str = ":1",
    button: str = "left",
):
    buttons = {"left": 1, "middle": 2, "right": 3}

    if button not in buttons:
        raise ValueError("Invalid button")

    run_x(
        container_id,
        [
            "xdotool",
            "mousemove",
            "--sync",
            str(x),
            str(y),
            "click",
            "--repeat",
            "2",
            "--delay",
            "100",
            str(buttons[button]),
        ],
        display,
    )

    return {
        "success": True,
        "x": x,
        "y": y,
        "button": button,
    }


def scroll(
    container_id: str,
    direction: str,
    amount: int = 3,
    x: int = None,
    y: int = None,
    display: str = ":1",
):
    buttons = {"up": 4, "down": 5, "left": 6, "right": 7}

    if direction not in buttons:
        raise ValueError("Invalid scroll direction")

    if amount < 1:
        raise ValueError("Amount must be >= 1")

    if (x is None) != (y is None):
        raise ValueError("Both x and y must be provided")

    if x is not None:
        run_x(
            container_id,
            ["xdotool", "mousemove", "--sync", str(x), str(y)],
            display,
        )

    run_x(
        container_id,
        [
            "xdotool",
            "click",
            "--repeat",
            str(amount),
            "--delay",
            "80",
            str(buttons[direction]),
        ],
        display,
    )

    return {
        "success": True,
        "direction": direction,
        "amount": amount,
    }


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
    buttons = {"left": 1, "middle": 2, "right": 3}

    if button not in buttons:
        raise ValueError("Invalid button")

    run_x(
        container_id,
        [
            "xdotool",
            "mousemove",
            "--sync",
            str(start_x),
            str(start_y),
            "mousedown",
            str(buttons[button]),
            "sleep",
            str(duration),
            "mousemove",
            "--sync",
            str(end_x),
            str(end_y),
            "mouseup",
            str(buttons[button]),
        ],
        display,
    )

    return {
        "success": True,
        "start": [start_x, start_y],
        "end": [end_x, end_y],
        "button": button,
    }


def type_text(
    container_id: str,
    text: str,
    display: str = ":1",
    delay: int = 12,
):
    run_x(
        container_id,
        [
            "xdotool",
            "type",
            "--clearmodifiers",
            "--delay",
            str(delay),
            "--",
            text,
        ],
        display,
    )

    return {
        "success": True,
        "length": len(text),
    }


def press_key(
    container_id: str,
    key: str,
    display: str = ":1",
):
    run_x(
        container_id,
        ["xdotool", "key", "--clearmodifiers", key],
        display,
    )

    return {
        "success": True,
        "key": key,
    }


def hotkey(
    container_id: str,
    *keys: str,
    display: str = ":1",
):
    if not keys:
        raise ValueError("At least one key is required")

    run_x(
        container_id,
        [
            "xdotool",
            "key",
            "--clearmodifiers",
            "+".join(keys),
        ],
        display,
    )

    return {
        "success": True,
        "keys": list(keys),
    }


def windows_list(container_id: str, display: str = ":1"):
    result = run_x(
        container_id,
        ["xdotool", "search", "--onlyvisible", "--class", ".*"],
        display,
    )

    windows = []

    for window_id in result.output.decode().splitlines():
        title_result = run_x(
            container_id,
            ["xdotool", "getwindowname", window_id],
            display,
        )

        title = title_result.output.decode(errors="replace").strip()

        windows.append(
            {
                "id": window_id,
                "title": title,
            }
        )

    return windows


def window_focus(
    container_id: str,
    window_id: str,
    display: str = ":1",
):
    run_x(
        container_id,
        ["xdotool", "windowactivate", "--sync", str(window_id)],
        display,
    )

    return True


def window_minimize(
    container_id: str,
    window_id: str,
    display: str = ":1",
):
    run_x(
        container_id,
        ["xdotool", "windowminimize", str(window_id)],
        display,
    )

    return True


def window_restore(
    container_id: str,
    window_id: str,
    display: str = ":1",
):
    run_x(
        container_id,
        ["xdotool", "windowmap", str(window_id)],
        display,
    )

    run_x(
        container_id,
        ["xdotool", "windowactivate", str(window_id)],
        display,
    )

    return True


def window_maximize(
    container_id: str,
    window_id: str,
    display: str = ":1",
):
    run_x(
        container_id,
        [
            "wmctrl",
            "-ir",
            str(window_id),
            "-b",
            "add,maximized_vert,maximized_horz",
        ],
        display,
    )

    return True


def window_unmaximize(
    container_id: str,
    window_id: str,
    display: str = ":1",
):
    run_x(
        container_id,
        [
            "wmctrl",
            "-ir",
            str(window_id),
            "-b",
            "remove,maximized_vert,maximized_horz",
        ],
        display,
    )

    return True


def window_close(
    container_id: str,
    window_id: str,
    display: str = ":1",
):
    run_x(
        container_id,
        ["xdotool", "windowclose", str(window_id)],
        display,
    )

    return True


def installed_apps(container_id: str) -> dict:
    container = get_container(container_id)

    gui_script = """
    for f in /usr/share/applications/*.desktop; do
        [ -f "$f" ] || continue
        name=$(grep -m1 '^Name=' "$f" | cut -d'=' -f2-)
        exec=$(grep -m1 '^Exec=' "$f" | cut -d'=' -f2-)
        no_display=$(grep -m1 '^NoDisplay=' "$f" | cut -d'=' -f2-)

        if [ "$no_display" != "true" ] && [ -n "$name" ]; then
            echo "$name | $exec"
        fi
    done
    """

    gui_res = container.exec_run(["bash", "-c", gui_script])
    gui_output = gui_res.output.decode(errors="replace").strip()

    gui_apps = []

    if gui_output:
        for line in gui_output.splitlines():
            if "|" not in line:
                continue

            name, raw_exec = line.split("|", 1)
            raw_exec = raw_exec.strip()

            cleaned_exec = re.sub(
                r"\s%[uUfFiIcCkK]",
                "",
                raw_exec,
            ).strip()

            first_token = cleaned_exec.split()[0] if cleaned_exec else ""
            binary_name = os.path.basename(first_token)

            gui_apps.append(
                {
                    "name": name.strip(),
                    "binary": binary_name,
                    "exec": cleaned_exec,
                }
            )

    apt_res = container.exec_run(["apt-mark", "showmanual"])
    apt_output = apt_res.output.decode(errors="replace").strip()

    apt_packages = [pkg.strip() for pkg in apt_output.splitlines() if pkg.strip()]

    return {
        "gui_apps": gui_apps,
        "apt_packages": apt_packages,
    }


def open_app(
    container_id: str,
    command: str,
    display: str = ":1",
    timeout: float = 4.0,
) -> dict:
    container = get_container(container_id)
    env = {"DISPLAY": display}

    cleaned_cmd = re.sub(
        r"\s%[uUfFiIcCkK]",
        "",
        command,
    ).strip()

    binary_name = os.path.basename(cleaned_cmd.split()[0]) if cleaned_cmd else ""

    launch_cmd = f"nohup {cleaned_cmd} >/dev/null 2>&1 & echo $!"

    res = container.exec_run(
        ["bash", "-c", launch_cmd],
        environment=env,
    )

    output = res.output.decode(errors="replace").strip()

    try:
        pid = int(output.splitlines()[-1])
    except (ValueError, IndexError):
        return {
            "started": False,
            "pid": None,
            "reason": "failed to capture pid",
        }

    deadline = time.time() + timeout
    pid_alive = False

    while time.time() < deadline:
        check = container.exec_run(
            ["bash", "-c", f"kill -0 {pid} 2>/dev/null && echo alive"],
            environment=env,
        )

        if b"alive" in check.output:
            pid_alive = True
            break

        time.sleep(0.2)

    win_deadline = time.time() + timeout
    window_found = False

    while time.time() < win_deadline:
        win_check = container.exec_run(
            ["xdotool", "search", "--pid", str(pid)],
            environment=env,
        )

        if win_check.output.decode(errors="replace").strip():
            window_found = True
            break

        name_check = container.exec_run(
            ["xdotool", "search", "--onlyvisible", "--name", binary_name],
            environment=env,
        )

        if name_check.output.decode(errors="replace").strip():
            window_found = True
            break

        time.sleep(0.3)

    return {
        "started": pid_alive or window_found,
        "pid": pid,
        "pid_alive": pid_alive,
        "window_found": window_found,
    }


def close_app(
    container_id: str,
    target: str,
    display: str = ":1",
) -> bool:
    container = get_container(container_id)
    env = {"DISPLAY": display}

    if target.isdigit():
        res = container.exec_run(
            ["xdotool", "windowclose", target],
            environment=env,
        )
        return res.exit_code == 0

    search_res = container.exec_run(
        ["xdotool", "search", "--onlyvisible", "--name", target],
        environment=env,
    )

    window_ids = search_res.output.decode(errors="replace").splitlines()

    if not window_ids:
        return False

    success = True

    for window_id in window_ids:
        window_id = window_id.strip()

        if window_id:
            close_res = container.exec_run(
                ["xdotool", "windowclose", window_id],
                environment=env,
            )

            if close_res.exit_code != 0:
                success = False

    return success


def upload_file(
    container_id: str,
    local_path: str,
    dest_dir: str,
):
    if not os.path.isfile(local_path):
        raise FileNotFoundError(local_path)

    filename = os.path.basename(local_path)
    buffer = io.BytesIO()

    with tarfile.open(fileobj=buffer, mode="w") as tar:
        tar.add(local_path, arcname=filename)

    container = get_container(container_id)

    success = container.put_archive(
        dest_dir,
        buffer.getvalue(),
    )

    if not success:
        raise RuntimeError("Docker failed to upload file")

    return {
        "success": True,
        "filename": filename,
        "destination": str(PurePosixPath(dest_dir) / filename),
    }


def download_file(
    container_id: str,
    container_path: str,
) -> bytes:
    container = get_container(container_id)

    stream, _ = container.get_archive(container_path)
    archive_bytes = b"".join(stream)

    with tarfile.open(
        fileobj=io.BytesIO(archive_bytes),
        mode="r:*",
    ) as tar:
        members = [member for member in tar.getmembers() if member.isfile()]

        if not members:
            raise FileNotFoundError(container_path)

        extracted = tar.extractfile(members[0])

        if extracted is None:
            raise RuntimeError("Could not read archived file")

        return extracted.read()


def _fs(container_id: str, args: list[str]) -> str:
    result = get_container(container_id).exec_run(args)

    if result.exit_code != 0:
        output = result.output
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        raise RuntimeError(output)

    return result.output.decode(errors="replace")


def list_files(container_id: str, path: str = "."):
    output = _fs(
        container_id,
        [
            "find",
            path,
            "-maxdepth",
            "1",
            "-mindepth",
            "1",
            "-printf",
            "%f\\t%y\\t%s\\n",
        ],
    )

    files = []

    for line in output.splitlines():
        parts = line.split("\t")

        if len(parts) == 3:
            name, kind, size = parts

            files.append(
                {
                    "name": name,
                    "type": "directory" if kind == "d" else "file",
                    "size": int(size),
                }
            )

    return files


def get_file_info(container_id: str, path: str):
    output = _fs(
        container_id,
        ["stat", "-c", "%n|%F|%s|%a|%Y", path],
    ).strip()

    name, kind, size, mode, mtime = output.split("|", 4)

    return {
        "path": name,
        "type": kind,
        "size": int(size),
        "permissions": mode,
        "modified_at": int(mtime),
    }


def create_directory(container_id: str, path: str):
    _fs(container_id, ["mkdir", "-p", path])

    return {
        "success": True,
        "path": path,
    }


def delete_file(container_id: str, path: str):
    _fs(container_id, ["rm", "-rf", "--", path])

    return {
        "success": True,
        "path": path,
    }


def move_file(container_id: str, source: str, destination: str):
    _fs(container_id, ["mv", "--", source, destination])

    return {
        "success": True,
        "source": source,
        "destination": destination,
    }


def copy_file(container_id: str, source: str, destination: str):
    _fs(container_id, ["cp", "-a", "--", source, destination])

    return {
        "success": True,
        "source": source,
        "destination": destination,
    }


def read_file(container_id: str, path: str):
    return _fs(container_id, ["cat", "--", path])


def write_file(container_id: str, path: str, content: str):
    target = PurePosixPath(path)

    if target.name in ("", ".", ".."):
        raise ValueError("A filename is required")

    buffer = io.BytesIO()
    data = content.encode("utf-8")

    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tarfile.TarInfo(name=target.name)
        info.size = len(data)
        info.mode = 0o644

        tar.addfile(info, io.BytesIO(data))

    container = get_container(container_id)

    parent = str(target.parent)

    if parent == ".":
        parent = "."

    success = container.put_archive(
        parent,
        buffer.getvalue(),
    )

    if not success:
        raise RuntimeError("Failed to write file")

    return {
        "success": True,
        "path": str(target),
        "size": len(data),
    }
