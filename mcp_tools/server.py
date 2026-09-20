import base64

from mcp.server.mcpserver import MCPServer

import server.tools as ct

mcp = MCPServer("computer-control")


@mcp.tool()
def screenshot(container_id: str, display: str = ":1") -> str:
    data = ct.screenshot(container_id, display)
    return base64.b64encode(data).decode()


@mcp.tool()
async def execute_command(container_id: str, command: str, timeout: int = 30) -> dict:
    return await ct.execute_command(container_id, command, timeout)


@mcp.tool()
def click(
    container_id: str, x: int, y: int, display: str = ":1", button: str = "left"
) -> dict:
    return ct.click(container_id, x, y, display, button)


@mcp.tool()
def double_click(
    container_id: str, x: int, y: int, display: str = ":1", button: str = "left"
) -> dict:
    return ct.double_click(container_id, x, y, display, button)


@mcp.tool()
def scroll(
    container_id: str,
    direction: str,
    amount: int = 3,
    x: int | None = None,
    y: int | None = None,
    display: str = ":1",
) -> dict:
    return ct.scroll(container_id, direction, amount, x, y, display)


@mcp.tool()
def drag(
    container_id: str,
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    display: str = ":1",
    button: str = "left",
    duration: float = 0.5,
) -> dict:
    return ct.drag(
        container_id, start_x, start_y, end_x, end_y, display, button, duration
    )


@mcp.tool()
def type_text(
    container_id: str, text: str, display: str = ":1", delay: int = 12
) -> dict:
    return ct.type_text(container_id, text, display, delay)


@mcp.tool()
def press_key(container_id: str, key: str, display: str = ":1") -> dict:
    return ct.press_key(container_id, key, display)


@mcp.tool()
def hotkey(container_id: str, keys: list[str], display: str = ":1") -> dict:
    return ct.hotkey(container_id, *keys, display=display)


@mcp.tool()
def windows_list(container_id: str, display: str = ":1") -> list:
    return ct.windows_list(container_id, display)


@mcp.tool()
def window_focus(container_id: str, window_id: str, display: str = ":1") -> bool:
    return ct.window_focus(container_id, window_id, display)


@mcp.tool()
def window_minimize(container_id: str, window_id: str, display: str = ":1") -> bool:
    return ct.window_minimize(container_id, window_id, display)


@mcp.tool()
def window_restore(container_id: str, window_id: str, display: str = ":1") -> bool:
    return ct.window_restore(container_id, window_id, display)


@mcp.tool()
def window_maximize(container_id: str, window_id: str, display: str = ":1") -> bool:
    return ct.window_maximize(container_id, window_id, display)


@mcp.tool()
def window_unmaximize(container_id: str, window_id: str, display: str = ":1") -> bool:
    return ct.window_unmaximize(container_id, window_id, display)


@mcp.tool()
def window_close(container_id: str, window_id: str, display: str = ":1") -> bool:
    return ct.window_close(container_id, window_id, display)


@mcp.tool()
def installed_apps(container_id: str) -> dict:
    return ct.installed_apps(container_id)


@mcp.tool()
def open_app(
    container_id: str, command: str, display: str = ":1", timeout: float = 4.0
) -> dict:
    return ct.open_app(container_id, command, display, timeout)


@mcp.tool()
def close_app(container_id: str, target: str, display: str = ":1") -> bool:
    return ct.close_app(container_id, target, display)


@mcp.tool()
def upload_file(container_id: str, local_path: str, dest_dir: str) -> dict:
    return ct.upload_file(container_id, local_path, dest_dir)


@mcp.tool()
def download_file(container_id: str, container_path: str) -> str:
    data = ct.download_file(container_id, container_path)
    return base64.b64encode(data).decode()


@mcp.tool()
def list_files(container_id: str, path: str = ".") -> list:
    return ct.list_files(container_id, path)


@mcp.tool()
def get_file_info(container_id: str, path: str) -> dict:
    return ct.get_file_info(container_id, path)


@mcp.tool()
def create_directory(container_id: str, path: str) -> dict:
    return ct.create_directory(container_id, path)


@mcp.tool()
def delete_file(container_id: str, path: str) -> dict:
    return ct.delete_file(container_id, path)


@mcp.tool()
def move_file(container_id: str, source: str, destination: str) -> dict:
    return ct.move_file(container_id, source, destination)


@mcp.tool()
def copy_file(container_id: str, source: str, destination: str) -> dict:
    return ct.copy_file(container_id, source, destination)


@mcp.tool()
def read_file(container_id: str, path: str) -> str:
    return ct.read_file(container_id, path)


@mcp.tool()
def write_file(container_id: str, path: str, content: str) -> dict:
    return ct.write_file(container_id, path, content)
