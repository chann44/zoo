# Logs

Things to check on real hardware before the final run.

## Phase 3: macOS guest (not yet run on a real VM)

Built and unit-tested on 2026-10-06. Never booted in a VM, because the base VM wasn't set up.

**Setup**
1. Finish the base VM: Install macOS, Setup Assistant (user `admin`), Run setup, and the Accessibility grant for `/usr/libexec/sshd-keygen-wrapper` (macos/README.md).
2. Build the guest with `make guest-darwin`, or rebuild the API image.
3. Set `ZOO_GUEST_REMOTE_URL` to an address the VM can reach. With the API on this Mac, use `ws://192.168.64.1:8000/guest/connect`. The API must listen on 0.0.0.0.

**Check**
- [ ] Booting a macOS sandbox installs `~/.zoo/bin/zoo-guest`, `~/.zoo/guest.env` and `~/Library/LaunchAgents/com.zoo.guest.plist` in the VM.
- [ ] `sudo launchctl bootstrap gui/<uid>` over SSH starts the agent in the logged-in session. This is the main unknown. If it fails, see `~/.zoo/guest.log` and try `launchctl asuser`.
- [ ] The API logs `guest connected` with services `exec, files, pty`.
- [ ] `execute_command` and the file tools (read, write, list, stat) work through the guest, faster than over SSH. Measure with `scripts/bench_tools.py`.
- [ ] `write_file` and home restore pass input through to the command correctly.
- [ ] The Terminal tab opens a shell in the VM.
- [ ] Window and app tools still work, since they stay on SSH with `osascript`.
- [ ] Stop the sandbox, then start it: the guest reconnects. It isn't copied again when the binary is unchanged.
- [ ] A network policy with `deny` by default still lets the guest reach the API.
- [ ] Commands run by the guest don't see `ZOO_GUEST_TOKEN` (`env | grep ZOO_GUEST` is empty).
- [ ] Clones of a base VM made before the guest existed still get it installed at boot.
- [ ] Record the benchmark numbers in `docs/guest-agent-plan.md`, Phase 3.

## Phase 4: Windows guest (not yet run on a real VM)

Built and unit-tested on 2026-10-06. The Windows binary was cross-compiled but never run, and the ConPTY and user32 code has only been type-checked.

**Setup**
1. A Windows server with the base VM ready (windows/README.md).
2. Build the guest with `make guest-windows`, or rebuild the API image.
3. Set `ZOO_GUEST_REMOTE_URL` to an address the VM can reach through the Hyper-V NAT, and restart the API.

**Check**
- [ ] A new base VM has zoo-guest in `C:\ProgramData\zoo\bin` and the `zoo-guest` scheduled task (`Get-ScheduledTask zoo-guest`). Booting a sandbox copies in `C:\ProgramData\zoo\guest.env`.
- [ ] The task starts in the desktop session and opens no console window. `C:\ProgramData\zoo\guest.log` shows no errors.
- [ ] The API logs `guest connected` with services `a11y, exec, files, metrics, pty, update, windows`.
- [ ] `execute_command` and the file tools work through the guest. Measure with `scripts/bench_tools.py`.
- [ ] No console window flashes when a command runs.
- [ ] `write_file`, home backup and restore, and move all work. tar runs as an argv: check paths with spaces.
- [ ] `windows_list`, focus, minimize, maximize, restore and close work. The `app` names are process names, such as `notepad` and `msedge`.
- [ ] `open_app` opens Notepad, a Start menu app (Calculator) and an exe path, and reports `window_found`. `close_app` closes them. `open_url` opens the browser.
- [ ] The Terminal tab opens PowerShell over ConPTY. Typing, resizing and closing the tab (it should end the shell) all work.
- [ ] Commands run in the desktop session: GUI apps started by `execute_command` show up on screen, and nothing breaks because of it.
- [ ] Stop and start the sandbox: the guest reconnects, and the binary isn't copied again when unchanged.
- [ ] Ship a new binary: the guest swaps it in through its `update` op and reconnects.
- [ ] A network policy with `deny` by default still lets the guest reach the API.
- [ ] Commands don't see `ZOO_GUEST_TOKEN` (`Get-ChildItem env:ZOO_GUEST*` is empty).
- [ ] Without `ZOO_GUEST_REMOTE_URL`, a Windows sandbox fails to start with a message naming it.
- [ ] Record the benchmark numbers in `docs/guest-agent-plan.md`, Phase 4.

## Phase 5: warm pool (not yet run against real Docker)

Built and unit-tested on 2026-10-06 against the fake runtime only. Linux kinds only.

