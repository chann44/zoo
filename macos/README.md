# macOS sandboxes

macOS sandboxes are microVMs on Apple Silicon Macs. Each Mac runs `zoovm`, a small helper in this folder built on Apple's Virtualization.framework. The API reaches the Mac over SSH and:

- clones a base VM for each sandbox (APFS clones, so this is instant and uses almost no extra disk);
- boots it headless with the framework's VNC server on `127.0.0.1` of the Mac;
- drives the screen, mouse and keyboard over that VNC server through the SSH tunnel;
- runs shell, file, app and window tools over SSH into the guest.

Because the screen is read and controlled from the host, the guest needs no Screen Recording permission. Window tools use System Events, so they need Accessibility (step 4 below).

macOS allows at most 2 macOS VMs running at once on each Mac.

## 1. Build zoovm on the Mac

Requires macOS 13+ on Apple Silicon and the Xcode command line tools.

```bash
git clone <this repo> && cd zoo/macos/zoovm
./build.sh              # installs /usr/local/bin/zoovm; PREFIX=~/.local ./build.sh to install elsewhere
```

## 2. Let the API reach the Mac

- Turn on **System Settings → General → Sharing → Remote Login** on the Mac.
- Put the API's SSH public key in the Mac's `~/.ssh/authorized_keys`.
- Add the Mac's host key to the API's `~/.ssh/known_hosts`, for example with `ssh-keyscan <mac-ip> >> ~/.ssh/known_hosts`.

## 3. Add the Mac and set up the base VM from the dashboard

In **Remote Servers**, choose **macOS** and enter `ssh://you@<mac-ip>` and the Mac's address. The server card gets a **Base VM** panel:

1. **Install macOS** downloads the latest macOS this Mac supports and installs it. Progress shows on the card, and the whole step takes about an hour. The Mac must run at least the macOS version it installs, so update the Mac first if the install fails with "requires a software update".
2. **Start** boots the base VM. **Open screen** shows it live in the browser. Go through Setup Assistant, create a user named `admin` (or set `ZOO_MACOS_USER`), and skip Apple Account, Siri, analytics and FileVault.
3. **Run setup** opens Terminal in the VM and types `guest-setup.sh` with the API's public key. Type the admin password when it asks. The script turns on passwordless sudo, Remote Login with that key, auto-login, and turns off sleep and screen lock.
4. In the VM, open **System Settings → Privacy & Security → Accessibility**, click **+**, press Cmd+Shift+G, enter `/usr/libexec/sshd-keygen-wrapper` and enable it. Window tools need this. Install anything else every sandbox should have.
5. **Stop** shuts the base VM down.

Then create sandboxes with type **macOS**. Each one is a clone of the base VM. To change the base later, stop the server's macOS sandboxes and start the base VM again. New sandboxes get the change, and existing ones keep their own disks.

The same steps work from a terminal on the Mac with `zoovm install zoo-macos-base` and `zoovm run zoo-macos-base`. `run` prints a `vnc://` URL you can open with Screen Sharing.

## Guest agent

When `ZOO_GUEST_REMOTE_URL` is set and the API has the darwin build of `zoo-guest` (`make guest-darwin`, or included in the API image), each boot installs the guest in the VM as a LaunchAgent. Shell and file tools and the Terminal tab then skip SSH. The VM must be able to reach that URL. If the API runs on this Mac, use the Mac's address on the VM network, for example `ws://192.168.64.1:8000/guest/connect`. Window and app tools stay on SSH because they need its Accessibility grant.

## zoovm commands

| Command | Does |
| --- | --- |
| `zoovm install <name> [--ipsw P] [--cpu N] [--memory MB] [--disk GB]` | create a VM from an IPSW (latest if omitted) |
| `zoovm clone <source> <name>` | APFS clone with a new machine id and MAC address |
| `zoovm set <name> [--cpu N] [--memory MB]` | resize |
| `zoovm run <name>` | boot headless and serve VNC; runs until the guest shuts down |
| `zoovm stop <name> [--timeout S]` | stop, forcing it after the timeout |
| `zoovm ip <name>` | guest IP from the host's DHCP leases |
| `zoovm vnc <name>` | VNC URL of a running VM |
| `zoovm list` | JSON list of VMs and their state |
| `zoovm delete <name>` | delete a stopped VM |

VMs live in `~/.zoovm/vms/<name>`.

## Limits

- The guest user is an administrator with passwordless sudo, so an agent with `shell.exec` can undo network (pf) and app policies. Deny `shell.exec` when those policies must hold.
- The VNC server is a private Virtualization.framework API. It works on macOS 13 to 26, but Apple could remove it.
- App profiles and moving sandboxes between servers aren't supported for macOS yet.
- Secrets are written to `~/.zoo/env` in the guest and loaded by `execute_command`. GUI apps don't see them.
