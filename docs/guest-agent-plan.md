# zoo-guest: plan

Goal: one agent inside every sandbox replaces `docker exec`, in-guest SSH, `agent.ps1`, and published VNC ports. Tool calls drop from hundreds of ms to under 30 ms at p50.

## Decisions (recommended)

| Question | Pick | Why |
|---|---|---|
| Language | **Go** | Static cross-compiles for linux/darwin/windows from one toolchain. Ready libraries: `creack/pty`, ConPTY, `jezek/xgb` (X11 capture and XTest input, no cgo), `godbus` (AT-SPI), `go-ole` (UI Automation), `mdlayher/vsock`. Only the macOS build needs cgo, for CoreGraphics and AX. |
| Protocol | **Framed messages over one multiplexed connection** (not gRPC) | Each frame is a small JSON header (`id`, `stream`, `op`, `ok/err`) plus an optional binary payload, so screenshots and tar data aren't base64-encoded. The same framing runs over WebSocket, TCP or vsock. gRPC would mean protoc in two languages and HTTP/2 over a reverse tunnel, which is awkward. |
| Direction | **The guest dials the API** (reverse WebSocket) on all three OSes | One code path. No published ports on servers (6080 goes away). Works through NAT. Kata under Docker doesn't expose vsock to the host anyway, so vsock comes later as a Linux transport swap. |
| Auth | Per-sandbox guest token | The guest gets the token at boot (env on Linux, a file in the VM on macOS and Windows). The API stores only its hash and checks it on `/guest/connect`. |
| Compatibility | Version handshake plus legacy fallback | The guest's `hello` frame carries `{version, os, services[]}`. If there's no guest, or it lacks a service, the API uses today's docker exec or SSH path. Old sandboxes keep working untouched. |

## Services (v1)

