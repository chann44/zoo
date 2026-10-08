---
title: macOS sandboxes
description: macOS microVMs on Apple Silicon Macs — hardware, zoovm, the base VM, and troubleshooting.
---

A `macos` sandbox is a macOS microVM on an Apple Silicon Mac. The Mac runs `zoovm`, a
helper built on Apple's Virtualization.framework (`macos/zoovm`). The API reaches the Mac
over SSH: it clones the base VM for each sandbox (APFS clones — instant, almost no extra
disk), boots it headless, drives the screen, mouse and keyboard through the framework's
VNC server, and runs the other tools through the guest agent (`zoo-guest`) in the VM.

Because the screen is read and controlled from the host, the guest needs no Screen
Recording permission. Window tools need one Accessibility grant.

## Hardware and versions

- **Host:** an Apple Silicon Mac (M1 or later; Intel Macs can't run macOS VMs) on macOS 13
  or later, with 16 GB of memory (32 GB to run two sandboxes comfortably) and 100 GB free
  for the base VM and its download.
- **Guest:** the macOS the host supports, up to the host's own version. A Mac on macOS 15
  can't install macOS 26 — update the Mac, or pass `--ipsw` with an older restore image.
- **Limit:** Apple's license allows 2 macOS VMs running at once per Mac, the base VM
  included. A sandbox created while every Mac is full waits in the queue ("Mac full" on
  its page) and starts when a VM stops, for up to 2 hours. Create it with
  `"queue": false` to get a `409 Mac full` error instead.

## Unattended setup

Run the command from **Servers → Add server → Mac** on the Mac, or
`zoo node install --macos --key "<the API's public key>"` with the `zoo` CLI from a
release. It checks the Mac, turns on Remote Login, authorizes the API's key, installs
signed `zoovm`, adds the passwordless `pfctl` sudoers rule for network policy, installs
macOS into the base VM (about an hour), and prepares it without Setup Assistant: first
boot creates the `admin` user, runs the guest setup and shuts down; a second boot checks
SSH and marks the base ready with its version.

What stays manual is the Accessibility grant, which macOS reserves for a person — see
step 4 below. Without it everything works except window tools.

## The dashboard way (and fixing a base)

1. **Build zoovm**: needs macOS 13+ on Apple Silicon and the Xcode command line tools.
   `git clone <repo> && cd zoo/macos/zoovm && ./build.sh` installs `/usr/local/bin/zoovm`.
2. **Let the API reach the Mac**: turn on **System Settings → General → Sharing → Remote
   Login**, put the API's SSH public key in `~/.ssh/authorized_keys`, and add the Mac's
   host key to the API's `known_hosts` (`ssh-keyscan <mac-ip>`).
3. **Add the Mac**: under **Remote Servers**, choose **macOS**, enter
   `ssh://you@<mac-ip>` and the Mac's address. The server card gets a **Base VM** panel.
4. **Install macOS** downloads the latest macOS this Mac supports and installs it (about
   an hour). **Start** boots the base VM; **Open screen** shows it live. Go through Setup
   Assistant, create the user `admin` (or set `ZOO_MACOS_USER`), skip Apple Account, Siri,
   analytics and FileVault.
5. **Run setup** opens Terminal in the VM and types `guest-setup.sh` with the API's public
   key — passwordless sudo, Remote Login with that key, auto-login, no sleep or screen
   lock.
6. **Accessibility grant**: in the VM, **System Settings → Privacy & Security →
   Accessibility**, click **+**, Cmd+Shift+G, add `/usr/libexec/sshd-keygen-wrapper` and
   enable it. Do the same for `/bin/zsh` — the guest agent runs under it, and window tools
   read accessibility trees natively only with the grant. Install anything else every
   sandbox should have.
7. **Stop** shuts the base VM down.

Then create sandboxes with type **macOS** — each is a clone of the base. To change the
base later, stop the server's macOS sandboxes and start the base again: new sandboxes get
the change, existing ones keep their own disks.

Each base VM has a version, `<macOS version>-<build>-<UTC time>`, shown on each sandbox's
page with its boot time. The target is under 10 seconds from the stopped base to a booted
sandbox.

## Guest agent and metrics

When `ZOO_GUEST_REMOTE_URL` is set, each boot installs `zoo-guest` in the VM as a
LaunchAgent and shell, file, app and window tools plus the Terminal tab skip SSH. If the
API runs on the same Mac, use the Mac's address on the VM network, e.g.
`ws://192.168.64.1:8000/guest/connect`. The guest sends metrics every 10 seconds, which
double as its heartbeat: a running VM whose guest goes quiet **and** whose screen stops
answering for a minute is restarted by the API, and the sandbox page says when.

## Network policy

The Mac enforces each VM's network policy itself, so nothing inside the VM can undo it:
the API runs `zoo-guest -egress` on the Mac, which proxies the VMs' web traffic and DNS,
deciding by name, and loads pf rules into the `com.apple/zoo` anchor. The pf rules inside
the VM stay as a second layer. The Mac's user needs passwordless sudo for `pfctl` only —
the installer adds it:

```sh
echo "$USER ALL=(root) NOPASSWD: /sbin/pfctl" | sudo tee /etc/sudoers.d/zoo-pf
```

## Limits

- Sandboxes run as a standard user by default, so an agent can't undo the VM's own pf
  rules or app policy. Create an **admin sandbox** (the **Guest user** option, or
  `"admin": true`) when the agent needs sudo.
- A VM's pf rules on the Mac match its address. An admin sandbox can change its address to
  another VM's, so give admin sandboxes the strictest policy on that Mac, or a Mac of
  their own.
- Safari profiles need Full Disk Access for `/bin/zsh` in the base VM.
- The VNC server is a private Virtualization.framework API. It works on macOS 13 to 26,
  but Apple could remove it.
- Moving macOS sandboxes between Macs needs `ZOO_OBJECT_STORE` (S3, or MinIO/R2 via
  `ZOO_S3_ENDPOINT`).
- Secrets are written to `~/.zoo/env` in the guest and loaded by `execute_command`. GUI
  apps don't see them.

## zoovm commands

| Command | Does |
| --- | --- |
| `zoovm install <name> [--ipsw P] [--cpu N] [--memory MB] [--disk GB]` | create a VM from an IPSW (latest if omitted) |
| `zoovm clone <source> <name>` | APFS clone with a new machine id and MAC address |
| `zoovm set <name> [--cpu N] [--memory MB]` | resize |
| `zoovm run <name>` | boot headless and serve VNC |
| `zoovm stop <name> [--timeout S]` | stop, forcing it after the timeout |
| `zoovm ip <name>` | guest IP from the host's DHCP leases |
| `zoovm vnc <name>` | VNC URL of a running VM |
| `zoovm version <name>` | the macOS version and build it was installed from, as JSON |
| `zoovm list` | JSON list of VMs and their state |
| `zoovm delete <name>` | delete a stopped VM |

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "requires a software update" when installing macOS | The IPSW is newer than the Mac's macOS. Update the Mac, or install an older macOS with `--ipsw PATH`. |
| Download or install stops partway | Run it again: the IPSW download resumes. Needs about 100 GB free. Log: `~/.zoovm/install.log`. |
| The Mac shows offline, or the API can't SSH in | Remote Login on; the API's key in the Mac user's `authorized_keys`; the Mac's host key in the API's `known_hosts`; `zoovm` on that user's PATH. |
| The base VM never opens SSH after unattended setup | Start it from the server's page and open its screen. At a login window: the first-boot log is `/var/log/zoo-firstboot.log` in the VM; finish with **Run setup**. |
| Window tools fail with an Accessibility error | Grant Accessibility to `/bin/zsh` and `/usr/libexec/sshd-keygen-wrapper` in the base VM; recreate sandboxes cloned before the grant. |
| Network policy fails with a pfctl error | Add the sudoers rule under [Network policy](#network-policy). |
