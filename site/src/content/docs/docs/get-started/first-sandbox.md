---
title: Your first sandbox
description: Create a sandbox in the dashboard, drive it from the browser, and take an API key for your agents.
---

Open the dashboard URL the installer printed — usually `http://<server ip>:3000` — and
sign up. The first account works right away; admin abilities (`/admin/*`, Domains) are
limited to the emails in `ADMIN_EMAILS`.

## Create a sandbox

Click **Create sandbox**, give it a name, and pick a type:

| Type | Display | Tools available | Notes |
| --- | --- | --- | --- |
| `desktop` | XFCE, 1280x720 | all | Firefox, terminal, file manager |
| `browser` | XFCE, 1280x720 | observe, mouse, keyboard, windows, browser | Firefox opens on start. No shell. |
| `code` | none | shell, files, `fetch_url` | Claude Code is preinstalled |
| `macos` | macOS, 1280x800 | all | Runs on a Mac server — see [macOS sandboxes](/docs/guides/macos/) |
| `windows` | Windows, 1280x800 | all | Runs on a Windows server — see [Windows sandboxes](/docs/guides/windows/) |

Whatever the type, every sandbox:

- runs in its own microVM with its own kernel (or a plain container on a `runc` host);
- runs its processes as the unprivileged user `zoo` (uid 1000);
- keeps `/home/zoo` on its own Docker volume (`zoo-home-<id>`), so files survive stop and
  start;
- is limited to 2 GB memory, 2 CPUs and 1024 processes, with `no-new-privileges`;
- is reached only through the API — desktop ports bind to `127.0.0.1`, or to the compose
  network.

A sandbox with enough free memory starts in about a second from the [warm
pool](/docs/concepts/architecture/#the-warm-pool) when an admin has enabled it under
**Servers → Warm pool**.

## Drive it

- **Live view** — the dashboard opens the sandbox's VNC in the browser. Watch, or take
  over the mouse and keyboard.
- **Terminal** — a shell in the sandbox (PowerShell on Windows).
- **Activity** — every tool call with its input, output and status.
- **Monitoring** — CPU, memory, network and disk for the whole VM.
- **Snapshots** — copy the home disk and restore it later.
- **Profiles** — save and load app profiles (logins, cookies, settings).

Stopping removes the container and keeps the volume; starting creates a fresh container on
the current image and mounts the same volume; deleting removes both.

## Take an API key

Under **Profile → API keys**, create a key. It is shown once — store it. Agents use it as
`Authorization: Bearer zoo_...` on every call. See
[Connect Claude Code or Claude Desktop](/docs/get-started/mcp/) to plug your agent in.

## Housekeeping

A container reported as running in the database but gone from Docker is marked stopped
within 15 seconds. Under the sandbox's **Overview** tab, **Restart on new image** re-creates
a stopped-or-running sandbox on the current release's image and keeps the home directory.
