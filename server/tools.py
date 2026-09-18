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


def click():
    pass


def type():
    pass


def key():
    pass


def apps():
    pass


def open_app():
    pass
