import subprocess
import docker
import asyncio
import re
import os
import time


client = docker.from_env()


def screenshot(
    container_id,
    display=":1",
):
    container = client.containers.get(container_id=container_id)

    result = container.exec_run(
        [
            "import",
            "-display",
            display,
            "-window",
            "root",
            "png:-",
        ],
        stdout=True,
        stderr=True,
    )

    if result.exit_code != 0:
        raise RuntimeError(result.output.decode())

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

def click(container_id, x, y, display=":1", button="left"):
    container = client.containers.get(container_id)
    buttons = {
        "left": 1,
        "right": 2,
        "middle": 3,
    }

    if button not in buttons:
        raise ValueError(f"Invalid button {button}")
    result = container.exec_run(
        [
            "xdotool",
            "mousemove",
            "--sync",
            str(x),
            str(y),
            "click",
            str(buttons[button]),
        ],
        environment={
            "DISPLAY": display,
        },
    )

    if result.exit_code != 0:
        raise RuntimeError(result.output.decode())
    return {
        "success": True,
        "x": x,
        "y": y,
        "button": button,
    }


def type():
    pass


def key():
    pass


def windows_list(container_id: str, display: str = ":1"):
    container = client.containers.get(container_id)
    windows = []

    res = container.exec_run(
        ["xdotool", "search", "--onlyvisible", "--class", ".*"],
        environment={"DISPLAY": display}
    )

    window_ids = res.output.decode("utf-8").splitlines()

    for win in window_ids:
        win_id = win.strip()
        if not win_id:
            continue

        name_res = container.exec_run(
            ["xdotool", "getwindowname", win_id],
            environment={"DISPLAY": display}
        )
        title = name_res.output.decode("utf-8").strip()

        if title:
            windows.append({"id": win_id, "title": title})

    return windows


def window_focus(container_id: str, window_id: str, display:str = ":1"):
    container = client.containers.get(container_id)

    res = container.exec_run(
        ["xdotool", "windowactivate", window_id],
        environment={"DISPLAY": display}
    )
    print(res)

    return res.exit_code == 0


def installed_apps(container_id: str) -> dict:
    container = client.containers.get(container_id)

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
    gui_output = gui_res.output.decode("utf-8").strip()

    gui_apps = []
    if gui_output:
        for line in gui_output.splitlines():
            if "|" in line:
                name, raw_exec = line.split("|", 1)
                raw_exec = raw_exec.strip()
                cleaned_exec = re.sub(r'\s%[uUfFiIcCkK]', '', raw_exec).strip()
                first_token = cleaned_exec.split()[0] if cleaned_exec else ""
                binary_name = os.path.basename(first_token)

                gui_apps.append({
                    "name": name.strip(),
                    "binary": binary_name,
                    "exec": cleaned_exec
                })

    apt_res = container.exec_run(["apt-mark", "showmanual"])
    apt_output = apt_res.output.decode("utf-8").strip()
    apt_packages = [pkg.strip() for pkg in apt_output.splitlines() if pkg.strip()]

    return {"gui_apps": gui_apps, "apt_packages": apt_packages}


def open_app(container_id: str, command: str, display: str = ":1",
             timeout: float = 4.0) -> dict:
    """
    Launches `command` inside the container and verifies it actually started —
    both that the process is alive and that a window appeared for it.
    """
    container = client.containers.get(container_id)
    env = {"DISPLAY": display}

    cleaned_cmd = re.sub(r'\s%[uUfFiIcCkK]', '', command).strip()
    binary_name = os.path.basename(cleaned_cmd.split()[0]) if cleaned_cmd else ""

    launch_cmd = f"nohup {cleaned_cmd} >/dev/null 2>&1 & echo $!"
    res = container.exec_run(["bash", "-c", launch_cmd], environment=env)
    output = res.output.decode("utf-8").strip()

    try:
        pid = int(output.splitlines()[-1])
    except (ValueError, IndexError):
        return {"started": False, "pid": None, "reason": "failed to capture pid"}

    deadline = time.time() + timeout
    pid_alive = False
    while time.time() < deadline:
        check = container.exec_run(
            ["bash", "-c", f"kill -0 {pid} 2>/dev/null && echo alive"],
            environment=env
        )
        if b"alive" in check.output:
            pid_alive = True
            break
        time.sleep(0.2)

    win_deadline = time.time() + timeout
    window_found = False
    while time.time() < win_deadline:
        win_check = container.exec_run(
            ["xdotool", "search", "--pid", str(pid)], environment=env
        )
        if win_check.output.decode("utf-8").strip():
            window_found = True
            break

        name_check = container.exec_run(
            ["xdotool", "search", "--onlyvisible", "--name", binary_name],
            environment=env
        )
        if name_check.output.decode("utf-8").strip():
            window_found = True
            break

        time.sleep(0.3)

    started = pid_alive or window_found
    return {
        "started": started,
        "pid": pid,
        "pid_alive": pid_alive,
        "window_found": window_found,
    }


def close_app(container_id: str, target: str, display: str = ":1") -> bool:
    container = client.containers.get(container_id)
    env = {"DISPLAY": display}

    if target.isdigit():
        res = container.exec_run(["xdotool", "windowclose", target], environment=env)
        return res.exit_code == 0

    search_res = container.exec_run(
        ["xdotool", "search", "--onlyvisible", "--name", target],
        environment=env
    )
    window_ids = search_res.output.decode("utf-8").splitlines()

    if not window_ids:
        print(f"No active window found matching: {target}")
        return False

    success = True
    for win_id in window_ids:
        win_id = win_id.strip()
        if win_id:
            close_res = container.exec_run(["xdotool", "windowclose", win_id], environment=env)
            if close_res.exit_code != 0:
                success = False

    return success