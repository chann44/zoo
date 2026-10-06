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
