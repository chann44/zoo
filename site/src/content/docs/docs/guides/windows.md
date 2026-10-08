---
title: Windows sandboxes
description: Hyper-V VMs on Windows hosts — supported versions, the one-command setup, base VMs and templates, licensing, troubleshooting.
---

A `windows` sandbox is a Hyper-V VM on a Windows machine that you add as a server. The API
reaches the machine over SSH and drives Hyper-V with `zoovm.ps1`, which it uploads itself.
The base VM is built straight from a Windows ISO and sets itself up — no Setup screens to
click through. Each sandbox boots from a differencing disk over a frozen template of the
base, so creating one takes about a second. The screen, mouse and keyboard go through a
VNC server (TightVNC) in the guest; every other tool goes through zoo-guest, which runs in
the guest's desktop session. The VMs run no SSH server.

## Supported versions

**Host** (the machine that runs the VMs):

| | Supported |
| --- | --- |
| Windows 10 / 11 | Pro, Enterprise or Education, 64-bit. Home has no Hyper-V. |
| Windows Server | 2019, 2022 or 2025 with the Hyper-V role |
| CPU | x64 (Intel or AMD). ARM64 hosts aren't tested. |

**Guest** (the base VM): any Windows 10, Windows 11 or Windows Server ISO that has
`sources\install.wim` or `install.esd`, including the free evaluation ISOs. With several
editions on the ISO, Pro is picked unless you pass an edition. Store app blocking needs
AppLocker, so it only works on Enterprise and Education guests.

## Requirements

- Virtualization (Intel VT-x or AMD-V, with SLAT) turned on in the firmware.
- Hyper-V turned on; 8 GB of memory at least (16 GB or more for several sandboxes — each
  takes `ZOO_WINDOWS_MEMORY_MB`, default 8192, of static memory); 80 GB free on `C:`.
- A virtual switch with DHCP. Windows 10 and 11 have the **Default Switch**. Windows
  Server doesn't: create one and set `ZOO_WINDOWS_SWITCH` in the host user's environment.
- OpenSSH Server **on the host**, with the control plane's key in
  `C:\ProgramData\ssh\administrators_authorized_keys`. The SSH user must be an
  administrator — building the base VM mounts disks and applies a Windows image.
- `ZOO_GUEST_REMOTE_URL` on the API: an address of the API the VMs can reach. Required for
  Windows sandboxes.
- Network policy uses `Add-VMNetworkAdapterExtendedAcl`, which is documented for Windows
  Server. On a Windows 10 or 11 host, check it exists before you rely on network policy.

## Set up a host in one command

In an elevated PowerShell on the Windows machine, run the line from
**Servers → Add server → Windows**:

```powershell
powershell -ExecutionPolicy Bypass -c "& ([scriptblock]::Create((irm https://github.com/chann44/zoo/releases/latest/download/install-node.ps1))) -Key '<key>' -ControlPlane '<url>' -Iso 'https://<windows iso url>'"
```

Or, from Git Bash started as administrator:

```bash
zoo node install --windows --key '<key>' --control-plane '<url>' --iso 'D:\isos\win11.iso'
```

