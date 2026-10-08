# Windows sandboxes

Windows sandboxes are Hyper-V VMs on a Windows machine. The API reaches the machine over SSH, uploads the scripts in this folder to `~\.zoovm`, and drives Hyper-V with `zoovm.ps1`:

- the base VM is built straight from a Windows ISO and sets itself up, with no clicking through Setup;
- each sandbox boots from a differencing disk on top of a frozen template of the base VM, so creating one is instant and uses almost no extra disk;
- the screen, mouse and keyboard go through a VNC server (TightVNC) in the guest, tunnelled through the host's SSH connection;
- every other tool, admin changes and the Terminal tab go through zoo-guest, which runs in the guest's desktop session and dials the API (see [Guest agent](#guest-agent)). The guest has no SSH server or other way in.

Supported versions, licensing, template versions, moving, hang recovery and troubleshooting are in [docs/windows.md](../docs/windows.md).

## 1. Prepare the Windows machine

The quickest way is `install-node.ps1` (the line under **Servers → Add server → Windows**), which does the steps below, and with `-Iso` also step 2. See [docs/windows.md](../docs/windows.md#set-up-a-host-in-one-command). By hand:

Requires Windows 10/11 Pro, Enterprise or Education, or Windows Server, on hardware with virtualization turned on.

1. Turn on Hyper-V in an elevated PowerShell, then reboot:
   ```powershell
   Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All
   ```
2. Install and start OpenSSH Server:
   ```powershell
   Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
   Set-Service sshd -StartupType Automatic; Start-Service sshd
   ```
3. Authorize the API's SSH key. Installing the base VM mounts disks and applies a Windows image, so the SSH user must be an administrator. For administrators, OpenSSH reads keys from `C:\ProgramData\ssh\administrators_authorized_keys`:
   ```powershell
   Add-Content C:\ProgramData\ssh\administrators_authorized_keys '<the API public key>'
   icacls C:\ProgramData\ssh\administrators_authorized_keys /inheritance:r /grant Administrators:F /grant SYSTEM:F
   ```
4. Add the machine's host key to the API's `~/.ssh/known_hosts`, for example with `ssh-keyscan <windows-ip> >> ~/.ssh/known_hosts`.

Sandboxes connect to the **Default Switch**, Hyper-V's built-in NAT with DHCP, on Windows 10 and 11. Windows Server doesn't have it. There, create an external switch, or an internal switch with your own NAT and DHCP, and set `ZOO_WINDOWS_SWITCH` to its name in the host user's environment.

If the API runs in Docker Desktop on the same Windows machine, add the server as `ssh://<user>@host.docker.internal`.

## 2. Add the server and install the base VM

In **Remote Servers**, choose **Windows** and enter `ssh://you@<windows-ip>` and the machine's address. The server card gets a **Base VM** panel.

1. Enter the path of a Windows ISO on the server, or an `https://` URL to download one. Any Windows 10/11 or Server ISO works, including the free Enterprise evaluation. With several editions on the ISO, Zoo picks Pro unless you name one under **Edition**.
2. **Install Windows** applies the image to a new disk (the progress shows on the card), then boots it. Setup runs unattended. It creates the user `zoo` with auto-login, then runs `setup.ps1` at first logon. That script turns off sleep, the lock screen and UAC prompts, installs TightVNC, and registers zoo-guest, which the install copied in from the host. Its log is `C:\zoo\setup.log` in the VM. The whole step takes 15 to 30 minutes, mostly downloads.
3. When the panel shows **ready**, use **Open screen** to install anything every sandbox should have, then **Stop**. Stopping freezes the base VM's disk as a new template.

Then create sandboxes with type **Windows**. You can start and change the base VM again at any time, even while sandboxes run. Sandboxes created after the next **Stop** get the change, and existing ones keep their own disks.

## Guest agent

zoo-guest is built into the base VM: `setup.ps1` installs it in `C:\ProgramData\zoo\bin` and registers the `zoo-guest` scheduled task, which runs at the `zoo` user's logon in the desktop session with the user's elevated token. It waits for `C:\ProgramData\zoo\guest.env`, its identity: the API's address and the sandbox's token.

- **At every boot** the host copies the VM its own `guest.env` through Hyper-V's Guest Service Interface (`zoovm push`, which is `Copy-VMFile`), with no network or account in the guest. Sealing a template removes `guest.env` from its disk, so clones never connect as the base VM.
- **Updates:** when the VM's guest differs from the API's build, the host copies the new build in as `zoo-guest.exe.new`. The guest renames itself aside, starts the new build and exits.
- **`ZOO_GUEST_REMOTE_URL` is required** for Windows sandboxes: an address of the API the VMs can reach, for example `wss://zoo.example.com/guest/connect`. The network policy always allows that host and port, unless a block rule names the same address.
- Its log is `C:\ProgramData\zoo\guest.log` in the VM.
- The API image includes the build. From a checkout, run `make guest-windows` (it lands in `guest/dist/`).

Base VMs built before zoo-guest replaced SSH have no guest: reinstall them.

## zoovm.ps1 commands

The API runs these over SSH. You can run them yourself as `& ~\.zoovm\zoovm.ps1 <command>`.

| Command | Does |
| --- | --- |
| `install <name> -Iso <path or URL> [-Edition E] [-Disk GB]` | build a VM from a Windows ISO with an unattended setup |
| `seal <name> [-Label L]` | freeze a stopped VM's disk as a new template, versioned `<label>-<UTC minute>`; the VM continues on a child disk |
| `clone <base> <name> [-Cpu N] [-Memory MB]` | a VM on a differencing disk over the base's latest template; records the template's version |
| `version <base>`, `base <name>` | the version of the base's latest template, and of the template a VM was cloned from |
| `chain <name>`, `adopt <name> -Parents T1,T2` | a stopped VM's disk and its templates, for moving; register a moved-in VM and relink its templates |
| `set <name> [-Cpu N] [-Memory MB]` | resize |
| `start <name>`, `stop <name> [-Timeout S]` | start, or shut down and turn off after the timeout |
| `ip <name>` | guest IPv4 address |
| `list`, `get <name>` | JSON state of Zoo's VMs |
| `delete <name>` | delete a VM and the templates nothing uses any more |

VMs and their disks live in `~\.zoovm\vms\<name>`, and templates in `~\.zoovm\templates`. zoovm only touches VMs it created (their Hyper-V notes say `zoo`).

## How it differs from Linux sandboxes

- `execute_command` runs PowerShell. Native exit codes are passed through, and a timeout gives exit code 124.
- File paths are Windows paths. Relative paths and `~` start at `C:\Users\zoo`.
- `installed_apps` lists Start menu apps. `binary` is the app's `.exe` name, or its app ID for Store apps. `open_app` takes a Start menu name like `Notepad`, an app ID, or a command line.
- Window ids are window handles from `windows_list`, which also returns each window's process name.
- Key names follow X11 keysyms as on Linux. Use `win` or `super` for the Windows key.
- Network policy is enforced on the host. The API runs `zoo-guest -egress` there as the `zoo-egress` scheduled task, a proxy that decides web traffic by name. A filtered VM gets Hyper-V port ACLs that let it reach only that proxy, the API, DHCP (and DNS when allowed) and addresses that ip or cidr rules allow. Its WinINet, WinHTTP and `HTTP_PROXY`/`HTTPS_PROXY` settings point at the proxy. Apps that ignore proxy settings can't reach names; reach those services with ip or cidr rules instead. Windows Firewall rules inside the VM stay as a second layer, where a block rule always beats an allow rule.
- App policy blocks an app's `.exe` through Image File Execution Options and a Store app with an AppLocker packaged-app rule. AppLocker only enforces rules on Enterprise and Education editions.
- Secrets go to `C:\Users\zoo\.zoo\env.ps1` and are loaded by `execute_command`. GUI apps don't see them.
- Backups skip `AppData\Local` and the registry hive, which Windows keeps locked.

## Limits

- The guest user is an administrator, so an agent with `shell.exec` can undo app policy and the VM's own firewall rules. It can't undo the host's port ACLs and proxy, so network policy holds.
- Clones share the base VM's computer name and machine SID. That's fine for standalone sandboxes, but don't join them to a domain.
- Windows licensing is up to you: unactivated Windows works but shows a watermark, and evaluation ISOs expire. See [docs/windows.md](../docs/windows.md#licensing).
- Templates form a chain of differencing disks, one per base VM edit. Very long chains get slower; reinstall the base VM if you've edited it many times.
- Chrome and Edge profiles are encrypted with the VM user's keys, which every clone of a base VM shares, so they only load into clones of the same base VM.
