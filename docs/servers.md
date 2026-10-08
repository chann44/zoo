# Servers

## Add a server

The control plane runs Linux sandboxes on its own machine. Add a server to get more room, or to run another OS:

| Server | Runs |
|---|---|
| Linux (amd64 or arm64; KVM for VM isolation, otherwise runc) | Linux sandboxes |
| Mac (Apple Silicon, macOS 13+) | macOS sandboxes, plus Linux ones with Docker Desktop |
| Windows Pro, Enterprise, Education or Server, with Hyper-V | Windows sandboxes, plus Linux ones with Docker Desktop |

Intel Macs and Windows Home can't run these VMs, so the installer refuses them. A Linux machine without KVM gets runc.

1. In the dashboard, open **Servers**, pick the machine's OS, name it and click **Get the command**. The command carries a one-time [zoo-node](nodes.md) join token.
2. Run the command on the machine: `curl … | sudo bash -s -- --node … --token …` on Linux or a Mac, or PowerShell as administrator on Windows.
   - It runs pre-flight checks first (virtualization, disk, memory, the control plane) and changes nothing if one fails. Add `--check` (or `-Check`) to only run them.
   - It then installs what's needed and zoo-node, which joins the control plane.
3. The server appears under **Servers** when its node connects. zoo-node dials out, so the machine needs no inbound port and can be behind NAT.

**Connect over SSH instead** is the older way, supported until Zoo 2.0. The command then prints a `zoo-join:` line to paste under **Servers**. The line carries the address, platform and SSH host key, so the control plane verifies the machine from its first connection. An SSH server can be switched to zoo-node in place later (see [Converting an SSH server](nodes.md#converting-an-ssh-server)).

The server then appears with what it can run, and the create dialog lists only the sandbox types some server can run; the others say which machine to add. Each server's capabilities are checked again with its status, so installing Docker Desktop later on a Mac adds Linux. macOS and Windows base VMs are built on the server itself (from Apple's IPSW, or a Windows ISO you supply), since neither OS image can be redistributed.

The control-plane installer creates the API's SSH key in `/opt/zoo/ssh`. On other installs, `ZOO_SSH_DIR` (default `~/.ssh`) is mounted read-only into the API, and host keys from join lines go to `/data/known_hosts`.

## Remote servers

**Set up manually instead** under **Servers** takes the same fields by hand. For a Linux machine:

1. Install Docker and Kata Containers and register the `kata` runtime as in the [Quickstart](install.md#quickstart). Add an SSH user to the `docker` group.
2. Make sure the API host can SSH in with a key and no password prompt, and knows the machine's host key.

Then fill in:

- **Docker URL**: `ssh://user@10.0.0.5`, or `tcp://host:2376` for a TLS-configured daemon.
- **Address**: an IP the API can reach, such as a LAN or Tailscale IP. Desktop ports are published on this address, so keep it on a private network.

Servers added this way are reached with Docker over SSH (`ssh://`, through the `ssh` client and its known hosts) or Docker's TLS port (`tcp://`). That keeps working until Zoo 2.0. **Switch to zoo-node** on a server, or `zoo-node migrate`, converts an `ssh://` server in place (see [zoo-node](nodes.md#converting-an-ssh-server)).

A server is rejected if its Docker daemon doesn't have the configured runtime. If a server doesn't have the sandbox image, the API pulls it, or copies it over from the main host.

When creating a sandbox you can pick a server or **Least busy server**. Least busy means the most free memory among hosts that report it (see [Placement](nodes.md#placement)), and otherwise the fewest sandboxes.

To move a stopped sandbox, use the **Server** tab or `POST /sandboxes/{id}/move`.

- With `ZOO_OBJECT_STORE` set, the home volume goes through object storage. The source host packs it and uploads it in 1 GB parts to presigned URLs, and the target downloads them, so the data never passes through the API host. macOS and Windows disks always move this way.
- Without object storage, a Linux home streams through the API.

The source copy is removed afterwards. A sandbox with snapshots stays on its server until they are deleted. A server can only be removed once no sandboxes are on it.

## macOS sandboxes

A `macos` sandbox is a macOS microVM on an Apple Silicon Mac. The Mac runs `zoovm`, our helper on Apple's Virtualization.framework (`macos/zoovm`). The API reaches the Mac over SSH. It drives the screen, mouse and keyboard through the VM's VNC server and runs the other tools over SSH into the guest, so agents use the same tools as on Linux.

Setup (build `zoovm`, install a base VM, prepare the guest, add the Mac as a **macOS** server) is in [macos/README.md](../macos/README.md).

How it differs from Linux sandboxes:

- Stop shuts the VM down and keeps its disk. Start boots the same VM again. Delete removes it.
- macOS runs at most 2 VMs per Mac. **Least busy server** picks a Mac with room.
- Network policy is enforced by pf on the Mac and a proxy there, with pf in the guest as a second layer. App policy locks `/Applications/<App>.app`. The guest user has no sudo unless the sandbox is created as an admin sandbox (see `macos/README.md`).
- `installed_apps` lists `.app` bundles and Homebrew packages. `open_app` takes an app name like `Safari`. Window ids look like `Safari:1`.
- Key names follow X11 keysyms as on Linux. Use `cmd` for Command.
- App profiles, monitoring metrics and moving between Macs (through `ZOO_OBJECT_STORE`) work. Each sandbox records the base VM version it was cloned from, and hung VMs are restarted.

## Windows sandboxes

A `windows` sandbox is a Hyper-V VM on a Windows machine. The API reaches the machine over SSH and drives Hyper-V with `windows/zoovm.ps1`, which it uploads itself. Agents use the same tools as on Linux: screen, mouse and keyboard go through a VNC server in the guest, and every other tool through zoo-guest in the guest's desktop session. The VMs run no SSH server.

Setup (turn on Hyper-V and OpenSSH on the host, add the machine as a **Windows** server, install the base VM from an ISO) is in [windows/README.md](../windows/README.md). The base VM sets itself up unattended, with no Setup screens to click through.

How it differs from Linux sandboxes:

- Stop shuts the VM down and keeps its disk. Start boots the same VM again. Delete removes it.
- Each sandbox starts from a frozen template of the base VM, so you can change the base while sandboxes run. **Stop** on the base VM saves a new template.
- At most `ZOO_WINDOWS_MAX_VMS` (default 4) run on each server.
- `execute_command` runs PowerShell. Paths are Windows paths, starting at `C:\Users\zoo`.
- Network policy is enforced on the host with Hyper-V port ACLs and a proxy, with Windows Firewall as a second layer. App policy blocks `.exe` files and, on editions with AppLocker, Store apps. The guest user is an administrator, so an agent with `shell.exec` can undo app policy (see `windows/README.md`).
- App profiles, monitoring metrics and moving between Windows servers (through `ZOO_OBJECT_STORE`) work. Each sandbox records the template version it was cloned from, and hung VMs are restarted.

Supported versions, Hyper-V requirements, licensing and troubleshooting are in [Windows sandboxes](windows.md).
