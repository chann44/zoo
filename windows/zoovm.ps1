<#
zoovm for Windows: manages Zoo's Windows sandboxes as Hyper-V VMs. The API uploads this script to
~\.zoovm on the host and runs it over SSH. Commands mirror macos/zoovm.

Every sandbox VM boots from a differencing disk on top of a read-only template of the base VM, so clones
are instant and the base VM can be edited while sandboxes run. `seal` turns the base VM's current disk into
a new template.
#>
param(
    [Parameter(Position = 0)][string]$Command,
    [Parameter(Position = 1)][string]$Name,
    [Parameter(Position = 2)][string]$Target,
    [string]$Iso,
    [string]$Edition,
    [string]$Label = 'windows',
    [string]$Parents = '',
    [string]$Source,
    [string]$Destination,
    [string]$SwitchName = $(if ($env:ZOO_WINDOWS_SWITCH) { $env:ZOO_WINDOWS_SWITCH } else { 'Default Switch' }),
    [string]$User = 'zoo',
    [int]$Cpu = 4,
    [int]$Memory = 8192,
    [int]$Disk = 64,
    [int]$Width = 1280,
    [int]$Height = 800,
    [int]$Timeout = 60
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Root = Join-Path $env:USERPROFILE '.zoovm'
$Vms = Join-Path $Root 'vms'
$Templates = Join-Path $Root 'templates'
$Marker = 'zoo'

function Fail([string]$message) { throw $message }

function VmDir([string]$n) { Join-Path $Vms $n }

function Get-ZooVM([string]$n) {
    Get-VM -Name $n -ErrorAction SilentlyContinue | Where-Object Notes -eq $Marker
}

function Require-VM([string]$n) {
    $vm = Get-ZooVM $n
    if (-not $vm) { Fail "no VM named $n" }
    $vm
}

function State($vm) {
    if ($vm.State -in 'Off', 'Saved') { 'stopped' } else { 'running' }
}

function Latest-Template([string]$base) {
    Get-ChildItem -Path $Templates -Filter "$base-*.vhdx" -ErrorAction SilentlyContinue |
        Where-Object { $_.BaseName -match '-\d{14}$' } | Sort-Object Name | Select-Object -Last 1
}

# A template's version, `<label>-<UTC stamp>`: written next to it by `seal`, so every sandbox records the template
# it was cloned from.
function Template-Version($template) {
    $file = [IO.Path]::ChangeExtension($template.FullName, '.version')
    if (Test-Path -LiteralPath $file) { return (Get-Content -LiteralPath $file -Raw).Trim() }
    "windows-" + ($template.BaseName -replace '^.*-(\d{12})\d{2}$', '$1')
}

function New-ZooVM([string]$n, [string]$vhd) {
    if (-not (Get-VMSwitch -Name $SwitchName -ErrorAction SilentlyContinue)) {
        Fail "Hyper-V switch '$SwitchName' not found; set ZOO_WINDOWS_SWITCH to a switch with DHCP"
    }
    $vm = New-VM -Name $n -Generation 2 -MemoryStartupBytes ([int64]$Memory * 1MB) -VHDPath $vhd -SwitchName $SwitchName -Path $Vms
    Set-VM -VM $vm -ProcessorCount $Cpu -StaticMemory -AutomaticCheckpointsEnabled $false `
        -AutomaticStartAction Nothing -AutomaticStopAction ShutDown -CheckpointType Disabled -Notes $Marker
    Set-VMFirmware -VM $vm -EnableSecureBoot On -SecureBootTemplate MicrosoftWindows
    try { Set-VMVideo -VM $vm -ResolutionType Single -HorizontalResolution $Width -VerticalResolution $Height } catch {}
    Enable-VMIntegrationService -VM $vm -Name 'Guest Service Interface' -ErrorAction SilentlyContinue
    $vm
}

function Stop-ZooVM($vm, [int]$seconds) {
    if ($vm.State -eq 'Saved') { Remove-VMSavedState -VM $vm; return }
    if ($vm.State -eq 'Off') { return }
    $job = Stop-VM -VM $vm -Force -AsJob
    if (-not (Wait-Job $job -Timeout $seconds)) { Stop-Job $job }
    Remove-Job $job -Force
    if ((Get-VM -Id $vm.Id).State -ne 'Off') { Stop-VM -VM $vm -TurnOff -Force }
}

function Remove-UnusedTemplates {
    $latest = @{}
    $used = @{}
    foreach ($t in Get-ChildItem -Path $Templates -Filter '*.vhdx' -ErrorAction SilentlyContinue) {
        # templates moved in from another server only stay while a VM uses them
        if ($t.Name -like 'moved-*') { continue }
        $base = $t.BaseName -replace '-\d{14}$', ''
        if (-not $latest[$base] -or $t.Name -gt $latest[$base].Name) { $latest[$base] = $t }
    }
    $disks = @(Get-VM | Where-Object Notes -eq $Marker | Get-VMHardDiskDrive | ForEach-Object Path)
    $disks += @($latest.Values | ForEach-Object FullName)
    foreach ($d in $disks) {
        $parent = $d
        while ($parent) {
            $used[$parent.ToLower()] = $true
            $parent = (Get-VHD -Path $parent -ErrorAction SilentlyContinue).ParentPath
        }
    }
    foreach ($t in Get-ChildItem -Path $Templates -Filter '*.vhdx' -ErrorAction SilentlyContinue) {
        if (-not $used[$t.FullName.ToLower()]) {
            $t.IsReadOnly = $false
            Remove-Item $t.FullName -Force
        }
    }
    foreach ($v in Get-ChildItem -Path $Templates -Filter '*.version' -ErrorAction SilentlyContinue) {
        if (-not (Test-Path -LiteralPath ([IO.Path]::ChangeExtension($v.FullName, '.vhdx')))) { Remove-Item $v.FullName -Force }
    }
}

# Removes the guest's identity (guest.env) from a stopped VM's disk, so the clones of a template never connect as
# the VM it was sealed from. The API copies each VM its own at every boot (`push`).
function Clear-GuestEnv([string]$vhd) {
    $disk = Mount-VHD -Path $vhd -PassThru | Get-Disk
    try {
        foreach ($p in Get-Partition -DiskNumber $disk.Number | Where-Object Type -eq 'Basic') {
            $added = -not $p.DriveLetter
            if ($added) { $p | Add-PartitionAccessPath -AssignDriveLetter; $p = $p | Get-Partition }
            Remove-Item -Force -ErrorAction SilentlyContinue "$($p.DriveLetter):\ProgramData\zoo\guest.env"
            if ($added) { $p | Remove-PartitionAccessPath -AccessPath "$($p.DriveLetter):\" }
        }
    } finally {
        Dismount-VHD -Path $vhd
    }
}

function Run([string]$exe, [string[]]$arguments) {
    # Lets the tool write its progress straight to the log instead of through PowerShell's pipeline.
    $process = Start-Process -FilePath $exe -ArgumentList $arguments -NoNewWindow -PassThru
    $null = $process.Handle  # keeps the exit code readable after the process ends
    $process.WaitForExit()
    $process.ExitCode
}

function Unattend([string]$arch, [string]$password) {
    $p = [Security.SecurityElement]::Escape($password)
    $shell = "processorArchitecture=`"$arch`" publicKeyToken=`"31bf3856ad364e35`" language=`"neutral`" versionScope=`"nonSxS`""
    @"
<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
  <settings pass="specialize">
    <component name="Microsoft-Windows-Shell-Setup" $shell>
      <ComputerName>ZOO</ComputerName>
      <TimeZone>UTC</TimeZone>
    </component>
  </settings>
  <settings pass="oobeSystem">
    <component name="Microsoft-Windows-International-Core" $shell>
      <InputLocale>en-US</InputLocale>
      <SystemLocale>en-US</SystemLocale>
      <UILanguage>en-US</UILanguage>
      <UserLocale>en-US</UserLocale>
    </component>
    <component name="Microsoft-Windows-Shell-Setup" $shell>
      <OOBE>
        <HideEULAPage>true</HideEULAPage>
        <HideOEMRegistrationScreen>true</HideOEMRegistrationScreen>
        <HideOnlineAccountScreens>true</HideOnlineAccountScreens>
        <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
        <HideLocalAccountScreen>true</HideLocalAccountScreen>
        <ProtectYourPC>3</ProtectYourPC>
      </OOBE>
      <UserAccounts>
        <LocalAccounts>
          <LocalAccount wcm:action="add">
            <Name>$User</Name>
            <Group>Administrators</Group>
            <Password><Value>$p</Value><PlainText>true</PlainText></Password>
          </LocalAccount>
        </LocalAccounts>
      </UserAccounts>
      <AutoLogon>
        <Enabled>true</Enabled>
        <Username>$User</Username>
        <Password><Value>$p</Value><PlainText>true</PlainText></Password>
        <LogonCount>999999</LogonCount>
      </AutoLogon>
      <FirstLogonCommands>
        <SynchronousCommand wcm:action="add">
          <Order>1</Order>
          <CommandLine>powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\zoo\setup.ps1</CommandLine>
          <Description>Zoo guest setup</Description>
        </SynchronousCommand>
      </FirstLogonCommands>
    </component>
  </settings>
</unattend>
"@
}

function Install([string]$n) {
    if (Get-ZooVM $n) { Fail "a VM named $n already exists" }
    if (-not $Iso) { Fail 'an ISO path or URL is required (-Iso)' }
    $dir = VmDir $n
    New-Item -ItemType Directory -Force -Path $dir, $Templates | Out-Null

    $image = $Iso
    if ($Iso -match '^https?://') {
        $image = Join-Path $Root 'windows.iso'
        Write-Output 'downloading Windows'
        $code = Run 'curl.exe' @('-fL', '--progress-bar', '-o', "`"$image`"", "`"$Iso`"")
        if ($code -ne 0) { Fail "download failed (curl exit $code)" }
    }
    if (-not (Test-Path $image)) { Fail "ISO not found: $image" }

    Write-Output 'preparing disk'
    $mounted = Mount-DiskImage -ImagePath (Resolve-Path $image).Path -PassThru
    $vhd = Join-Path $dir 'disk.vhdx'
    try {
        $letter = ($mounted | Get-Volume).DriveLetter
        $wim = @("${letter}:\sources\install.wim", "${letter}:\sources\install.esd") | Where-Object { Test-Path $_ } | Select-Object -First 1
        if (-not $wim) { Fail 'the ISO has no sources\install.wim or install.esd' }
        $images = @(Get-WindowsImage -ImagePath $wim)
        if ($Edition) {
            $chosen = $images | Where-Object ImageName -like "*$Edition*" | Select-Object -First 1
        } else {
            $chosen = $images | Where-Object ImageName -match ' Pro$' | Select-Object -First 1
            if (-not $chosen) { $chosen = $images[0] }
        }
        if (-not $chosen) { Fail "no edition matching '$Edition' (has: $(($images | ForEach-Object ImageName) -join ', '))" }
        Write-Output "using $($chosen.ImageName)"

        New-VHD -Path $vhd -SizeBytes ([int64]$Disk * 1GB) -Dynamic | Out-Null
        $mountedDisk = Mount-VHD -Path $vhd -PassThru | Get-Disk
        try {
            Initialize-Disk -Number $mountedDisk.Number -PartitionStyle GPT
            $efi = New-Partition -DiskNumber $mountedDisk.Number -Size 260MB -GptType '{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}'
            $efi | Format-Volume -FileSystem FAT32 -Force | Out-Null
            $efi | Add-PartitionAccessPath -AssignDriveLetter
            $efi = $efi | Get-Partition
            New-Partition -DiskNumber $mountedDisk.Number -Size 16MB -GptType '{e3c9e316-0b5c-4db8-817d-f92df00215ae}' | Out-Null
            $os = New-Partition -DiskNumber $mountedDisk.Number -UseMaximumSize -AssignDriveLetter
            $os | Format-Volume -FileSystem NTFS -Force | Out-Null
            $os = $os | Get-Partition
            $w = "$($os.DriveLetter):"
            $s = "$($efi.DriveLetter):"

            Write-Output 'applying Windows image'
            $code = Run 'dism.exe' @('/Apply-Image', "/ImageFile:$wim", "/Index:$($chosen.ImageIndex)", "/ApplyDir:$w\")
            if ($code -ne 0) { Fail "dism failed with exit code $code" }
            & bcdboot.exe "$w\Windows" /s $s /f UEFI | Out-Null
            if ($LASTEXITCODE -ne 0) { Fail "bcdboot failed with exit code $LASTEXITCODE" }

            $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'amd64' }
            $password = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 20 | ForEach-Object { [char]$_ })
            New-Item -ItemType Directory -Force -Path "$w\Windows\Panther", "$w\zoo" | Out-Null
            [IO.File]::WriteAllText("$w\Windows\Panther\unattend.xml", (Unattend $arch $password))
            $guest = Join-Path $Root 'bin\zoo-guest-vm.exe'
            if (-not (Test-Path -LiteralPath $guest)) { Fail "zoo-guest is missing at $guest" }
            Copy-Item (Join-Path $Root 'setup.ps1'), $guest "$w\zoo\"
            $efi | Remove-PartitionAccessPath -AccessPath "$s\"
        } finally {
            Dismount-VHD -Path $vhd
        }
    } finally {
        Dismount-DiskImage -ImagePath $mounted.ImagePath | Out-Null
    }

    Write-Output 'first boot'
    New-ZooVM $n $vhd | Start-VM
    Write-Output 'installed'
}

try {
switch ($Command) {
    'list' {
        $rows = @(Get-VM | Where-Object Notes -eq $Marker | ForEach-Object { @{ name = $_.Name; state = (State $_) } })
        ConvertTo-Json -InputObject $rows -Compress
    }
    'get' {
        $vm = Require-VM $Name
        ConvertTo-Json -Compress @{ name = $vm.Name; state = (State $vm); cpus = $vm.ProcessorCount; memory_mb = $vm.MemoryStartup / 1MB }
    }
    'install' { Install $Name }
    'clone' {
        # zoovm clone <base> <name>: a VM on a differencing disk over the base's latest template.
        if (Get-ZooVM $Target) { Fail "a VM named $Target already exists" }
        $template = Latest-Template $Name
        if (-not $template) { Fail "the base VM $Name has no template yet: stop it once its setup is done" }
        $dir = VmDir $Target
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $vhd = Join-Path $dir 'disk.vhdx'
        New-VHD -Path $vhd -ParentPath $template.FullName -Differencing | Out-Null
        Set-Content -Path (Join-Path $dir 'zoo-base') -Value (Template-Version $template)
        New-ZooVM $Target $vhd | Out-Null
    }
    'version' {
        # the version of the base VM's latest template, which the next clone gets
        $template = Latest-Template $Name
        if (-not $template) { Fail "the base VM $Name has no template yet" }
        Template-Version $template
    }
    'base' {
        # the template version a VM was cloned from; nothing for clones older than versions
        $file = Join-Path (VmDir $Name) 'zoo-base'
        if (Test-Path -LiteralPath $file) { (Get-Content -LiteralPath $file -Raw).Trim() }
    }
    'chain' {
        # a stopped VM's disk, then each template under it: what moving it to another server copies
        $vm = Require-VM $Name
        if ($vm.State -ne 'Off') { Fail "stop $Name before moving it" }
        $rows = @()
        $path = (Get-VMHardDiskDrive -VM $vm | Select-Object -First 1).Path
        while ($path) {
            $rows += @{ name = (Split-Path $path -Leaf); path = $path; size = (Get-Item -LiteralPath $path).Length }
            $path = (Get-VHD -Path $path).ParentPath
        }
        ConvertTo-Json -Compress -InputObject $rows
    }
    'adopt' {
        # zoovm adopt <name> -Parents t1,t2: a VM over vms\<name>\disk.vhdx, copied in with its templates t1 (its
        # parent), t2 (t1's parent) and so on, which are relinked to where they are on this server
        $dir = VmDir $Name
        $vhd = Join-Path $dir 'disk.vhdx'
        if (-not (Test-Path -LiteralPath $vhd)) { Fail "no disk at $vhd" }
        $chain = @($vhd) + @($Parents.Split(',') | Where-Object { $_ } | ForEach-Object { Join-Path $Templates $_ })
        for ($i = $chain.Count - 2; $i -ge 0; $i--) {
            $item = Get-Item -LiteralPath $chain[$i]
            $item.IsReadOnly = $false
            Set-VHD -Path $chain[$i] -ParentPath $chain[$i + 1]
            $item.IsReadOnly = $i -gt 0
        }
        if (-not (Get-ZooVM $Name)) { New-ZooVM $Name $vhd | Out-Null }
    }
    'seal' {
        # Freezes the base VM's disk as a new read-only template and continues the base on a child of it.
        $vm = Require-VM $Name
        if ($vm.State -ne 'Off') { Fail "$Name must be stopped to seal it" }
        New-Item -ItemType Directory -Force -Path $Templates | Out-Null
        $drive = Get-VMHardDiskDrive -VM $vm | Select-Object -First 1
        Clear-GuestEnv $drive.Path
        $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss')
        $template = Join-Path $Templates "$Name-$stamp.vhdx"
        Move-Item -Path $drive.Path -Destination $template
        (Get-Item $template).IsReadOnly = $true
        Set-Content -Path ([IO.Path]::ChangeExtension($template, '.version')) -Value "$Label-$($stamp.Substring(0, 12))"
        New-VHD -Path $drive.Path -ParentPath $template -Differencing | Out-Null
        $drive | Set-VMHardDiskDrive -Path $drive.Path
        Remove-UnusedTemplates
    }
    'push' {
        # zoovm push <name> -Source <file on the host> -Destination <path in the guest>: copies a file into a running
        # VM through Hyper-V's Guest Service Interface, with no network or account in the guest
        $vm = Require-VM $Name
        Copy-VMFile -VM $vm -SourcePath $Source -DestinationPath $Destination -FileSource Host -CreateFullPath -Force
    }
    'sealed' { if (-not (Latest-Template $Name)) { exit 1 } }
    'set' {
        $vm = Require-VM $Name
        Set-VM -VM $vm -ProcessorCount $Cpu -MemoryStartupBytes ([int64]$Memory * 1MB)
    }
    'start' {
        $vm = Require-VM $Name
        if ($vm.State -ne 'Running') { Start-VM -VM $vm }
    }
    'stop' {
        $vm = Get-ZooVM $Name
        if ($vm) { Stop-ZooVM $vm $Timeout }
    }
    'ip' {
        $vm = Require-VM $Name
        $ip = (Get-VMNetworkAdapter -VM $vm).IPAddresses |
            Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' -and $_ -notlike '169.254.*' } | Select-Object -First 1
        if (-not $ip) { Fail "$Name has no IPv4 address yet" }
        $ip
    }
    'delete' {
        $vm = Get-ZooVM $Name
        if ($vm) {
            Stop-ZooVM $vm 0
            Remove-VM -VM $vm -Force
        }
        Remove-Item -Recurse -Force -Path (VmDir $Name) -ErrorAction SilentlyContinue
        Remove-UnusedTemplates
    }
    'installing' {
        $file = Join-Path $Root 'install.pid'
        if (-not (Test-Path $file)) { exit 1 }
        if (-not (Get-Process -Id ([int](Get-Content $file)) -ErrorAction SilentlyContinue)) { exit 1 }
    }
    'spawn' {
        # Runs `zoovm install` detached from the SSH session (OpenSSH ends a session's processes when it closes),
        # logging to ~\.zoovm\install.log.
        New-Item -ItemType Directory -Force -Path $Root | Out-Null
        $log = Join-Path $Root 'install.log'
        $self = Join-Path $Root 'zoovm.ps1'
        $quote = { param($v) "'" + ($v -replace "'", "''") + "'" }
        $script = "& $(& $quote $self) install $(& $quote $Name) -Iso $(& $quote $Iso) -User $(& $quote $User) -Disk $Disk"
        if ($Edition) { $script += " -Edition $(& $quote $Edition)" }
        $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
        $line = "cmd.exe /c powershell.exe -NoProfile -ExecutionPolicy Bypass -EncodedCommand $encoded > `"$log`" 2>&1"
        $result = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $line; CurrentDirectory = $Root }
        if ($result.ReturnValue -ne 0) { Fail "could not start the installer (error $($result.ReturnValue))" }
        Set-Content -Path (Join-Path $Root 'install.pid') -Value $result.ProcessId
    }
    default { Fail 'usage: zoovm list|get|install|clone|version|base|chain|adopt|push|seal|sealed|set|start|stop|ip|delete|installing|spawn' }
}
} catch {
    [Console]::Error.WriteLine("zoovm: $($_.Exception.Message)")
    exit 1
}
