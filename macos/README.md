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

## 2. Install the base VM

```bash
zoovm install zoo-macos-base              # downloads the latest macOS for this Mac and installs it
# or: zoovm install zoo-macos-base --ipsw ~/Downloads/UniversalMac.ipsw --cpu 4 --memory 8192 --disk 80
```

Installing takes 20 to 40 minutes.

## 3. Finish setup over VNC

```bash
zoovm run zoo-macos-base      # prints vnc://:<password>@127.0.0.1:<port>
```

Open that URL on the Mac with Screen Sharing, or tunnel it with `ssh -L 5901:127.0.0.1:<port> mac` and connect to `localhost:5901`. Go through Setup Assistant:

- create a user named `admin` (or set `ZOO_MACOS_USER` on the API);
- skip Apple Account, Siri, analytics and FileVault.

Then copy `macos/guest-setup.sh` into the VM and run it in Terminal with the API's SSH public key, the one the API uses to reach the Mac:

```bash
sh guest-setup.sh "ssh-ed25519 AAAA... zoo-api" "<admin password>"
```

It enables passwordless sudo, Remote Login with that key, auto-login, and turns off sleep and screen lock.

## 4. Grant Accessibility

In the VM, open **System Settings → Privacy & Security → Accessibility**, click **+**, press Cmd+Shift+G, enter `/usr/libexec/sshd-keygen-wrapper` and enable it. Window tools need this.

Install anything else every sandbox should have, such as browsers or Homebrew. Then shut the VM down from the Apple menu.

## 5. Add the Mac to Zoo

In the dashboard, open **Remote Servers**, choose **macOS**, and enter `ssh://you@mac-host` plus the Mac's address. The API checks that `zoovm` and the base VM are there. Create sandboxes with type **macOS**.

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
