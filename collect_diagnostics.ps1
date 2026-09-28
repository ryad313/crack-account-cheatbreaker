param([string]$PatcherPath = '', [string]$OutputPath = '')

$ErrorActionPreference = 'Stop'
$report = New-Object System.Collections.Generic.List[string]
$cbRoot = Join-Path $env:APPDATA 'CheatBreaker'
$minecraft = Join-Path $env:APPDATA '.minecraft'
$downloads = Join-Path $cbRoot 'downloads'
$settingsFile = Join-Path $cbRoot 'launcher\settings.json'
$settings = $null
if (Test-Path -LiteralPath $settingsFile) {
    try {
        $settings = Get-Content -LiteralPath $settingsFile -Raw | ConvertFrom-Json
        if ($settings.downloads_dir) { $downloads = [string]$settings.downloads_dir }
        if ($settings.game_dir) { $minecraft = [string]$settings.game_dir }
    } catch { $report.Add('Settings could not be parsed: ' + $_.Exception.Message) }
}

function Protect-Text([string]$Text) {
    $Text = [regex]::Replace($Text, '(?i)(--[\w-]*(?:token|secret|password)[\w-]*\s+)("[^"]*"|\S+)', '$1[REDACTED]')
    $Text = [regex]::Replace($Text, '(?i)("[^"]*(?:token|secret|password)[^"]*"\s*:\s*")[^"]*', '$1[REDACTED]')
    $Text = [regex]::Replace($Text, '(?i)((?:access_token|refresh_token|token|secret|password|authorization)=)[^&\s]+', '$1[REDACTED]')
    $Text = [regex]::Replace($Text, '(?i)Bearer\s+\S+', 'Bearer [REDACTED]')
    $Text = [regex]::Replace($Text, 'gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}', '[REDACTED]')
    $Text = [regex]::Replace($Text, 'eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', '[REDACTED]')
    if ($env:USERPROFILE) { $Text = $Text.Replace($env:USERPROFILE, '%USERPROFILE%') }
    return $Text
}

function Add-Section([string]$Title) { $report.Add("`r`n=== $Title ===") }

function Add-Log([string]$Path, [int]$Tail = 180) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return }
    $item = Get-Item -LiteralPath $Path
    Add-Section ((Protect-Text $Path) + ' | modified ' + $item.LastWriteTime.ToString('s'))
    try {
        # Read from the beginning so a tail never starts inside a launch command.
        $clean = New-Object System.Collections.Generic.List[string]
        $skip = $false
        foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
            if ($line -match '(?i)Launching with Arguments|^Command Line:|^jvm_args:|^java_command:') {
                $skip = $true
                $clean.Add('[Launch arguments omitted]')
                continue
            }
            if ($skip) {
                if ($line -match '^\[(LOG|DEBUG|ERROR|WARN|INFO)\]|^\s*(Stack:|Current thread|VM Arguments|Environment Variables|---------------)') {
                    $skip = $false
                } else { continue }
            }
            # Do not include environment-variable dumps in JVM crash reports.
            if ($line -match '(?i)^Environment Variables:') { break }
            $clean.Add($line)
        }
        $report.Add((Protect-Text (($clean | Select-Object -Last $Tail) -join "`r`n")))
    } catch { $report.Add('Cannot read log: ' + $_.Exception.Message) }
}

Add-Section 'System'
$os = Get-CimInstance Win32_OperatingSystem
$report.Add(('Windows: {0}; version: {1}; architecture: {2}; RAM MB: {3}' -f $os.Caption, $os.Version, $os.OSArchitecture, [math]::Round($os.TotalVisibleMemorySize / 1024)))
$report.Add('PowerShell: ' + $PSVersionTable.PSVersion)
$report.Add('Time: ' + (Get-Date -Format o))
$report.Add('Downloads: ' + (Protect-Text $downloads))
$report.Add('Game directory: ' + (Protect-Text $minecraft))

