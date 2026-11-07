$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$source = Join-Path $root 'Source'
$versionFile = Join-Path $source 'lantool\_version.py'
$buildScript = Join-Path $source 'scripts\build_windows.ps1'
$releaseRoot = Join-Path $root 'Releases'
$logRoot = Join-Path $source 'build\logs'
New-Item -ItemType Directory -Path $releaseRoot,$logRoot -Force | Out-Null
$logFile = Join-Path $logRoot 'build-latest-lan-launcher.log'

function Find-BuildPython {
    $candidates = New-Object System.Collections.Generic.List[string]
    try {
        $fromLauncher = & py.exe -3.15 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $fromLauncher) { $candidates.Add(($fromLauncher | Select-Object -First 1).Trim()) }
    } catch {}
    foreach ($commandName in @('python.exe', 'python3.exe')) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($command -and $command.Source) { $candidates.Add($command.Source) }
    }
    foreach ($registryRoot in @('HKCU:\Software\Python\PythonCore', 'HKLM:\Software\Python\PythonCore')) {
        if (Test-Path $registryRoot) {
            foreach ($version in (Get-ChildItem $registryRoot -ErrorAction SilentlyContinue)) {
                $key = Join-Path $version.PSPath 'InstallPath'
                $installKey = Get-Item $key -ErrorAction SilentlyContinue
                if ($installKey) {
                    $folder = $installKey.GetValue('')
                    if ($folder) { $candidates.Add((Join-Path $folder 'python.exe')) }
                }
            }
        }
    }
    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
        try {
            $version = & $candidate -c 'import sys; print(*sys.version_info[:3])' 2>$null
            if ($LASTEXITCODE -eq 0 -and $version.Trim() -eq '3 15 0') {
                return $candidate
            }
        } catch {}
    }
    throw 'Release builds require Windows x64 CPython 3.15.0. Install that interpreter, then run this tool again.'
}

try {
    Start-Transcript -Path $logFile -Force | Out-Null
    if (-not (Test-Path -LiteralPath $versionFile -PathType Leaf) -or
        -not (Test-Path -LiteralPath $buildScript -PathType Leaf)) {
        throw 'The Source folder or Windows build script is missing.'
    }
    $python = Find-BuildPython
    Write-Host "Using Python: $python"

    $versionSource = [IO.File]::ReadAllText($versionFile)
    $match = [regex]::Match($versionSource, '(?m)^__version__ = "0\.9\.(\d{2,})"\r?$')
    if (-not $match.Success) { throw 'Could not read the launcher version.' }
    $patch = [int]$match.Groups[1].Value
    $latest = $patch
    foreach ($release in (Get-ChildItem -LiteralPath @($root,$releaseRoot) -Directory -Filter 'LAN Launcher V0.9.*')) {
        if ($release.Name -match '^LAN Launcher V0\.9\.(\d{2,})$' -and
            (Test-Path -LiteralPath (Join-Path $release.FullName 'Launcher Bin\Release\version.json') -PathType Leaf)) {
            $latest = [Math]::Max($latest, [int]$Matches[1])
        }
    }
    foreach ($archive in (Get-ChildItem -LiteralPath @($root,$releaseRoot) -File -Filter 'LAN Launcher V0.9.*.zip')) {
        if ($archive.Name -match '^LAN Launcher V0\.9\.(\d{2,})\.zip$') {
            $latest = [Math]::Max($latest, [int]$Matches[1])
        }
    }
    $nextPatch = $latest + 1
    $nextVersion = '0.9.{0:D2}' -f $nextPatch
    $updated = [regex]::Replace($versionSource, '(?m)^__version__ = "0\.9\.\d{2,}"', '__version__ = "' + $nextVersion + '"', 1)
    [IO.File]::WriteAllText($versionFile, $updated, [Text.UTF8Encoding]::new($false))
    Write-Host "Release number advanced to $nextVersion."

    & $python (Join-Path $source 'scripts\check_build_environment.py') 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Preparing Python build requirements...'
        & $python -m pip --version 2>$null
        if ($LASTEXITCODE -ne 0) { & $python -m ensurepip --upgrade }
        if ($LASTEXITCODE -ne 0) { throw 'Python pip could not be prepared.' }
        & $python -m pip --disable-pip-version-check install --require-hashes -r (Join-Path $source 'build-requirements.lock')
        if ($LASTEXITCODE -ne 0) { throw 'Python build requirements could not be installed.' }
    }

    Write-Host 'Checking the Qt interface before packaging...'
    $previewRoot = Join-Path $source 'build\qt-preview'
    New-Item -ItemType Directory -Path $previewRoot -Force | Out-Null
    Push-Location $source
    try {
        foreach ($check in @(@('library', ''), @('room', ''), @('settings', 'Network'),
                             @('settings', 'Player'), @('downloads', ''), @('details', ''))) {
            $page = $check[0]
            $tab = $check[1]
            $capture = Join-Path $previewRoot ("build-check-$page-$tab.png")
            $previewArgs = @('-m', 'lantool.qt.main', '--capture-ui', $capture, '--preview-page', $page)
            if ($tab) { $previewArgs += @('--preview-settings-tab', $tab) }
            & $python @previewArgs
            if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $capture -PathType Leaf)) {
                throw "The Qt interface failed to load: $page $tab. Packaging stopped."
            }
        }
    } finally {
        Pop-Location
    }

    & $buildScript -PythonExecutable $python -OutputDirectory $releaseRoot
    if ($LASTEXITCODE -ne 0) { throw "Windows build exited with code $LASTEXITCODE." }
    Write-Host 'Release build complete.' -ForegroundColor Green
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
} finally {
    Stop-Transcript -ErrorAction SilentlyContinue | Out-Null
}
