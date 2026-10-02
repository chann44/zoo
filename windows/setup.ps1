<#
Zoo guest setup for the Windows base VM. zoovm copies it to C:\zoo and Windows runs it once at the first
logon of the zoo user (FirstLogonCommands in the unattend file). It:
  - turns off sleep, the lock screen and UAC prompts (agents can't answer them);
  - installs OpenSSH Server and authorizes the API's key (C:\zoo\authorized_keys);
  - installs TightVNC as a service so the API can see and drive the screen;
  - registers C:\zoo\agent.ps1 to run in the desktop session at every logon (window and app tools).
Progress goes to C:\zoo\setup.log. When it finishes, the API can reach the guest and the base VM shows as ready.
#>
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Start-Transcript -Path C:\zoo\setup.log -Append | Out-Null
$TightVnc = 'https://www.tightvnc.com/download/2.8.85/tightvnc-2.8.85-gpl-setup-64bit.msi'

function Download([string]$url, [string]$path) {
    for ($i = 0; $i -lt 30; $i++) {
        & curl.exe -fsSL -o $path $url
        if ($LASTEXITCODE -eq 0) { return }
        Start-Sleep -Seconds 10
    }
    throw "could not download $url"
}

function Set-Reg([string]$path, [string]$name, $value, [string]$type = 'DWord') {
    New-Item -Path $path -Force -ErrorAction SilentlyContinue | Out-Null
    Set-ItemProperty -Path $path -Name $name -Value $value -Type $type
}

try {
    Write-Output 'power, lock screen and UAC'
    powercfg /change monitor-timeout-ac 0
    powercfg /change standby-timeout-ac 0
    powercfg /hibernate off
    Set-Reg 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Personalization' 'NoLockScreen' 1
    Set-Reg 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' 'ConsentPromptBehaviorAdmin' 0
    Set-Reg 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' 'PromptOnSecureDesktop' 0
    Set-Reg 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' 'InactivityTimeoutSecs' 0
    Set-Reg 'HKCU:\Control Panel\Desktop' 'ScreenSaveActive' '0' 'String'
    Set-Reg 'HKLM:\SOFTWARE\Policies\Microsoft\Edge' 'HideFirstRunExperience' 1
    Set-Reg 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\CloudContent' 'DisableWindowsConsumerFeatures' 1
    Set-Reg 'HKCU:\Software\Microsoft\Windows\CurrentVersion\UserProfileEngagement' 'ScoobeSystemSettingEnabled' 0

    Write-Output 'OpenSSH Server'
    if (-not (Get-Service sshd -ErrorAction SilentlyContinue)) {
        try {
            Add-WindowsCapability -Online -Name 'OpenSSH.Server~~~~0.0.1.0' | Out-Null
        } catch {
            Write-Output "capability install failed ($($_.Exception.Message)), using the Win32-OpenSSH MSI"
            $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'ARM64' } else { 'Win64' }
            $release = Invoke-RestMethod 'https://api.github.com/repos/PowerShell/Win32-OpenSSH/releases/latest'
            $asset = $release.assets | Where-Object name -match "$arch.*\.msi$" | Select-Object -First 1
            Download $asset.browser_download_url C:\zoo\openssh.msi
            Start-Process msiexec.exe -ArgumentList '/i', 'C:\zoo\openssh.msi', '/quiet', '/norestart' -Wait
        }
    }
    Set-Service sshd -StartupType Automatic
    Start-Service sshd
    $keys = 'C:\ProgramData\ssh\administrators_authorized_keys'
    Copy-Item C:\zoo\authorized_keys $keys -Force
    # Administrators and SYSTEM by SID, since group names are localized.
    icacls.exe $keys /inheritance:r /grant '*S-1-5-32-544:F' /grant '*S-1-5-18:F' | Out-Null
    if (-not (Get-NetFirewallRule -Name 'zoo-ssh' -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name 'zoo-ssh' -DisplayName 'Zoo SSH' -Direction Inbound -Protocol TCP -LocalPort 22 -Action Allow | Out-Null
    }

    Write-Output 'TightVNC'
    if (-not (Get-Service tvnserver -ErrorAction SilentlyContinue)) {
        # The API sets a per-sandbox password on every boot; this one only covers the base VM's first start.
        $password = -join ((97..122) | Get-Random -Count 8 | ForEach-Object { [char]$_ })
        Download $TightVnc C:\zoo\tightvnc.msi
        $properties = @(
            'ADDLOCAL=Server', 'SERVER_REGISTER_AS_SERVICE=1', 'SERVER_ADD_FIREWALL_EXCEPTION=0',
            'SET_USEVNCAUTHENTICATION=1', 'VALUE_OF_USEVNCAUTHENTICATION=1', 'SET_PASSWORD=1', "VALUE_OF_PASSWORD=$password",
            'SET_ACCEPTHTTPCONNECTIONS=1', 'VALUE_OF_ACCEPTHTTPCONNECTIONS=0', 'SET_REMOVEWALLPAPER=1', 'VALUE_OF_REMOVEWALLPAPER=0',
            'SET_USECONTROLAUTHENTICATION=1', 'VALUE_OF_USECONTROLAUTHENTICATION=0'
        )
        Start-Process msiexec.exe -ArgumentList (@('/i', 'C:\zoo\tightvnc.msi', '/quiet', '/norestart') + $properties) -Wait
    }
    Set-Service tvnserver -StartupType Automatic
    Start-Service tvnserver
    if (-not (Get-NetFirewallRule -Name 'zoo-vnc' -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name 'zoo-vnc' -DisplayName 'Zoo VNC' -Direction Inbound -Protocol TCP -LocalPort 5900 `
            -RemoteAddress LocalSubnet -Action Allow | Out-Null
    }

    Write-Output 'desktop agent'
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File C:\zoo\agent.ps1'
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName 'zoo-agent' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName 'zoo-agent'

    Remove-Item C:\zoo\*.msi -Force -ErrorAction SilentlyContinue
    Set-Content -Path C:\zoo\ready -Value (Get-Date -Format o)
    Write-Output 'done'
} catch {
    Write-Output "setup failed: $($_.Exception.Message)"
    Set-Content -Path C:\zoo\failed -Value $_.Exception.Message
}
Stop-Transcript | Out-Null