Add-Section 'Launch settings (safe fields only)'
foreach ($key in @('version','ram','pre_allocate_memory','client_branch','client_automatic_branch','launch_action','crash_action','close_action','jre_dir')) {
    if ($null -ne $settings -and $null -ne $settings.$key) {
        $report.Add($key + ': ' + (Protect-Text ([string]$settings.$key)))
    }
}
foreach ($key in @('jvm_args','wrapper_command','pre_launch_command','post_exit_command')) {
    $report.Add($key + ' configured: ' + [bool]($null -ne $settings -and $settings.$key))
}

Add-Section 'Account summary (no names or credentials)'
$accountsFile = Join-Path $env:APPDATA '.minecraft\cheatbreaker_accounts.json'
if (Test-Path -LiteralPath $accountsFile) {
    try {
        $store = Get-Content -LiteralPath $accountsFile -Raw | ConvertFrom-Json
        $all = @($store.accounts.PSObject.Properties)
        $offline = @($all | Where-Object { $_.Value.accessToken -eq '0' })
        $active = $all | Where-Object { $_.Name -eq $store.activeAccountLocalId }
        $report.Add(('Accounts: {0}; offline: {1}; active is offline: {2}' -f $all.Count, $offline.Count, [bool]($active.Value.accessToken -eq '0')))
    } catch { $report.Add('Account store could not be parsed.') }
} else { $report.Add('Account store missing.') }

Add-Section 'Processes (command lines omitted)'
Get-CimInstance Win32_Process -Filter "Name='CheatBreaker.exe' OR Name='javaw.exe' OR Name='java.exe'" | ForEach-Object {
    $report.Add(('{0} PID={1} Path={2}' -f $_.Name, $_.ProcessId, (Protect-Text $_.ExecutablePath)))
}

Add-Section 'Bundled Java runtimes'
$javaRoots = @((Join-Path $cbRoot 'jres'), (Join-Path $cbRoot 'jre'))
if ($null -ne $settings -and $settings.jre_dir) { $javaRoots += [string]$settings.jre_dir }
foreach ($root in ($javaRoots | Select-Object -Unique)) {
    if (Test-Path -LiteralPath $root) {
        foreach ($file in Get-ChildItem -LiteralPath $root -Filter 'release' -File -Recurse -Depth 3 -ErrorAction SilentlyContinue) {
            $report.Add('Runtime: ' + (Protect-Text $file.DirectoryName))
            Get-Content -LiteralPath $file.FullName | Where-Object { $_ -match '^(JAVA_VERSION|JAVA_RUNTIME_VERSION|IMPLEMENTOR|OS_ARCH)=' } | ForEach-Object { $report.Add($_) }
        }
    }
}

