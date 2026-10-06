from server import guest, windows, windows_tools


class Agent:
    def __init__(self, services=("exec", "windows")):
        self.services = services
        self.calls = []

    def has(self, service):
        return service in self.services

    def exec_run(self, argv, stdin=b"", timeout=600):
        self.calls.append((argv, stdin))
        return 0, b"True\r\n", b""

    def call(self, op, args, payload=b"", timeout=600):
        self.calls.append((op, args))
        return {"windows": [{"id": "42", "title": "Untitled - Notepad", "app": "notepad", "pid": 7}]}, b""


def routed(monkeypatch, agent):
    ssh = []
    monkeypatch.setattr(windows.hub, "for_runtime", lambda rid: agent)
    monkeypatch.setattr(windows, "guest_client", lambda rid: None)
    monkeypatch.setattr(
        windows, "execute", lambda client, command, stdin, timeout: ssh.append(command) or (0, b"", b"")
    )
    return ssh


def test_powershell_goes_through_the_agent_but_admin_changes_stay_on_ssh(monkeypatch):
    agent = Agent()
    ssh = routed(monkeypatch, agent)
    rid = "windows:srv:zoo-sb"
    windows.guest(rid, "Get-Date", b"data")
    argv, stdin = agent.calls[0]
    assert argv == windows.POWERSHELL_ARGV and stdin.endswith(b"data") and b"Get-Date" in stdin
    windows.apply_apps(rid, {"notepad.exe": "deny"})
    assert len(agent.calls) == 1 and ssh == [windows.POWERSHELL]


def test_tar_runs_without_a_shell(monkeypatch):
    agent = Agent()
    routed(monkeypatch, agent)
    windows.import_home("windows:srv:zoo-sb", b"tar")
    assert agent.calls[-1] == (["tar.exe", "-xf", "-", "-C", "C:\\Users"], b"tar")
    ssh = routed(monkeypatch, None)
    windows.export_dir("windows:srv:zoo-sb", "C:/Users/zoo/My Docs")
    assert ssh == ['tar.exe -cf - -C C:\\Users\\zoo "My Docs"']


def test_window_tools_use_the_window_service(monkeypatch):
    agent = Agent()
    routed(monkeypatch, agent)
    rid = "windows:srv:zoo-sb"
    assert windows_tools.WinWindows.windows_list(rid) == [{"id": "42", "title": "Untitled - Notepad", "app": "notepad"}]
    windows_tools.WinWindows.window_minimize(rid, "42")
    assert agent.calls[-1] == ("window", {"action": "show", "id": "42", "cmd": 6})
    assert windows_tools.WinApps.close_app(rid, "Notepad.exe") is True
    assert ("window", {"action": "close", "id": "42", "cmd": 0}) in agent.calls


def test_window_tools_fall_back_to_the_desktop_agent(monkeypatch):
    scripts = []
    routed(monkeypatch, Agent(services=("exec",)))
    monkeypatch.setattr(windows, "agent", lambda rid, script, timeout=30: scripts.append(script) or "[]")
    windows_tools.WinWindows.window_close("windows:srv:zoo-sb", "42")
    assert windows_tools.WinWindows.windows_list("windows:srv:zoo-sb") == []
    assert scripts[0] == "[ZooWin]::Close('42')"


def test_network_policy_keeps_the_guest_reaching_the_api(monkeypatch):
    monkeypatch.setattr(guest, "REMOTE_URL", "ws://10.0.0.5:8000/guest/connect")
    assert windows.guest_rule()[1] == "if ($ips) { Rule zoo-guest Allow $ips TCP 8000 }"
    monkeypatch.setattr(guest, "REMOTE_URL", "")
    assert windows.guest_rule() == []