- `exec`: one-shot run, and a streaming PTY with resize and signals.
- `files`: read, write, list, stat, and tar in and out (used by backup, restore and move).
- `input`: mouse and keyboard.
- `screen`: screenshot in png/webp/jpeg with `scale` and `quality`, changed-region diff against the last frame per session, and `wait_until_stable(timeout, quiet_ms, threshold)`. The guest polls locally at about 10 fps, so there are no network round-trips while it waits.
- `windows` and `apps`: list, focus, move, close, launch.
- `tunnel`: a raw byte stream to a local port (the guest's RFB at `127.0.0.1:5900`).
- `metrics`: cpu, mem, disk, net, pushed every N seconds.
- `a11y` (phase 6): an accessibility tree with its visible text.

## API side

New package `server/guest/`:
- `protocol.py`: frame encode and decode, plus a version constant.
- `hub.py`: the `/guest/connect` WebSocket. It authenticates the token and keeps a registry of `sandbox_id → connection`. It also tracks the services each guest offers and handles reconnect and backoff. Connections are keyed by sandbox id; tools get it through a `runtime_id → sandbox_id` map.
- `client.py`: `GuestClient(sandbox_id)` with typed methods (`exec`, `pty`, `read_file`, `screenshot`, …) and `has(service)`.

Adapters:
- `server/tools.py`, `macos_tools.py`, `windows_tools.py` and `vnc_tools.py` keep their tool names and signatures.
- Each method body becomes "guest if `has(service)` else legacy". The legacy code stays until no running sandbox predates the guest, then gets deleted.
- `sandbox_api.proxy` (noVNC) opens a `tunnel` stream instead of dialing `host:6080`.

The guest token is added in the next free `db/migrations/` slot, as a `guest_token_hash` column on sandboxes.

## Per OS

**Linux (Kata/runc images).**
- Add `[program:zoo-guest]` to `supervisord.conf`, running as root so it can serve both root and zoo-user exec.
- Bake the binary into `Dockerfile` and `Dockerfile.code`.
- Capture and input use X11 directly through xgb, which replaces the xdotool and scrot forks. That's most of the speedup.
- `run_container` passes `ZOO_GUEST_URL` and `ZOO_GUEST_TOKEN`, and no longer publishes 6080 once the guest is confirmed.

**macOS (zoovm).**
- A launchd **LaunchAgent** in the guest user's GUI session, installed in the base image.
- Capture uses ScreenCaptureKit, input uses CGEvent, and a11y uses the AX API.
- **Risk:** TCC (Screen Recording and Accessibility) must be pre-granted in the image's TCC.db. This has to be verified on a real VM first, because it decides whether this OS is feasible at all.
- Replaces the `server.macos.run` SSH hops in `macos_tools.py`.

**Windows.**
- A scheduled task "at logon, run only when the user is logged on" launches `zoo-guest.exe` in the interactive session.
- Capture uses DXGI duplication with a GDI fallback, input uses SendInput, and a11y uses UI Automation.
- Replaces `windows/agent.ps1` and the SSH path in `windows_tools.py`.

## Speed work outside the guest

- **Secrets cache.**
  - `secret_values()` decrypts every secret on every tool call. Cache it per sandbox in memory.
  - Clear the cache on any secret or vault write for that sandbox, and on stop or delete.
- **Async execution rows.**
  - `run_tool` makes 3 synchronous DB writes per call. Move them to an asyncio queue drained by one writer.
  - Insert the row with its final status in one write.
- **Pre-pull images.**
  - After a release (API version changes at startup) and when a server is added, run a background `ensure_image` for every kind's image on every server.
  - Show this per server in the UI as "images: ready / pulling".
- **Warm pool** (needs the guest).
  - Pooled sandboxes boot without a user, a home volume or secrets. A create claims one, then:
    - restores the home via `files` tar-in;
    - writes secrets through the guest into `/run/zoo/env`, which exec sources, so they're no longer in the container env;
    - applies the network and app policy (already done after boot today);
    - assigns the owner.
  - Docker volumes can't be mounted after boot, so the pool serves **new** sandboxes only. Starting a stopped sandbox stays a cold boot.
  - Settings: pool size per (kind, server), default 0. macOS is limited to 2 VMs per host by Apple's license, so a pooled Mac VM uses half that host's capacity.
  - Dashboard: a pool panel on the Servers page showing idle, booting and claimed per kind.
- **Metrics.** Guest `metrics` feeds the existing monitoring, which fills the macOS and Windows gaps.

## Phases

0. **Baseline and quick wins, no binary.**
   - `scripts/bench_tools.py` measures p50/p95 for exec `true`, screenshot, click and read_file on each OS. This is how "<30 ms" gets proven.
   - Also in this phase: the secrets cache, async execution rows, pre-pull, and webp/jpeg plus scale on screenshots (converted API-side with Pillow for now).
1. **Linux guest.** Done (`guest/`, `server/guest.py`). Where it differs from the plan above:
   - The token is an HMAC of the sandbox id under the secrets key, so there's no migration and guests reconnect after an API restart. Rotating `ZOO_SECRETS_KEY` drops running sandboxes to the fallback until they restart.
   - The guest runs as `zoo`, not root, so commands and file writes get the sandbox user's permissions. Root commands (network and app policy) stay on docker exec.
   - One module, `server/guest.py`, holds the frames, hub, client and terminal streams.
   - Every Linux `exec_run` goes through the guest, so the window, app and file tools speed up without being rewritten.
   - Mouse and keyboard use XTest. The keyboard takes xdotool key names from X11's full keysym table, and maps characters missing from the layout onto spare keycodes. Screenshots read X directly and use a fast PNG writer (Sub filter, klauspost deflate).
   - The terminal is `/sandboxes/{id}/terminal` (ticketed, needs `shell.exec`) plus a Terminal tab in the dashboard. Its output isn't redacted, the same as the desktop viewer.
   - Metrics come from the sandbox's cgroup. `/monitoring` uses them when docker stats can't reach the container, such as on remote servers.
   - Benchmark, desktop sandbox on runc, p50 with the guest vs docker exec:

     | Tool | Guest | docker exec |
     |---|---|---|
     | exec | 5.6 ms | 55 ms |
     | click | 6.0 ms | 151 ms |
     | press_key | 5.6 ms | 63 ms |
     | read_file | 5.0 ms | 49 ms |
     | screenshot (png) | 22 ms | 632 ms |
     | screenshot (webp at half scale) | 25 ms | 639 ms |
2. **Screen tools and the VNC tunnel.** Done. Where it differs from the plan above:
   - `screen_diff` and `wait_until_stable` are tools of their own, behind the guest's `diff` service. Frames are compared in 16 px tiles: `changed` is the fraction of tiles that differ, and `box` is their bounding box in screen pixels. The image covers only that box. A session's first call returns the whole screen.
   - Sandboxes without the `diff` service (older Linux images, macOS and Windows) get the same tools computed API-side from full screenshots with Pillow.
   - The guest's `tunnel` service only dials ports on `127.0.0.1`. `proxy` logs in to x11vnc through it, the same way it did over websockify.
   - 6080 stays unpublished when the image carries `LABEL zoo.guest.tunnel=1` and the sandbox gets a guest token. Those sandboxes record `access_url` as `guest://vnc`. Boot waits for a tunnel to 5900 to open, not for noVNC's HTTP. Older images keep the published port.
3. **macOS guest.** Built; not yet run on a real VM. Where it differs from the plan above:
   - No TCC spike was needed. The host already drives the VM's screen, mouse and keyboard over Virtualization.framework's VNC server, so the guest needs no Screen Recording or input permission. It's the same Go binary (no cgo) and offers `exec`, `pty` and `files` only.
   - Window and app tools run `osascript` against System Events, so they stay on SSH, where the Accessibility grant lives (macos/README.md, step 4). Root commands (network and app policy) stay on SSH too. Everything else in `macos.guest()` goes through the guest when it's connected, including `execute_command`, the file tools, and home backup and restore. The Terminal tab works for macOS sandboxes.
   - The base image doesn't change. On every boot the API copies `zoo-guest` over SSH (only when its hash differs), writes `~/.zoo/guest.env`, and starts a LaunchAgent (`com.zoo.guest`) in the auto-logged-in session. Clones of an existing base VM pick the guest up with no manual step. The guest reads that file again on each reconnect.
   - The VM dials `ZOO_GUEST_REMOTE_URL`, because it can't resolve compose names. With the API running on the Mac itself, that's the host's address on the VM network, for example `ws://192.168.64.1:8000/guest/connect`. The pf policy always lets the guest reach that host and port.
   - The darwin binary comes from `make guest-darwin` (`guest/dist/`) and ships in the API image. Without it, or without the URL, macOS tools stay on SSH.
4. **Windows guest.** Built, and the only way into a Windows VM: it replaced OpenSSH in the guest and `agent.ps1`. Where it differs from the plan above:
   - The host keeps driving the screen, mouse and keyboard over TightVNC, so the guest offers `exec`, `pty` (ConPTY), `files`, `windows`, `a11y`, `metrics` (the whole VM's CPU, memory, network, disk and processes, which is also the heartbeat hang recovery watches) and `update`.
   - It runs in the desktop session as a scheduled task (`zoo-guest`, at logon, highest run level), so everything goes through it, admin changes included (network and app policy, the VNC password, the secrets file).
   - `setup.ps1` builds it into the base VM. Its identity (`C:\ProgramData\zoo\guest.env`) comes from the host through Hyper-V's Guest Service Interface (`zoovm push`, `Copy-VMFile`) at every boot, and `zoovm seal` removes it from a template's disk, so clones never connect as the base VM.
   - Updates: the host copies the new build in as `zoo-guest.exe.new`, and the `update` op renames the running exe aside, starts the new one detached and exits. Windows lets a running exe be renamed, not overwritten.
   - `ZOO_GUEST_REMOTE_URL` is required for Windows sandboxes. A tool call with no guest connected fails with a message saying so, rather than falling back.
   - tar for backup, restore and move runs as an argv with no shell (`guest_raw`). The binary is built with `-H windowsgui`, so it opens no console window, and the commands it runs get `CREATE_NO_WINDOW`.
   - The firewall policy adds an allow rule for the guest URL's host and port. Windows Firewall lets a block rule win, so a policy that blocks that address cuts the guest off.
   - CI's `windows` job runs the Windows tool layer against a live guest on GitHub's Windows runner (`tests/windows_live`); the nightly job covers Hyper-V on a real host.
5. **Warm pool.** Built for Linux kinds (desktop, browser, code); not yet run against real Docker. Where it differs from the plan above:
   - A pooled container boots under the id its sandbox will have (`pool_sandboxes.id`), so its name, home volume and guest token are already the sandbox's. A create claims one (`ClaimPoolSandbox`, a `DELETE ... RETURNING`, so a claim and a drain can't both win) and takes that id. The boot job sees `pooled` in the config with a live runtime and adopts it (`SandboxApi.adopt`): it writes the secrets, applies profiles and policy, and opens the browser home page. If the pooled container died in between, the job removes it and cold boots on the same volume.
   - No home restore is needed: a new sandbox's home starts empty, and the pooled container already mounts the volume that stays with the sandbox. So stop and start work as usual afterwards.
   - Secrets go to `/run/zoo/env.json` (mode 0600, owned by `zoo`) through `put_archive`. The guest merges it into every `exec` and `pty` environment, so it's read fresh on each command. Apps started from the desktop itself (menus, its own terminal) don't see them, and neither does the `docker exec` fallback, so pooling needs the guest: pools only fill when a guest URL is configured.
   - The VNC password is made when the pooled container boots and moves into the sandbox config on claim.
   - Settings are `pool_settings` rows keyed `kind:server` (`local` for the API's own Docker), size 0 to 10, default 0. Admins size the local pool; owners size their own Linux-capable servers. `GET/PUT /pool`; the Servers page has a "Warm pool" panel with size, idle, booting, claimed (since the API started) and the last boot error.
   - `Pool.fill` runs every 10 s and after each claim. It removes containers left mid-boot by a restart, dead or idle ones over the size, and ones on an outdated image (so a release replaces the pool). A failed boot keeps its row for 5 minutes, which holds that pool back so a broken image or host isn't booted in a loop. Deleting a server drains its pool first.
   - macOS and Windows VMs aren't pooled yet: their start path clones and configures per sandbox over SSH, and a pooled Mac VM would take half its host's two-VM license.
6. **Accessibility tree.** Built on all three OSes, native in the guest; not yet run on a real sandbox or VM. Where it differs from the plan above:
   - One tool, `accessibility_tree(app, title, max_nodes)`, in the `observe` category behind `screen.read`. It reads one window: the active one, or the first whose app and title contain the filters. The guest's `a11y` service returns a pre-order node list (`depth, role, name, value, states, box`), the same on every OS. `server/a11y.py` renders it as an indented outline, one line per element: `role "name" = "value" [states] @(x,y wxh)`. Unnamed generic containers are dropped and their children moved up. Values are cut at 200 characters, and password fields are never read. `max_nodes` defaults to 300, up to 2000.
   - The guest stays cgo-free on every OS.
   - **Linux:** AT-SPI with `godbus`. Each element's six calls go out together, and sibling subtrees are read in parallel (up to 64 elements in flight), so the app answers back to back instead of waiting a round trip per call. The image now runs one session bus (`/tmp/zoo-session-bus`) for xfce, the guest and everything the guest starts, and installs `at-spi2-core`. The guest turns on `org.a11y.Status.IsEnabled` and sets `GNOME_ACCESSIBILITY=1`, so GTK apps and Firefox export their trees. Older images don't offer `a11y`, and the tool says to upgrade.
   - **Windows:** UI Automation through its raw COM vtables (no go-ole). One `ElementFromHandleBuildCache` with a subtree cache request brings the whole control view with 16 properties into the guest in a single call into the app. The walk then reads only the local cache. The window comes from `GetForegroundWindow` or the user32 window list.
   - **macOS:** the AX API through `purego` (`dlopen` of CoreFoundation and ApplicationServices). One `AXUIElementCopyMultipleAttributeValues` per element reads 13 attributes, children included. The messaging timeout is 2 s, so a hung app can't stall the walk. Windows are picked from the focused app, or from `CGWindowListCopyWindowInfo` for the filters.
   - **macOS permission:** AX needs the Accessibility permission for the responsible process. The LaunchAgent starts the guest as a child of `/bin/zsh` (`-c "...; exit $?"`, so zsh doesn't exec it), and `/bin/zsh` gets the grant in macos/README.md step 4. zsh is Apple-signed, so the grant survives guest updates; a grant on the ad-hoc signed guest would break with every build. The plist is now reloaded with bootout and bootstrap, so this change reaches existing VMs. The guest offers `a11y` only when `AXIsProcessTrusted()` is true.
   - **Fallbacks:** when the guest doesn't offer `a11y` (an older guest, or a Mac without the grant), macOS and Windows fall back to scripts: JXA over System Events through SSH, and PowerShell UI Automation in the desktop session. Both take seconds.
   - The tool returns `{app, window, tree, elements, truncated}`. Secrets in the tree are redacted like any tool result.

Later: vsock transport when Linux moves to Firecracker, swapped in under `hub.py` with no tool changes.

## Risks and open questions

- **Several API replicas.** A guest connects to one API process. If there's more than one replica, tool calls need routing, either sticky by sandbox or a hop through the owner. One replica works for now.
- **Network policy.** Sandboxes must always be allowed to reach the API's guest endpoint. `apply_network` needs that rule pinned, and it must not be something users can remove.
- **Reverse dial vs inbound.** Remote servers' sandboxes must be able to reach the control plane URL. A deployment where the API sits on a private network that sandboxes can't reach would need inbound mode, meaning the API dials the guest on a published port. Keep the transport interface open for that.
- **Sandboxes booted before the guest.** They keep the legacy path until they're recreated. There's no in-place upgrade into a running container.
- **Release.** Release CI builds `zoo-guest` for linux/amd64, linux/arm64, darwin/arm64 and windows/amd64. The Windows binary should be signed to avoid Defender and SmartScreen friction.
