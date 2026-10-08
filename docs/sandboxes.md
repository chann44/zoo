# Sandboxes

## Sandbox types

| Type | Display | Tools available | Notes |
| --- | --- | --- | --- |
| `desktop` | XFCE, 1280x720 | all | Firefox, terminal, file manager |
| `browser` | XFCE, 1280x720 | observe, mouse, keyboard, windows, browser | Firefox opens on start (`ZOO_BROWSER_HOME`). No shell. |
| `code` | none | shell, files, `fetch_url` | Claude Code is preinstalled |
| `macos` | macOS, 1280x800 | all | Runs on a Mac server. See [macOS sandboxes](servers.md#macos-sandboxes). |
| `windows` | Windows, 1280x800 | all | Runs on a Windows server. See [Windows sandboxes](servers.md#windows-sandboxes). |

Every sandbox:

- runs in its own microVM with its own kernel (`ZOO_RUNTIME`, default `kata`);
- runs its processes as the unprivileged user `zoo` (uid 1000);
- keeps `/home/zoo` on its own Docker volume (`zoo-home-<id>`), so files survive stop and start;
- is limited to 2 GB memory, 2 CPUs and 1024 processes, with `no-new-privileges`;
- is reached only through the API. Desktop ports are bound to `127.0.0.1`, or to the compose network.

Stop removes the container and keeps the volume. Start creates a fresh container on the current image and mounts the same volume. Delete removes both.

A container reported as running in the DB but gone from Docker is marked stopped within 15 seconds.

## App profiles

Save an app's profile directory (logins, cookies, settings) from a running sandbox and load it into others.

| App | Directory |
| --- | --- |
| `firefox` | `~/.mozilla` |
| `chromium` | `~/.config/chromium` |
| `chrome` | `~/.config/google-chrome` |
| `vscode` | `~/.config/Code` |

Save and load profiles in the sandbox's **Profiles** tab, or choose one in the create dialog to have it loaded before the desktop starts. Profiles are stored as tar files in `PROFILE_DIR`. Close the app before loading a profile into a running sandbox.
