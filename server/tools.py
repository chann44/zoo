import subprocess
import docker


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


def exec():
    pass


def click(container_id, x, y, display=":1", button="left"):
    container = client.containers.get(container_id)
    buttons = {
        "left": 1,
        "right": 2,
        "middle": 3,
    }

    if button not in buttons:
        raise ValueError(
            f"Invalid button {button}"
        )
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


def apps():
    pass


def open_app():
    pass
