from server import guest, macos


class Agent:
    def __init__(self):
        self.calls = []

    def has(self, service):
        return service == "exec"

    def exec_run(self, argv, stdin=b"", timeout=600):
        self.calls.append((argv, stdin))
        return 0, b"out", b""


def test_guest_runs_through_the_agent_but_root_and_osascript_stay_on_ssh(monkeypatch):
    agent, ssh = Agent(), []
    monkeypatch.setattr(macos.hub, "for_runtime", lambda rid: agent)
    monkeypatch.setattr(macos, "guest_client", lambda rid: None)
    monkeypatch.setattr(macos, "execute", lambda client, command, stdin, timeout: ssh.append(command) or (0, b"", b""))
    rid = "macos:srv:zoo-sb"
    assert macos.guest(rid, "cat > f", stdin=b"data") == (0, b"out", b"")
    assert agent.calls == [(["/bin/sh", "-c", f"cd {macos.HOME} && cat > f"], b"data")]
    macos.guest(rid, "pfctl -e", root=True)
    macos.guest(rid, "osascript -e x", ssh=True)
    assert len(agent.calls) == 1 and len(ssh) == 2 and ssh[0].startswith("sudo -n")


def test_network_policy_keeps_the_guest_reaching_the_api(monkeypatch):
    monkeypatch.setattr(guest, "REMOTE_URL", "wss://zoo.example/guest")
    assert macos.guest_rule() == ["pass out quick proto tcp to zoo.example port 443 keep state"]
    monkeypatch.setattr(guest, "REMOTE_URL", "")
    assert macos.guest_rule() == []