The script checks the machine (changing nothing if a check fails), turns on Hyper-V
(registering a one-time logon task if a restart is needed), installs OpenSSH Server and
authorizes the control plane's key, and with `-Iso` downloads this release's `zoovm.ps1`,
`setup.ps1` and zoo-guest (checked against the release's `SHA256SUMS`) and starts the base
VM install in the background. The log is `~\.zoovm\install.log`; it takes 15 to 30
minutes, mostly downloads.

Once the base VM is ready, **Stop** it on the server's page — that seals its first
template, and sandboxes can start.

## Base VMs, templates and hang recovery

- The API uploads its own copies of `zoovm.ps1` and `setup.ps1` to `~\.zoovm` on each
  host, checking every SHA-256; a mismatch fails the connection instead of running a stale
  script.
- Stopping the base VM seals its disk as a read-only template, versioned
  `windows-<build>.<revision>-<UTC minute>`. Sandboxes boot from a differencing disk over
  the latest template, record the version they were cloned from, and keep it when the base
  changes.
- At most `ZOO_WINDOWS_MAX_VMS` (default 4) run on each server.
- The API checks every running Windows sandbox every 15 seconds. When zoo-guest stops
  sending metrics **and** the VM's VNC stops answering, on checks 60 seconds apart, the
  API stops the VM and boots it again; the sandbox page shows a notice. A VM busy but
  still drawing or reporting in is never restarted.
- zoo-guest reports CPU, memory, network, disk and process counts every 10 seconds, on the
  Monitoring page as for Linux and macOS.
- A stopped Windows sandbox moves to another Windows server (needs
  `ZOO_OBJECT_STORE`). The first move off a server copies the full template (often 15 to
  25 GB); later moves copy only the sandbox's own disk.

## Tools on Windows

- `execute_command` runs PowerShell. Paths are Windows paths starting at `C:\Users\zoo`.
- `installed_apps` lists Start menu apps; `open_app` takes a Start menu name like
  `Notepad`, an app ID, or a command line.
- Window ids are window handles from `windows_list`, which also returns each window's
  process name.
- Key names follow X11 keysyms as on Linux. Use `win` or `super` for the Windows key.
- Secrets go to `C:\Users\zoo\.zoo\env.ps1` and are loaded by `execute_command`. GUI apps
  don't see them. Backups skip `AppData\Local` and the registry hive, which Windows keeps
  locked.

## Licensing

This is guidance, not legal advice — check your agreement or your Microsoft licensing
contact.

- **Every VM runs its own copy of Windows**, so each sandbox needs a license, the same as
  any VM.
- **Evaluation ISOs** are fine for trying Zoo: Windows 11 Enterprise evaluation runs 90
  days, Windows Server 180. After that Windows shuts down periodically — rebuild the base
  VM, or convert to a licensed edition.
- **AVMA**: Windows Server guests on a Windows Server Datacenter host activate against the
  host with an AVMA key in the base VM — no per-VM key.
- **KMS**: Zoo doesn't sysprep clones, so every clone shares the base VM's client machine
  ID and a KMS host counts them as one machine. Sysprep the base VM yourself before
  sealing it, or use MAK.
- **Domains**: clones share the base VM's computer name and machine SID — don't join them
  to a domain.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Base VM install fails | `~\.zoovm\install.log` on the host; the server card shows its last line. Missing `install.wim`/`install.esd` means it isn't a Windows install ISO. |
| Base VM stays "finishing setup" | `C:\zoo\setup.log` in the VM (**Open screen**). Setup downloads TightVNC, so the VM needs internet. |
| `Hyper-V switch '…' not found` | Windows Server has no Default Switch: create one and set `ZOO_WINDOWS_SWITCH`. |
| `… has no IPv4 address yet` | The switch has no DHCP, or the VM is still booting. |
| `the base VM isn't ready yet` | Start and **Stop** the base VM once its setup is done. |
| `this server already runs N Windows VMs` | Raise `ZOO_WINDOWS_MAX_VMS`, or stop a sandbox. |
| `the Windows guest agent isn't connected` | Check `ZOO_GUEST_REMOTE_URL` is reachable from the VM; read `C:\ProgramData\zoo\guest.log` (**Open screen**). |
| Store app policy has no effect | AppLocker only enforces on Enterprise and Education guests. |
| A sandbox keeps getting restarted | The VM hung — check the VM's and the host's free memory and disk. |
| Moving fails with `needs object storage` | Set `ZOO_OBJECT_STORE` and its credentials on the API. |

## Limits

- The guest user is an administrator, so an agent with `shell.exec` can undo app policy
  and the VM's own firewall rules. It can't undo the host's port ACLs and proxy, so
  network policy holds. See the [security model](/docs/concepts/security-model/).
- Templates form a chain of differencing disks, one per base VM edit — very long chains
  get slower; reinstall the base VM if you've edited it many times.
- Chrome and Edge profiles only load into clones of the same base VM.
- Windows VMs aren't in the warm pool yet. Each clone is configured when it starts.
