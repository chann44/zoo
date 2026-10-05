<#
Prepares a Windows machine to run sandboxes for a Zoo control plane, then prints a join line to paste into the
dashboard. Servers > Add server > Windows shows this command with -Key and -ControlPlane filled in:

  powershell -ExecutionPolicy Bypass -c "& ([scriptblock]::Create((irm <release>/install-node.ps1))) -Key '<key>' -ControlPlane '<url>'"

It checks the machine first (edition, Hyper-V, disk, memory, the control plane) and changes nothing if a check
fails. Then it turns on Hyper-V and OpenSSH Server and authorizes the control plane's SSH key. Run it in an
elevated PowerShell. With Docker Desktop installed, the machine also runs Linux sandboxes.
#>
param(
    [Parameter(Mandatory)][string]$Key,
    [string]$ControlPlane = '',
    [switch]$Check
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Docs = 'https://github.com/chann44/zoo#add-a-server'
$script:Failed = $false

function Ok([string]$m) { Write-Host '  ok    ' -ForegroundColor Green -NoNewline; Write-Host $m }
function Note([string]$m) { Write-Host '  note  ' -ForegroundColor Yellow -NoNewline; Write-Host $m }
function Fail([string]$m) { Write-Host '  fail  ' -ForegroundColor Red -NoNewline; Write-Host $m; $script:Failed = $true }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { throw 'run this in an elevated PowerShell (Run as administrator)' }

Write-Host '==> Checking this machine' -ForegroundColor White
$os = Get-CimInstance Win32_OperatingSystem
if ($os.Caption -match 'Home') { Fail "$($os.Caption): Hyper-V needs Windows Pro, Enterprise, Education or Server" }
else { Ok $os.Caption }
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$hypervisor = (Get-CimInstance Win32_ComputerSystem).HypervisorPresent
if ($hypervisor -or $cpu.VirtualizationFirmwareEnabled) { Ok 'virtualization is on' }
else { Fail 'virtualization is off in the firmware: turn on Intel VT-x or AMD-V in the BIOS/UEFI settings' }
$hyperv = (Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V-All).State
if ($hyperv -eq 'Enabled') { Ok 'Hyper-V is on' } else { Note 'Hyper-V is off; it will be turned on (needs a restart)' }
$free = [math]::Floor((Get-PSDrive C).Free / 1GB)
if ($free -ge 80) { Ok "$free GB free on C:" } else { Fail "$free GB free on C:, needs 80 GB for the base VM and sandboxes" }
$memory = [math]::Floor($os.TotalVisibleMemorySize / 1MB)
if ($memory -lt 8) { Fail "$memory GB of memory, needs 8 GB" }
elseif ($memory -lt 16) { Note "$memory GB of memory; 16 GB or more runs more sandboxes at once" }
else { Ok "$memory GB of memory" }
if (-not $ControlPlane) { Note 'no -ControlPlane given, skipped the reachability check' }
else {
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 "$($ControlPlane.TrimEnd('/'))/healthz" | Out-Null; Ok "control plane reachable at $ControlPlane" }
    catch { Note "can't reach $ControlPlane from here; the control plane must still reach this machine over SSH" }
}
$docker = [bool](Get-Command docker -ErrorAction SilentlyContinue)
if ($docker) { Ok 'Docker found: this machine can also run Linux sandboxes' }
else { Note 'no Docker: install Docker Desktop to also run Linux sandboxes here' }
if ($script:Failed) { throw "pre-flight checks failed, nothing was changed. See $Docs" }
if ($Check) { Write-Host '==> Pre-flight checks passed'; return }

if ($hyperv -ne 'Enabled') {
    Write-Host '==> Turning on Hyper-V'
    Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -All -NoRestart | Out-Null
    Write-Host 'Restart Windows, then run this command again to finish.' -ForegroundColor Yellow
    return
}

Write-Host '==> Setting up OpenSSH Server'
if ((Get-WindowsCapability -Online -Name 'OpenSSH.Server*').State -ne 'Installed') {
    Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0' | Out-Null
}
Set-Service sshd -StartupType Automatic
Start-Service sshd
if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server' -Protocol TCP -LocalPort 22 `
        -Direction Inbound -Action Allow | Out-Null
}
# Installing the base VM mounts disks and applies a Windows image, so the control plane signs in as an
# administrator, whose keys OpenSSH reads from administrators_authorized_keys
$keys = 'C:\ProgramData\ssh\administrators_authorized_keys'
if (-not (Test-Path $keys) -or -not (Select-String -Path $keys -SimpleMatch $Key -Quiet)) { Add-Content $keys $Key }
icacls $keys /inheritance:r /grant Administrators:F /grant SYSTEM:F | Out-Null

$route = Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric | Select-Object -First 1
$ip = (Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $route.InterfaceIndex | Select-Object -First 1).IPAddress
$hostKey = ((Get-Content C:\ProgramData\ssh\ssh_host_ed25519_key.pub) -split ' ')[0..1] -join ' '
$join = [ordered]@{
    platform = 'windows'; name = $env:COMPUTERNAME; docker_url = "ssh://$env:USERNAME@$ip"; bind_address = $ip
    host_key = $hostKey
} | ConvertTo-Json -Compress
$line = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($join))
$runs = if ($docker) { 'Windows and Linux sandboxes' } else { 'Windows sandboxes' }

Write-Host '==> This machine is ready' -ForegroundColor White
Write-Host @"

  It can run: $runs

  In the dashboard, open Servers > Add server and paste this join line:

  zoo-join:$line

  Then build its base Windows VM from the server's page, from a Windows ISO you supply (or the evaluation ISO).
"@