Add-Section 'Launcher archive'
$resources = Join-Path $env:LOCALAPPDATA 'Programs\cheatbreaker\resources'
foreach ($name in @('app.asar', 'app.asar.ORIGINAL')) {
    $path = Join-Path $resources $name
    if (Test-Path -LiteralPath $path) {
        $item = Get-Item -LiteralPath $path
        $report.Add(('{0} size={1} SHA256={2}' -f $name, $item.Length, (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash))
    } else { $report.Add($name + ' missing') }
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
Add-Section 'Client jars, backups and class versions'
$versions = Join-Path $downloads 'versions'
if (Test-Path -LiteralPath $versions) {
    foreach ($item in Get-ChildItem -LiteralPath $versions -Recurse -File | Where-Object { $_.Name -match '\.patch(\.ORIGINAL)?$' }) {
        $report.Add((Protect-Text $item.FullName) + ' size=' + $item.Length + ' SHA256=' + (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash)
        $zip = $null
        try {
            $zip = [IO.Compression.ZipFile]::OpenRead($item.FullName)
            $report.Add('CheatBreaker Start.class present: ' + [bool]($null -ne $zip.GetEntry('Start.class')))
            $majors = @{}
            foreach ($entry in $zip.Entries) {
                if (-not $entry.FullName.EndsWith('.class')) { continue }
                $stream = $entry.Open()
                try {
                    $header = New-Object byte[] 8
                    $count = $stream.Read($header, 0, 8)
                    if ($count -eq 8) {
                        $major = ([int]$header[6] * 256) + [int]$header[7]
                        $majors[$major] = 1 + [int]$majors[$major]
                    }
                } finally { $stream.Dispose() }
            }
            $report.Add('Class versions: ' + (($majors.GetEnumerator() | Sort-Object Key | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join ', '))
        } catch { $report.Add('Jar inspection failed: ' + $_.Exception.Message) }
        finally { if ($null -ne $zip) { $zip.Dispose() } }
    }
    foreach ($file in Get-ChildItem -LiteralPath $versions -Recurse -File -Filter '*.json') {
        try {
            $data = Get-Content -LiteralPath $file.FullName -Raw | ConvertFrom-Json
            $report.Add(('{0}: id={1}; mainClass={2}; libraries={3}' -f (Protect-Text $file.FullName), $data.id, $data.mainClass, @($data.libraries).Count))
        } catch { $report.Add('Invalid version JSON: ' + (Protect-Text $file.FullName)) }
    }
}

Add-Log (Join-Path $cbRoot 'logs\rendererOld.log') 80
Add-Log (Join-Path $cbRoot 'logs\renderer.log') 220
Add-Log (Join-Path $minecraft 'logs\latest.log') 160
Add-Log (Join-Path $env:LOCALAPPDATA 'cia_unpatcher\cia_unpatcher.log') 80

$roots = @([Environment]::GetFolderPath('Desktop'), (Join-Path $env:USERPROFILE 'Downloads'), [Environment]::GetFolderPath('MyDocuments'))
if ($PatcherPath) { $roots += Split-Path -Parent $PatcherPath }
$patchLogs = foreach ($root in ($roots | Select-Object -Unique)) {
    if ($root -and (Test-Path -LiteralPath $root)) {
        Get-ChildItem -LiteralPath $root -Filter 'cia_patcher.log' -File -Recurse -Depth 3 -ErrorAction SilentlyContinue
    }
}
foreach ($log in ($patchLogs | Sort-Object LastWriteTime -Descending | Select-Object -First 3)) { Add-Log $log.FullName 100 }
if (-not $patchLogs) { $report.Add('Patcher log not found. Re-run with -PatcherPath pointing to the patcher EXE if needed.') }

$crashes = foreach ($root in @($minecraft, $cbRoot)) {
    if (Test-Path -LiteralPath $root) {
        Get-ChildItem -LiteralPath $root -Filter 'hs_err_pid*.log' -File -Depth 2 -Recurse -ErrorAction SilentlyContinue
        $crashDir = Join-Path $root 'crash-reports'
        if (Test-Path -LiteralPath $crashDir) { Get-ChildItem -LiteralPath $crashDir -Filter '*.txt' -File }
    }
}
foreach ($crash in ($crashes | Sort-Object LastWriteTime -Descending | Select-Object -First 2)) { Add-Log $crash.FullName 140 }

Add-Section 'Recent Windows application crashes'
try {
    $events = Get-WinEvent -FilterHashtable @{LogName='Application'; ProviderName='Application Error'; StartTime=(Get-Date).AddHours(-3)} -MaxEvents 30 -ErrorAction Stop
    foreach ($event in ($events | Where-Object { $_.Message -match '(?i)CheatBreaker|javaw?\.exe' } | Select-Object -First 3)) {
        $report.Add((Protect-Text ($event.TimeCreated.ToString('s') + "`r`n" + $event.Message)))
    }
} catch { $report.Add('No matching accessible Windows crash event.') }

if (-not $OutputPath) { $OutputPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'CheatBreaker-diagnostic.txt' }
$result = Protect-Text ($report -join "`r`n")
[IO.File]::WriteAllText($OutputPath, $result, [Text.UTF8Encoding]::new($false))
Write-Output $result
Write-Output "`r`nReport saved: $OutputPath"
