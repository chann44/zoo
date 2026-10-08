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

macOS and Windows sandboxes have their own apps (Safari, Chrome, Edge, Firefox, VS Code on macOS; Chrome, Edge, Firefox, VS Code on Windows; `GET /profile-apps?platform=`), and a profile only loads into a sandbox of the OS it came from.

Save and load profiles in the sandbox's **Profiles** tab, or choose one in the create dialog to have it loaded before the desktop starts. Profiles are stored encrypted as tar files in `PROFILE_DIR`.

Profiles are versioned. Saving under a name you've used for that app (or with **Save new version**, `profile_id` in the API) adds a version; the last 10 are kept. Loading takes the latest unless you pick one (`POST /sandboxes/{id}/profiles/{profile_id}?version=N`); `GET /profiles/{id}/versions` lists them and `DELETE /profiles/{id}/versions/{n}` removes one. A new sandbox gets the latest version.

Loading into a running sandbox is refused (409) while the app is running there, because the app holds its profile open and would overwrite or corrupt it: quit the app, then load. If the sandbox can't be asked, the load is refused too (503).
