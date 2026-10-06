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
- [ ] Booting a Windows sandbox installs `~\.zoo\bin\zoo-guest.exe` and `~\.zoo\guest.env`, and registers the `zoo-guest` scheduled task (`Get-ScheduledTask zoo-guest`).
- [ ] The task starts in the desktop session and opens no console window. `~\.zoo\guest.log` shows no errors.
- [ ] The API logs `guest connected` with services `exec, pty, files, windows`.
- [ ] `execute_command` and the file tools work through the guest and are faster than over SSH. Measure with `scripts/bench_tools.py`.
- [ ] No console window flashes when a command runs.
- [ ] `write_file`, home backup and restore, and move all work. tar runs as an argv: check paths with spaces.
- [ ] `windows_list`, focus, minimize, maximize, restore and close work. The `app` names match what `agent.ps1` gave, such as `notepad` and `msedge`.
- [ ] `open_app` opens Notepad, a Start menu app (Calculator) and an exe path, and reports `window_found`. `close_app` closes them. `open_url` opens the browser.
- [ ] The Terminal tab opens PowerShell over ConPTY. Typing, resizing and closing the tab (it should end the shell) all work.
- [ ] Commands now run in the desktop session, not the SSH session: GUI apps started by `execute_command` show up on screen, and nothing breaks because of it.
- [ ] Stop and start the sandbox: the guest reconnects, and the binary isn't copied again when unchanged.
- [ ] Ship a new binary: the running guest is stopped, replaced and restarted.
- [ ] A network policy with `deny` by default still lets the guest reach the API.
- [ ] Commands don't see `ZOO_GUEST_TOKEN` (`Get-ChildItem env:ZOO_GUEST*` is empty).
- [ ] Without `ZOO_GUEST_REMOTE_URL`, all tools still work over SSH and `agent.ps1`.
- [ ] Record the benchmark numbers in `docs/guest-agent-plan.md`, Phase 4. If everything passes, delete `agent.ps1` and the fallback in `window()` and `desktop()`.

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