Setup: rebuild the sandbox images (the guest now reads `/run/zoo/env.json`), set `ZOO_GUEST_URL`, sign in as an admin, and on Servers → Warm pool set Desktop to 1.

- [ ] Within about a minute the row shows idle 1; `docker ps` shows `zoo-sandbox-<id>` with no owner sandbox in the list.
- [ ] Create a desktop sandbox: it is running in about a second, its id is the pooled container's id, and the viewer opens.
- [ ] Claimed goes to 1 and a replacement boots.
- [ ] Attach a vault secret at create: `execute_command echo $NAME` prints it, and the Terminal tab sees it too. `docker inspect` shows it isn't in the container env.
- [ ] `/run/zoo/env.json` is `-rw------- zoo zoo`.
- [ ] A browser kind from the pool opens the home page.
- [ ] Stop and start the claimed sandbox: it cold boots on the same volume and files in the home survive.
- [ ] Set the size back to 0: the idle container and its volume are removed.
- [ ] Restart the API mid-boot: the half-booted container is removed on the next fill.
- [ ] Bump `ZOO_SANDBOX_IMAGE` and restart: the idle pool is replaced on the new image.
- [ ] A remote Linux server's pool fills on that server, and deleting the server removes its pooled containers.
- [ ] Break the image name: the panel shows the boot error, and the pool waits 5 minutes before trying again.
- [ ] Measure create → running with and without the pool and record both in `docs/guest-agent-plan.md`, Phase 5.

## Phase 6: accessibility tree (not yet run on a real sandbox or VM)

Built and unit-tested on 2026-10-06. On this Mac, the darwin guest (built with cgo off) loaded CoreFoundation and ApplicationServices through purego and called `AXIsProcessTrusted`. It wasn't trusted, so no tree was walked. Nothing has walked a real window on any OS yet.

Linux (rebuild `zoo-sandbox`, then create a new desktop sandbox):
- [ ] `supervisorctl status` shows `dbus` running, and xfce and the guest have `DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/zoo-session-bus`.
- [ ] `accessibility_tree` with the terminal focused returns its menu bar and terminal.
- [ ] `accessibility_tree(app="firefox")` after `open_url` shows the page's links and the address bar with its URL as the value. If Firefox shows only its frame, check that `GNOME_ACCESSIBILITY=1` reached it.
- [ ] Click the middle of a button's box: the right button is pressed, so the boxes line up with screen pixels.
- [ ] A filter that matches nothing lists the showing windows in its error.
- [ ] Time 300 and 2000 elements on a big Firefox page. Target: 300 well under 1 s. The output is in pre-order, and truncation drops later subtrees.
- [ ] A password field shows no value.
- [ ] A sandbox on the old image gets the "upgrade" error, not a crash.

macOS:
- [ ] Grant `/bin/zsh` Accessibility in the base VM (README step 4), boot a sandbox, and check that `ps` shows `zoo-guest` with `zsh -c` as its parent. The guest's hello lists `a11y` (`GET /sandboxes/{id}/guest`).
- [ ] Without the grant, `a11y` is absent, and the tool falls back to JXA and still works.
- [ ] With TextEdit frontmost, the tree shows its window, toolbar and text area with the typed text.
- [ ] `app="Safari"` works when Safari isn't frontmost.
- [ ] Time 300 elements. Target: under about 300 ms.
- [ ] Ship a new guest binary: the grant still holds, because it's on zsh.
- [ ] `launchctl print gui/$(id -u)/com.zoo.guest` shows the zsh arguments after an upgrade from the old plist.
- [ ] Compare the boxes with screenshot pixels on the VM's display scale.

Windows:
- [ ] With Notepad focused, the tree shows the window, menu bar and the document with its text.
- [ ] `app="explorer"` returns a File Explorer window.
- [ ] Time 300 elements through the guest. Target: under about 200 ms with the single cache request.
- [ ] Check boxes and tree items report checked and expanded or collapsed. A password box shows no value.
- [ ] Disconnect the guest: the tool fails with "the Windows guest agent isn't connected".
- [ ] Repeated calls don't leak: the guest's memory and handle count stay flat over 100 calls.

## Security phase: host-side policy, secrets, hardening (not yet run on real hosts)

Built and unit-tested on 2026-10-06: Go tests for the proxy, DNS and firewall rules, Python tests for the backends, KMS and profiles. No real nftables, pf, Hyper-V or KMS has seen any of it.

