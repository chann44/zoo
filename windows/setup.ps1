<#
Zoo guest setup for the Windows base VM. zoovm copies it to C:\zoo and Windows runs it once at the first
logon of the zoo user (FirstLogonCommands in the unattend file). It:
  - turns off sleep, the lock screen and UAC prompts (agents can't answer them);
  - installs TightVNC as a service so the API can see and drive the screen;
  - installs zoo-guest (C:\zoo\zoo-guest.exe) as a task in the desktop session at every logon. It serves every
    other tool and dials the API once the host copies its identity in (C:\ProgramData\zoo\guest.env).
The guest has no SSH server or other way in. Progress goes to C:\zoo\setup.log. When the guest connects, the base
VM shows as ready.
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

    Write-Output 'zoo-guest'
    $dir = 'C:\ProgramData\zoo'
    New-Item -ItemType Directory -Force -Path "$dir\bin" | Out-Null
    Copy-Item C:\zoo\zoo-guest.exe "$dir\bin\zoo-guest.exe" -Force
    # it waits for guest.env, which the host copies in at every boot, and reads it again on each reconnect
    $action = New-ScheduledTaskAction -Execute "$dir\bin\zoo-guest.exe" -WorkingDirectory $env:USERPROFILE `
        -Argument ('-env "{0}\guest.env" -log "{0}\guest.log"' -f $dir)
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName 'zoo-guest' -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName 'zoo-guest'

    Remove-Item C:\zoo\*.msi -Force -ErrorAction SilentlyContinue
    Set-Content -Path C:\zoo\ready -Value (Get-Date -Format o)
    Write-Output 'done'
} catch {
    Write-Output "setup failed: $($_.Exception.Message)"
    Set-Content -Path C:\zoo\failed -Value $_.Exception.Message
}
Stop-Transcript | Out-Null
