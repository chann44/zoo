"""Tools for Windows sandboxes. Screen, mouse and keyboard go over VNC (server/vnc_tools.py); window and app tools
run in the desktop session through the guest agent; shell and file tools run over SSH in PowerShell."""

import re

from server.windows import (
    ENV_FILE,
    HOME,
    agent,
    agent_json,
    guest,
    guest_check,
    guest_json,
    q,
)

WINDOW = "[ordered]@{ id = $_.id; title = $_.title; app = $_.app }"


def path_of(path: str) -> str:
    if path == "~" or path.startswith(("~/", "~\\")):
        path = HOME + path[1:]
    return q(path)


def on_window(container_id: str, window_id: str, call: str):
    agent(container_id, f"[ZooWin]::{call.format(id=q(window_id))}")
    return True


class WinWindows:
    @staticmethod
    def windows_list(container_id: str, display: str = ":1"):
        return agent_json(
            container_id, f"ConvertTo-Json -Compress -InputObject @([ZooWin]::List() | ForEach-Object {{ {WINDOW} }})"
        )

    @staticmethod
    def window_focus(container_id: str, window_id: str, display: str = ":1"):
        return on_window(container_id, window_id, "Focus({id})")

    @staticmethod
    def window_minimize(container_id: str, window_id: str, display: str = ":1"):
        return on_window(container_id, window_id, "Show({id}, 6)")

    @staticmethod
    def window_restore(container_id: str, window_id: str, display: str = ":1"):
        return on_window(container_id, window_id, "Focus({id})")

    @staticmethod
    def window_maximize(container_id: str, window_id: str, display: str = ":1"):
        return on_window(container_id, window_id, "Show({id}, 3)")

    @staticmethod
    def window_unmaximize(container_id: str, window_id: str, display: str = ":1"):
        return on_window(container_id, window_id, "Show({id}, 9)")

    @staticmethod
    def window_close(container_id: str, window_id: str, display: str = ":1"):
        return on_window(container_id, window_id, "Close({id})")


INSTALLED_APPS = r"""
$shell = New-Object -ComObject WScript.Shell
$targets = @{}
foreach ($dir in "$env:ProgramData\Microsoft\Windows\Start Menu\Programs", "$env:APPDATA\Microsoft\Windows\Start Menu\Programs") {
    Get-ChildItem -Path $dir -Recurse -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {
        $target = $shell.CreateShortcut($_.FullName).TargetPath
        if ($target -like '*.exe') { $targets[$_.BaseName] = $target }
    }
}
$apps = @(Get-StartApps | ForEach-Object {
    $exe = $targets[$_.Name]
    if (-not $exe -and $_.AppID -like '*.exe') { $exe = $_.AppID }
    [ordered]@{
        name = $_.Name
        binary = $(if ($exe) { Split-Path $exe -Leaf } else { $_.AppID })
        exec = $(if ($exe) { $exe } else { "shell:AppsFolder\$($_.AppID)" })
    }
})
ConvertTo-Json -Compress -Depth 3 -InputObject @{ gui_apps = $apps }
"""

OPEN_APP = r"""
$command = __COMMAND__.Trim()
$before = @{}
foreach ($w in [ZooWin]::List()) { $before[$w.id] = $true }
$app = Get-StartApps | Where-Object { $_.Name -eq $command -or $_.AppID -eq $command } | Select-Object -First 1
$process = $null
if ($app) {
    Start-Process -FilePath ("shell:AppsFolder\" + $app.AppID)
} elseif (Test-Path -LiteralPath $command) {
    $process = Start-Process -FilePath $command -PassThru
} else {
    if ($command.StartsWith('"')) { $file, $rest = $command.Substring(1).Split('"', 2) } else { $file, $rest = $command.Split(' ', 2) }
    $start = @{ FilePath = $file; PassThru = $true }
    if ($rest -and $rest.Trim()) { $start.ArgumentList = $rest.Trim() }
    $process = Start-Process @start
}
$deadline = (Get-Date).AddSeconds(__TIMEOUT__)
$found = $false
while (-not $found -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 300
    $found = [bool]([ZooWin]::List() | Where-Object { -not $before[$_.id] })
}
$alive = $process -eq $null -or -not $process.HasExited
ConvertTo-Json -Compress @{ started = ($found -or $alive); pid = $(if ($process) { $process.Id } else { $null }); pid_alive = $alive; window_found = $found }
"""

CLOSE_APP = r"""
$target = __TARGET__
$name = $target -replace '\.exe$', ''
$windows = @([ZooWin]::List() | Where-Object { $_.app -eq $name -or $_.title -eq $target })
$processes = @(Get-Process -Name $name -ErrorAction SilentlyContinue)
foreach ($w in $windows) { [ZooWin]::Close($w.id) }
foreach ($p in $processes) { [void]$p.CloseMainWindow() }
if ($processes) {
    Start-Sleep -Seconds 3
    $processes | Where-Object { -not $_.HasExited } | Stop-Process -Force -ErrorAction SilentlyContinue
}
if ($windows -or $processes) { 'true' } else { 'false' }
"""


class WinApps:
    @staticmethod
    def installed_apps(container_id: str) -> dict:
        return agent_json(container_id, INSTALLED_APPS, timeout=60)

    @staticmethod
    def open_app(container_id: str, command: str, display: str = ":1", timeout: float = 4.0) -> dict:
        script = OPEN_APP.replace("__COMMAND__", q(command)).replace("__TIMEOUT__", str(float(timeout)))
        return agent_json(container_id, script, timeout=timeout + 30)

    @staticmethod
    def close_app(container_id: str, target: str, display: str = ":1") -> bool:
        if target.isdigit():
            try:
                return WinWindows.window_close(container_id, target)
            except RuntimeError:
                return False
        return agent(container_id, CLOSE_APP.replace("__TARGET__", q(target))) == "true"