**Linux (Docker host with Kata, and one with runc)**
- [ ] Rebuild the sandbox image (`nftables`, `apparmor`, `curl`, `iproute2`, and the `zoo-policy` program).
- [ ] Setting a policy starts `zoo-egress` (host network, `NET_ADMIN` only); `nft list table inet zoo` on the host shows the sandbox's chains.
- [ ] `scripts/egress_bypass.sh <container> <listener>` with deny-by-default plus `github.com`: every line `ok`, the listener receives nothing, and github.com still works.
- [ ] The same with allow-by-default plus `deny example.com`: example.com fails over HTTP, HTTPS and DNS; everything else works.
- [ ] `docker inspect` of a new sandbox shows no `NET_ADMIN`, `NET_RAW` dropped. On runc: the seccomp profile, and `apparmor=zoo-sandbox` on an AppArmor host (`aa-status` lists it). Firefox, xfce and the terminal still work.
- [ ] `docker stop zoo-egress`: filtered sandboxes lose web access rather than gaining it. Starting it again restores everything.
- [ ] Stop a sandbox: its file in the `zoo-egress` volume is gone.
- [ ] From another machine, port 15128 on the host refuses to proxy.
- [ ] Remote server without `ZOO_GUEST_REMOTE_URL`: a desktop sandbox fails with the "don't publish the desktop port" error. With it set, it boots and nothing listens on 6080 on the host.
- [ ] Apps tab: deny Firefox while it runs; it's killed within a second and won't start again as `zoo`.
- [ ] Timing: the first HTTPS request through the proxy adds under 20 ms.

**macOS host**
- [ ] Add the `pfctl` sudoers line (macos/README.md). Setting a policy starts `~/.zoovm/bin/zoo-guest -egress`; `sudo pfctl -a com.apple/zoo -sr` and `-sn` show the VM's rules.
- [ ] Run setup again on the base VM, then `ssh root@<vm-ip>` with the API's key works. This is the main unknown for non-admin sandboxes.
- [ ] A new sandbox's user isn't in `admin` and has no `/etc/sudoers.d/zoo`; the guest agent still starts (launchctl as root). An admin sandbox keeps both.
- [ ] As the VM user (and as root in an admin sandbox), `sudo pfctl -d` in the VM doesn't open anything the host policy denies.
- [ ] Repeat the curl checks from the bypass script inside the VM.
- [ ] Safari, Chrome and Firefox profiles capture on one macOS sandbox and load into another (grant Full Disk Access to `/bin/zsh` for Safari).

**Windows host**
- [ ] `Add-VMNetworkAdapterExtendedAcl` exists on the host's Windows edition (it's documented for Windows Server; check client Hyper-V). If it doesn't, the policy call fails; record what to do instead.
- [ ] The `zoo-egress` scheduled task runs after a host reboot; the `zoo egress` firewall rule lets VMs reach port 15128.
- [ ] Check the ACL direction: `Outbound` must mean traffic leaving the VM. With deny-by-default, Edge reaches allowed sites through the proxy and nothing else; `Test-NetConnection 1.1.1.1 -Port 443` fails; SSH and VNC from the API still work.
- [ ] Turn off the proxy settings inside the VM as admin: the VM loses web access rather than gaining it.
- [ ] Reboot the host (the Default Switch subnet changes), then start a filtered sandbox: it boots, and enforcement uses the new host address.
- [ ] On Enterprise or Education, denying a Store app (Calculator) closes it and blocks it from starting. On Pro, record what happens.
- [ ] Chrome and Edge profiles capture and load between clones of the same base VM.

**Secrets**
- [ ] Existing install: `make rotate-secrets` moves every old value to envelope encryption (counts in the output), and the vault, sandbox secrets, agent keys, VNC and profiles all still work after an API restart.
- [ ] `ZOO_KMS` with each of AWS KMS, Google Cloud KMS and Vault transit: run `make rotate-secrets`, restart, and secrets still decrypt. `secret_keys.wrapped` starts with `aws:`, `gcp:` or `vault:`.

### Windows parity (real Hyper-V host)

