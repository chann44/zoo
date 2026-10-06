import json

import pytest

from server import a11y, macos_tools, windows_tools

TREE = {
    "app": "Firefox",
    "window": "Zoo",
    "truncated": False,
    "nodes": [
        {"d": 0, "role": "frame", "name": "Zoo", "box": [0, 0, 1280, 720]},
        {"d": 1, "role": "panel", "name": ""},
        {"d": 2, "role": "push button", "name": "Back", "states": ["focused"], "box": [4, 40, 32, 32]},
        {"d": 2, "role": "entry", "name": "Address", "value": "zoo.dev", "states": ["editable"]},
        {"d": 1, "role": "AXStaticText", "name": "Hello\nworld"},
        {"d": 1, "role": "CheckBox", "name": "", "states": ["checked"]},
    ],
}


def test_render_drops_unnamed_containers_and_lifts_their_children():
    out = a11y.render(TREE)
    assert out["tree"].splitlines() == [
        'frame "Zoo" @(0,0 1280x720)',
        '  push button "Back" [focused] @(4,40 32x32)',
        '  entry "Address" = "zoo.dev" [editable]',
        '  static text "Hello world"',
        "  check box [checked]",
    ]
    assert out["elements"] == 5 and out["app"] == "Firefox" and not out["truncated"]


def test_long_values_are_cut():
    out = a11y.render({"nodes": [{"d": 0, "role": "text", "name": "", "value": "x" * 500}]})
    assert len(out["tree"]) < 220 and out["tree"].endswith('…"')


def test_max_nodes_is_bounded():
    with pytest.raises(ValueError):
        a11y.check(0)
    with pytest.raises(ValueError):
        a11y.check(a11y.MAX_NODES + 1)


class Guest:
    def __init__(self, services):
        self.services = services
        self.calls = []

    def has(self, service):
        return service in self.services

    def call(self, op, args, payload=b"", timeout=600):
        self.calls.append((op, args))
        return TREE, b""


def test_linux_reads_the_guest(monkeypatch):
    guest = Guest({"a11y"})
    monkeypatch.setattr(a11y.hub, "for_runtime", lambda rid: guest)
    out = a11y.accessibility_tree("c1", app="fire", max_nodes=10)
    assert guest.calls == [("a11y", {"app": "fire", "title": "", "max_nodes": 10})]
    assert out["tree"].startswith('frame "Zoo"')


def test_linux_without_the_service_says_why(monkeypatch):
    monkeypatch.setattr(a11y.hub, "for_runtime", lambda rid: Guest({"exec"}))
    with pytest.raises(RuntimeError, match="upgrade"):
        a11y.accessibility_tree("c1")


def test_vms_prefer_the_native_guest(monkeypatch):
    guest = Guest({"a11y"})
    monkeypatch.setattr(a11y.hub, "for_runtime", lambda rid: guest)
    monkeypatch.setattr(macos_tools, "guest_check", lambda *a, **k: pytest.fail("used the script"))
    monkeypatch.setattr(windows_tools, "desktop_json", lambda *a, **k: pytest.fail("used the script"))
    assert macos_tools.accessibility_tree("mac-1")["elements"] == 5
    assert windows_tools.accessibility_tree("win-1")["elements"] == 5
    assert [op for op, _ in guest.calls] == ["a11y", "a11y"]


def test_macos_runs_jxa_over_ssh(monkeypatch):
    seen = {}

    def guest_check(rid, script, stdin=None, timeout=60, root=False, ssh=False):
        seen.update(script=script, ssh=ssh)
        return json.dumps(TREE)

    monkeypatch.setattr(macos_tools, "guest_check", guest_check)
    out = macos_tools.accessibility_tree("mac-1", title="Zoo")
    assert seen["ssh"] and "osascript -l JavaScript" in seen["script"]
    assert '"title": "Zoo"' in seen["script"]
    assert out["elements"] == 5


def test_windows_runs_uia_in_the_desktop(monkeypatch):
    seen = {}

    def desktop_json(rid, script, timeout=30):
        seen["script"] = script
        return TREE

    monkeypatch.setattr(windows_tools, "desktop_json", desktop_json)
    out = windows_tools.accessibility_tree("win-1", app="O'Brien")
    assert "UIAutomationClient" in seen["script"] and "O''Brien" in seen["script"]
    assert out["window"] == "Zoo"