def open_url(container_id: str, url: str, display: str = ":1") -> dict:
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", url):
        url = f"https://{url}"
    if not re.match(r"^(https?|file|about|edge):", url, re.IGNORECASE):
        raise ValueError("open_url only opens http(s), file, about and edge URLs")
    agent(container_id, f"Start-Process -FilePath {q(url)}")
    return {"opened": url}


EXECUTE = r"""
if (Test-Path -LiteralPath __ENV__) { . __ENV__ }
$file = Join-Path $env:TEMP ('zoo-' + [guid]::NewGuid().ToString() + '.ps1')
$body = "[Console]::OutputEncoding = [Text.UTF8Encoding]::new(`$false)`n" + [Text.Encoding]::UTF8.GetString((Read-ZooInput)) +
    "`nif (`$global:LASTEXITCODE) { exit `$global:LASTEXITCODE }"
[IO.File]::WriteAllText($file, $body, [Text.UTF8Encoding]::new($true))
$out = "$file.out"; $err = "$file.err"
try {
    $process = Start-Process -FilePath powershell.exe -NoNewWindow -PassThru -WorkingDirectory $HOME `
        -ArgumentList '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', "`"$file`"" `
        -RedirectStandardOutput $out -RedirectStandardError $err
    $null = $process.Handle
    if ($process.WaitForExit(__TIMEOUT_MS__)) { $code = $process.ExitCode } else { taskkill.exe /T /F /PID $process.Id | Out-Null; $code = 124 }
    [Console]::Out.Write([IO.File]::ReadAllText($out))
    [Console]::Error.Write([IO.File]::ReadAllText($err))
} finally {
    Remove-Item -LiteralPath $file, $out, $err -Force -ErrorAction SilentlyContinue
}
exit $code
"""


class WinShell:
    @staticmethod
    def execute_command(container_id: str, command: str, timeout: int = 30) -> dict:
        """Runs a PowerShell command as the sandbox user, with the sandbox's secrets in its environment."""
        script = EXECUTE.replace("__ENV__", q(ENV_FILE)).replace("__TIMEOUT_MS__", str(int(timeout) * 1000))
        code, out, err = guest(container_id, script, command.encode(), timeout=timeout + 30)
        return {
            "exit_code": code,
            "stdout": out.decode(errors="replace"),
            "stderr": err.decode(errors="replace"),
            "timed_out": code == 124,
        }


def fetch_url(container_id: str, url: str, timeout: int = 20) -> dict:
    result = WinShell.execute_command(container_id, f"curl.exe -sSL --max-time {int(timeout)} {q(url)}", timeout + 5)
    result["stdout"] = result["stdout"][:200000]
    return result


ENTRY = (
    "[ordered]@{ name = $_.Name; type = $(if ($_.PSIsContainer) { 'directory' } else { 'file' }); "
    "size = $(if ($_.PSIsContainer) { 0 } else { $_.Length }) }"
)


def resolved(path: str) -> str:
    return f"$ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath({path_of(path)})"


class WinFiles:
    @staticmethod
    def list_files(container_id: str, path: str = "."):
        return guest_json(
            container_id,
            f"ConvertTo-Json -Compress -InputObject @(Get-ChildItem -Force -LiteralPath {path_of(path)} | ForEach-Object {{ {ENTRY} }})",
        )

    @staticmethod
    def get_file_info(container_id: str, path: str):
        return guest_json(
            container_id,
            f"$i = Get-Item -Force -LiteralPath {path_of(path)}\n"
            "ConvertTo-Json -Compress ([ordered]@{ path = $i.FullName; "
            "type = $(if ($i.PSIsContainer) { 'directory' } else { 'regular file' }); "
            "size = $(if ($i.PSIsContainer) { 0 } else { $i.Length }); permissions = $i.Mode; "
            "modified_at = [DateTimeOffset]::new($i.LastWriteTimeUtc).ToUnixTimeSeconds() })",
        )

    @staticmethod
    def create_directory(container_id: str, path: str):
        guest_check(container_id, f"New-Item -ItemType Directory -Force -Path {resolved(path)} | Out-Null")
        return {"success": True, "path": path}

    @staticmethod
    def delete_file(container_id: str, path: str):
        guest_check(container_id, f"Remove-Item -Recurse -Force -LiteralPath {path_of(path)}")
        return {"success": True, "path": path}

    @staticmethod
    def move_file(container_id: str, source: str, destination: str):
        guest_check(
            container_id, f"Move-Item -Force -LiteralPath {path_of(source)} -Destination {resolved(destination)}"
        )
        return {"success": True, "source": source, "destination": destination}

    @staticmethod
    def copy_file(container_id: str, source: str, destination: str):
        guest_check(
            container_id,
            f"Copy-Item -Recurse -Force -LiteralPath {path_of(source)} -Destination {resolved(destination)}",
        )
        return {"success": True, "source": source, "destination": destination}

    @staticmethod
    def read_file(container_id: str, path: str):
        return guest_check(container_id, f"[Console]::Out.Write([IO.File]::ReadAllText({resolved(path)}))")

    @staticmethod
    def write_file(container_id: str, path: str, content: str):
        name = path.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        if name in ("", ".", ".."):
            raise ValueError("A filename is required")
        data = content.encode("utf-8")
        guest_check(container_id, f"[IO.File]::WriteAllBytes({resolved(path)}, (Read-ZooInput))", data)
        return {"success": True, "path": path, "size": len(data)}