- [ ] Release: `zoovm.ps1`, `setup.ps1`, `install-node.ps1` and `zoo-guest-windows-amd64.exe` are release assets and in `SHA256SUMS`.
- [ ] `install-node.ps1 -Key … -Iso <url>` on a fresh Windows 11 Pro machine with Hyper-V off: it turns Hyper-V on, the `ZooNodeInstall` logon task carries on after the restart and removes itself, the helper and zoo-guest hashes match, and the base VM installs with no clicks. The VM has no `sshd` service, and its zoo-guest connects once the server is added. Repeat on Windows Server 2022 with `ZOO_WINDOWS_SWITCH`.
- [ ] `zoo node install --windows --key … --iso …` from an elevated Git Bash does the same.
- [ ] Connecting uploads only changed helpers: change one byte of `~\.zoovm\setup.ps1` on the host, reconnect, and only it is rewritten. `helpers.json` holds the API's version.
- [ ] Stop the base VM: the new template has a `.version` next to it (`windows-<build>.<UBR>-<stamp>`). A new sandbox's page shows that version and its boot time. The log has `clone_seconds` (about 1 s). Record the time to a usable desktop (target: under 60 s).
- [ ] Hang recovery: `Suspend-VM zoo-<id>` on the host. Within about 2 minutes the API restarts it and the page shows the notice. A VM at 100 % CPU is never restarted.
- [ ] Windows guest metrics show on the Monitoring page (CPU, memory, network, disk, processes) and match Task Manager roughly.
- [ ] Move a stopped sandbox between two Windows hosts with `ZOO_OBJECT_STORE` on S3 and on MinIO: it boots on the target with its files, `Get-VHD` shows the chain relinked to `moved-…` templates, and the source copy and objects are gone. Move a second sandbox from the same base: only its disk is copied. Record the times.
- [ ] Record the fixtures: `uv run python -m tests.recorded.record windows <sandbox-id>`, then commit `tests/recorded/fixtures/windows.json` so CI replays it.
- [ ] Nightly: set `ZOO_VM_E2E=true` and the `ZOO_E2E_WINDOWS_SERVER` and `ZOO_E2E_SSH_KEY` secrets, so the nightly Windows run (`.github/workflows/nightly.yml`) runs against a real Hyper-V host.
- [ ] A new sandbox gets its `guest.env` through `Copy-VMFile` (no network or account in the VM), and a clone of a freshly sealed template never connects as the base VM. A guest older than the API's build updates in place (`zoo-guest.exe.old` appears next to it) and reconnects.

### macOS parity (real Mac)

- [ ] Release with the signing secrets set: `codesign -dv zoovm` shows `Authority=Developer ID Application`, notarytool reports `Accepted`, and a curl-downloaded zoovm runs without a Gatekeeper prompt. Without the secrets the release still publishes, with the ad-hoc warning.
- [ ] `install.sh --node --key …` on a fresh Mac, end to end:
  - The `SHA256SUMS` check passes.
  - `/etc/sudoers.d/zoo-pf` is in place.
  - macOS installs, and the first boot shuts the VM down by itself.
  - The second boot opens SSH, and `zoo-ready` holds `<os>-<build>-<stamp>`.
  
  The unknowns: whether the Data volume is found and mounts with ownership, whether `.AppleSetupDone` plus the LaunchDaemon skip Setup Assistant on the macOS that installs, and whether the `SetupAssistant` keys skip the per-user screens at autologin. Record which screens still show.
- [ ] Then the API logs in as `admin` and as root with its key, and a sandbox boots from that base without anyone touching it.
- [ ] Create 3 macOS sandboxes on one Mac: the third shows "Mac full" (waiting) and boots after one is stopped. Never more than 2 VMs run, the base included. With `"queue": false` it's a 409.
- [ ] A new sandbox's page shows its base version and boot time. The log has `clone_seconds` under 1 s. Record the boot time (target: under 10 s from stopped base to booted sandbox).
- [ ] Stop the base after changing it: `zoo-ready` gets a new stamp, new clones record it, and old ones keep theirs.
- [ ] Hang recovery: `kill -STOP` the VM's `zoovm run` process. Within about 2 minutes the API restarts it, and the page shows the restart notice. A busy but healthy VM (CPU at 100 %) is never restarted.
- [ ] Darwin guest metrics show on the Monitoring page for a macOS sandbox (CPU, memory, network, disk).
- [ ] Window tools with `/bin/zsh` granted Accessibility: list, focus, minimize, restore, maximize, unmaximize and close all go through the guest (no SSH session in `log show`). Without the grant they still work over System Events.
- [ ] Move a stopped macOS sandbox between two Macs with `ZOO_OBJECT_STORE` on S3 and on MinIO. It boots on the target, the source copy and the objects are gone, and `du -h disk.img` on the target is close to the source's (tar kept the image sparse). Record the time for a typical VM.
- [ ] Record the fixtures: `uv run python -m tests.recorded.record macos <sandbox-id>`, then commit `tests/recorded/fixtures/macos.json` so CI replays it.
- [ ] Nightly: set `ZOO_VM_E2E=true` and the `ZOO_E2E_MACOS_SERVER` and `ZOO_E2E_SSH_KEY` secrets, so the nightly macOS run (`.github/workflows/nightly.yml`) runs against a real Mac.

