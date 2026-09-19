import subprocess
import docker
import asyncio


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




def window_focus():
    pass

def open_app():
    pass

def close_app():
    pass
