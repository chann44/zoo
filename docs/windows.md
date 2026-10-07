# Windows sandboxes

A `windows` sandbox is a Hyper-V VM on a Windows machine that you add as a server. Step-by-step setup and the `zoovm.ps1` commands are in [windows/README.md](../windows/README.md). This page covers what's supported, licensing, how sandboxes are versioned, moved and recovered, and troubleshooting.

## Supported versions

**Host** (the machine that runs the VMs):

| | Supported |
| --- | --- |
| Windows 10 / 11 | Pro, Enterprise or Education, 64-bit. Home has no Hyper-V. |
| Windows Server | 2019, 2022 or 2025 with the Hyper-V role |
| CPU | x64 (Intel or AMD). ARM64 hosts aren't tested, and zoo-guest is only built for amd64. |

**Guest** (the base VM): any Windows 10, Windows 11 or Windows Server ISO that has `sources\install.wim` or `install.esd`, including the free evaluation ISOs. With several editions on the ISO, Pro is picked unless you pass an edition. Store app blocking needs AppLocker, so it only works on Enterprise and Education guests (see [Limits](#limits)).

## Hyper-V requirements

- Virtualization (Intel VT-x or AMD-V, with SLAT) turned on in the firmware. `install-node.ps1` checks this.
- Hyper-V turned on. `install-node.ps1` does it, and finishes after the restart Hyper-V needs.
- 8 GB of memory at least; 16 GB or more to run several sandboxes. Each sandbox takes `ZOO_WINDOWS_MEMORY_MB` (default 8192) of static memory.
- 80 GB free on `C:` for the base VM, its templates and sandbox disks.
- A virtual switch with DHCP. Windows 10 and 11 have the **Default Switch**. Windows Server doesn't: create an external switch, or an internal one with your own NAT and DHCP, and set `ZOO_WINDOWS_SWITCH` to its name in the host user's environment.
- OpenSSH Server **on the host**, with the control plane's key in `C:\ProgramData\ssh\administrators_authorized_keys`. The SSH user must be an administrator, since building the base VM mounts disks and applies a Windows image. The VMs themselves run no SSH server.
- The Hyper-V **Guest Service Interface**, which zoovm turns on for every VM. The host uses it to copy each VM its guest identity and zoo-guest updates.
- `ZOO_GUEST_REMOTE_URL` on the API: an address of the API the VMs can reach (see [windows/README.md](../windows/README.md#guest-agent)).
- Network policy uses `Add-VMNetworkAdapterExtendedAcl`, which is documented for Windows Server. On a Windows 10 or 11 host, check that it exists (`Get-Command Add-VMNetworkAdapterExtendedAcl`) before you rely on network policy.

## Set up a host in one command

In an elevated PowerShell on the Windows machine, run the line from **Servers → Add server → Windows**. Add `-Iso` to also build the base VM without visiting the dashboard:

```powershell
powershell -ExecutionPolicy Bypass -c "& ([scriptblock]::Create((irm https://github.com/chann44/zoo/releases/latest/download/install-node.ps1))) -Key '<key>' -ControlPlane '<url>' -Iso 'https://<windows iso url>'"
```

Or, from Git Bash started as administrator:

```bash
zoo node install --windows --key '<key>' --control-plane '<url>' --iso 'D:\isos\win11.iso'
```

The script:

1. checks the machine and changes nothing if a check fails;
2. turns on Hyper-V. If that needs a restart, it registers a one-time logon task and carries on by itself after you restart and sign in;
3. installs OpenSSH Server on the host and authorizes the control plane's key;
4. with `-Iso`, downloads this release's `zoovm.ps1`, `setup.ps1` and zoo-guest, checks them against the release's `SHA256SUMS`, and starts the base VM install in the background. The log is `~\.zoovm\install.log`, and it takes 15 to 30 minutes;
5. prints the join line to paste under **Servers → Add server**.

Once the base VM is ready, **Stop** it on the server's page. That seals its first template, and sandboxes can start.

## Helper scripts

The API puts its own copies of `zoovm.ps1` and `setup.ps1` in `~\.zoovm` on each host when it connects. It uploads only the files whose SHA-256 differs, then checks every hash again. If one still doesn't match, the connection fails instead of running a stale script. `~\.zoovm\helpers.json` records the helper version and each file's hash. Each release also publishes the scripts on their own, with their hashes in `SHA256SUMS`.

## Template versions

Stopping the base VM seals its disk as a read-only template, and sandboxes boot from a differencing disk over the latest template. Each template gets a version, `windows-<build>.<revision>-<UTC minute>` (for example `windows-26100.4061-202610071200`). Every sandbox records the version it was cloned from, and its Overview tab shows it with its last boot time. Sandboxes keep their template when the base VM changes. Only new sandboxes get the new one.

The API logs `clone_seconds` for each clone and `boot_seconds` for each boot. A clone is a new differencing disk, so it takes about a second. The target from clone to a usable desktop is under 60 seconds.

## Hang recovery

The API checks every running Windows sandbox every 15 seconds. When zoo-guest stops sending metrics and the VM's VNC server stops answering, on checks 60 seconds apart, the API stops the VM and boots it again. The sandbox page then shows a notice. A VM that's busy but still draws or reports in is never restarted. Without zoo-guest, only the screen is checked.

## Monitoring

zoo-guest reports CPU, memory, network, disk and process counts for the whole VM every 10 seconds. These show on the Monitoring page, as they do for Linux and macOS sandboxes.

## Moving between servers

A stopped Windows sandbox can move to another Windows server (the **Server** tab, or `POST /sandboxes/{id}/move`). This needs object storage: set `ZOO_OBJECT_STORE` (see [Configuration](configuration.md)).

The VM's disk is a differencing disk, so its templates move with it. The source host uploads each file in 1 GB parts to presigned URLs, and the target downloads them. The target stores the templates as `moved-<server>-<name>.vhdx`, apart from its own base VM's, and skips any it already has from an earlier move. It then relinks the disk chain and registers the VM. The first move off a server copies the full template (often 15 to 25 GB). Later moves copy only the sandbox's own disk. If the move fails, the source VM is kept and the target's partial copy is removed.

## Licensing

This is guidance, not legal advice. Check your agreement or ask your Microsoft licensing contact.

- **Every VM runs its own copy of Windows**, so each sandbox needs a license, the same as any VM.
- **Evaluation ISOs** are free and fine for trying Zoo: Windows 11 Enterprise evaluation runs for 90 days, and Windows Server evaluation for 180 days. After that, Windows shuts down periodically. Rebuild the base VM from a fresh evaluation ISO, or convert to a licensed edition.
- **Unactivated Windows** works, but shows a watermark and locks personalization settings.
- **Windows Server guests on a Windows Server Datacenter host** can use Automatic Virtual Machine Activation (AVMA). Put the AVMA key for the guest's version in the base VM, and every clone activates against the host, with no per-VM key and no network activation.
- **Windows 10 and 11 guests** at volume usually need Enterprise E3/E5 or Windows VDA rights per user, plus KMS or MAK activation.
  - **KMS:** Zoo doesn't sysprep clones, so every clone of a template shares the base VM's client machine ID. A KMS host counts them as one machine and won't reach its activation threshold of 25 client machines. Sysprep the base VM yourself before sealing it, or use MAK.
  - **MAK:** each clone uses one activation from the key's count.
  - **Active Directory-based activation** needs a domain join, and clones shouldn't be joined to a domain (they share a SID).
- **Store apps and Microsoft accounts:** sign-ins made in the base VM are copied to every clone.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Base VM install fails | `~\.zoovm\install.log` on the host. The server card shows its last line. Missing `install.wim`/`install.esd` means the ISO isn't a Windows install ISO. A wrong `-Edition` lists the editions it found. |
| Base VM stays "finishing setup" | `C:\zoo\setup.log` in the VM (use **Open screen**). Setup downloads TightVNC, so the VM needs internet access. The base VM is ready once its zoo-guest connects: see the next rows. |
| `Hyper-V switch '…' not found` | Windows Server has no Default Switch: create one and set `ZOO_WINDOWS_SWITCH`. |
| `… has no IPv4 address yet` | The switch has no DHCP, or the VM is still booting. `Get-VMNetworkAdapter -VMName zoo-<id>` on the host shows its addresses. |
| `the base VM isn't ready yet` | Start and **Stop** the base VM once its setup is done. Stopping seals the first template. |
| `this server already runs N Windows VMs` | Raise `ZOO_WINDOWS_MAX_VMS`, or stop a sandbox. |
| `the helper scripts on the host don't match` | The API couldn't write `~\.zoovm` (disk full, or a file locked by a running `zoovm.ps1`). Free space, or wait for the running command to finish, and reconnect. |
| `the Windows guest agent isn't connected` or `didn't connect` | Check `ZOO_GUEST_REMOTE_URL` is an address the VM can reach, and read `C:\ProgramData\zoo\guest.log` in the VM (**Open screen**). A network policy block rule for the API's address cuts the guest off. A base VM built before zoo-guest replaced SSH has no guest: reinstall it. |
| `Windows sandboxes need ZOO_GUEST_REMOTE_URL` | Set it on the API (see [Configuration](configuration.md)). |
| Copying the identity fails (`Copy-VMFile`) | The VM's Guest Service Interface must be on (`Get-VMIntegrationService -VMName zoo-<id>`). zoovm turns it on for every VM it creates. |
| A filtered sandbox has no web access | The host's `zoo-egress` task must be running (`Get-ScheduledTask zoo-egress`), and the `zoo egress` firewall rule must allow port 15128. |
| Store app policy has no effect | AppLocker only enforces on Enterprise and Education guests. |
| SSH to the host fails with a host key error | Add the host key to the API's `known_hosts` (`ssh-keyscan <host> >> ~/.ssh/known_hosts`), or re-add the server with the join line, which carries its key. |
| A sandbox keeps getting restarted | The VM hung (see [Hang recovery](#hang-recovery)). Check the VM's memory and the host's free memory and disk. |
| Moving fails with `needs object storage` | Set `ZOO_OBJECT_STORE` and its credentials on the API. |
| Boots get slower over time | Each base VM edit adds a template to the chain. Reinstall the base VM if you've edited it many times. |

## Limits

- The guest user is an administrator, so an agent with `shell.exec` can undo app policy and the VM's own firewall rules. It can't undo the host's port ACLs and proxy, so network policy holds.
- Clones share the base VM's computer name and machine SID. Don't join them to a domain.
- Chrome and Edge profiles are encrypted with keys every clone of a base VM shares, so they only load into clones of the same base VM.
- Windows VMs aren't in the warm pool yet. Each clone is configured when it starts.
