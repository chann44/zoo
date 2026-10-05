"""Which sandboxes each kind of host can run.

A server is a host machine. Its platform is the host's OS, and its capabilities are the sandbox OSes it can run:
every host runs sandboxes of its own OS, and Macs and Windows machines with Docker also run Linux sandboxes.
The scheduler only places a sandbox on a server whose capabilities include the sandbox's OS.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Platform:
    id: str
    name: str  # the sandbox OS, as the dashboard shows it
    host: str  # what to add to run it, as in "Add a Mac"
    kinds: tuple[str, ...]  # the sandbox kinds of this OS
    runs: tuple[str, ...]  # the sandbox OSes a host of this platform can run
    requirements: str


PLATFORMS = {
    "linux": Platform(
        "linux",
        "Linux",
        "Linux server",
        ("desktop", "browser", "code"),
        ("linux",),
        "Ubuntu or Debian, amd64 or arm64; KVM for VM isolation (otherwise runc)",
    ),
    "macos": Platform(
        "macos",
        "macOS",
        "Mac",
        ("macos",),
        ("macos", "linux"),
        "Apple Silicon, macOS 13 or later, Remote Login on; Docker to also run Linux sandboxes",
    ),
    "windows": Platform(
        "windows",
        "Windows",
        "Windows machine",
        ("windows",),
        ("windows", "linux"),
        "Windows 10/11 Pro, Enterprise or Education, or Server, with Hyper-V; Docker to also run Linux sandboxes",
    ),
}

INSTALL_URL = os.environ.get("ZOO_INSTALL_URL", "https://github.com/chann44/zoo/releases/latest/download")


def os_of(kind: str) -> str:
    return next((p.id for p in PLATFORMS.values() if kind in p.kinds), "linux")


def parse(capabilities: str) -> set[str]:
    return {c for c in capabilities.split(",") if c}


def capabilities_of(platform: str, docker: bool) -> str:
    """The sandbox OSes a host can run, given its platform and whether it has a usable Docker."""
    return ",".join(o for o in PLATFORMS[platform].runs if o != "linux" or platform == "linux" or docker)


def install_command(platform: str, public_key: str, api_url: str) -> str:
    """The one line to paste on a new host. It checks the host, installs what it needs and authorizes our key."""
    if platform == "windows":
        return (
            f'powershell -ExecutionPolicy Bypass -c "& ([scriptblock]::Create((irm {INSTALL_URL}/install-node.ps1)))'
            f" -Key '{public_key}' -ControlPlane '{api_url}'\""
        )
    return (
        f"curl -fsSL {INSTALL_URL}/install.sh | sudo bash -s -- --node --key '{public_key}' --control-plane '{api_url}'"
    )
