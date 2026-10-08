---
title: Remote Linux servers
description: Add Linux machines to spread sandboxes out — with zoo-node, the dial-out daemon that needs no inbound port.
---

The control plane runs Linux sandboxes on its own machine. Add a server to get more room,
or to run another OS:

| Server | Runs |
|---|---|
| Linux (amd64 or arm64; KVM for VM isolation, otherwise runc) | Linux sandboxes |
| Mac (Apple Silicon, macOS 13+) | macOS sandboxes, plus Linux ones with Docker Desktop |
| Windows Pro, Enterprise, Education or Server, with Hyper-V | Windows sandboxes, plus Linux ones with Docker Desktop |

Intel Macs and Windows Home can't run these VMs, so the installer refuses them. A Linux
machine without KVM gets runc.

## Add a server with zoo-node

[zoo-node](#how-zoo-node-works) is a small daemon on each host that runs sandboxes:

1. In the dashboard, open **Servers**, pick the machine's OS, name it and click
   **Get the command**. The command carries a one-time join token.
2. Run the command on the machine: `curl … | sudo bash -s -- --node … --token …` on Linux
   (or a Mac), or PowerShell as administrator on Windows.
   - It runs pre-flight checks first (virtualization, disk, memory, the control plane) and
     changes nothing if one fails. Add `--check` to only run them.
   - It then installs what's needed and zoo-node, which joins the control plane.
3. The server appears under **Servers** when its node connects.

On a machine that is already set up, run only the join line the dashboard shows:

```sh
sudo zoo-node join '<token>' --service                    # Linux
zoo-node join '<token>' --service                         # Mac, as the user that runs the VMs
zoo-node.exe join '<token>' --service --ssh-user <user>   # Windows, elevated
```

A token works once and expires after an hour. It carries the API's URL and the fingerprint
of its node CA, so a man in the middle of the join request can't slip in its own.

## How zoo-node works

The node **dials out** to the API and keeps one mTLS gRPC stream up, so the machine needs
no inbound port and can sit behind NAT. It:

- reports the host's capacity, health and running sandboxes, and the scheduler places
  sandboxes by that free capacity;
- carries the API's connections to the host's Docker socket (and, on macOS and Windows,
  its SSH server), so every runtime operation works the same as over SSH;
- updates itself to the API's version;
- renews its own certificate (a year each; renewed within 30 days of expiry).

## SSH, the older way

**Connect over SSH instead** is supported until Zoo 2.0. The command then prints a
`zoo-join:` line to paste under **Servers**; the line carries the address, platform and
SSH host key, so the control plane verifies the machine from its first connection.

You can also set a Linux machine up manually under **Servers**: install Docker and Kata as
in the [quickstart](/docs/get-started/install/), add an SSH user to the `docker` group,
then fill in a Docker URL (`ssh://user@10.0.0.5`, or `tcp://host:2376` for TLS) and a bind
address on a private network — desktop ports are published there.

An SSH server can be switched to zoo-node in place later: click **Switch to zoo-node** on
it, or `zoo-node migrate <server-id> --api <url> --key <key>`. Sandboxes stay where they
are.

## Placement and moves

When creating a sandbox you can pick a server or **Least busy server**: the most free
memory among hosts that report it, otherwise the fewest sandboxes. A Linux sandbox needs
2 GB; the macOS and Windows per-host VM limits still apply.

A stopped sandbox moves with the **Server** tab or `POST /sandboxes/{id}/move`. With
`ZOO_OBJECT_STORE` set, the home volume goes through object storage in 1 GB parts and the
data never passes through the API host; without it, a Linux home streams through the API.
macOS and Windows disks always move through object storage. The source copy is removed
afterwards. A sandbox with snapshots stays on its server until they are deleted.
