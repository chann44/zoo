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
2. **Screen tools and the VNC tunnel.**
   - Diff and `wait_until_stable`.
   - noVNC through `tunnel`, and stop publishing 6080.
3. **macOS guest.** The TCC spike comes first.
4. **Windows guest.** Then delete `agent.ps1`.
5. **Warm pool.** Pool table, claim path, settings and dashboard panel.
6. **Accessibility tree** on all three OSes.

Later: vsock transport when Linux moves to Firecracker, swapped in under `hub.py` with no tool changes.

## Risks and open questions

- **Several API replicas.** A guest connects to one API process. If there's more than one replica, tool calls need routing, either sticky by sandbox or a hop through the owner. One replica works for now.
- **Network policy.** Sandboxes must always be allowed to reach the API's guest endpoint. `apply_network` needs that rule pinned, and it must not be something users can remove.
- **Reverse dial vs inbound.** Remote servers' sandboxes must be able to reach the control plane URL. A deployment where the API sits on a private network that sandboxes can't reach would need inbound mode, meaning the API dials the guest on a published port. Keep the transport interface open for that.
- **Sandboxes booted before the guest.** They keep the legacy path until they're recreated. There's no in-place upgrade into a running container.
- **Release.** Release CI builds `zoo-guest` for linux/amd64, linux/arm64, darwin/arm64 and windows/amd64. The Windows binary should be signed to avoid Defender and SmartScreen friction.
