param(
    [string]$OutputDirectory = "",
    [string]$PythonExecutable = "python",
    [switch]$SkipMsiDownload,
    [switch]$AllowMissingVlaRuntime,
    [switch]$CleanBuild,
    [switch]$CleanOldReleases,
    [switch]$SkipHelper,
    [switch]$BuildBootloaderFromSource,
    [ValidatePattern('^[A-Fa-f0-9]{40}$')][string]$CodeSigningCertificateThumbprint = '',
    [string]$CodeSigningTimestampServer = ''
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
& $PythonExecutable (Join-Path $PSScriptRoot 'check_build_environment.py')
if ($LASTEXITCODE -ne 0) { throw 'Release environment verification failed.' }
$VlaPackageDirectory = Join-Path $ProjectRoot "vendor\vla"
$HasVlaRuntime = Test-Path -LiteralPath (Join-Path $VlaPackageDirectory 'manifest.json') -PathType Leaf
if (-not $HasVlaRuntime -and -not $AllowMissingVlaRuntime) {
    throw 'The VLA runtime is not ready. Assemble the private service and unchanged signed shared driver package in vendor\vla first. Use -AllowMissingVlaRuntime only for a separate UI preview package without networking.'
}
$OutputDirectory = if ($OutputDirectory) { $OutputDirectory } else { Join-Path (Split-Path -Parent $ProjectRoot) 'Releases' }
$VersionSource = Get-Content -LiteralPath (Join-Path $ProjectRoot "lantool\_version.py") -Raw
$VersionMatch = [regex]::Match($VersionSource, '(?m)^__version__ = "(0\.9\.\d{2,})"\r?$')
if (-not $VersionMatch.Success) { throw "Set the launcher release version to 0.9.NN in Source/lantool/_version.py." }
$AppVersion = $VersionMatch.Groups[1].Value
$ReleaseLabel = "V$AppVersion"
$PatchNumber = [int]($AppVersion.Split('.')[-1])
if ($PatchNumber -gt [uint16]::MaxValue -or $AppVersion -ne "0.9.$($PatchNumber.ToString('D2'))") {
    throw "Use the 0.9.NN release format, padding the patch counter to at least two digits."
}
$ProtocolMatch = [regex]::Match($VersionSource, '(?m)^__proto__ = ([1-9]\d*)\r?$')
if (-not $ProtocolMatch.Success) { throw "The launcher room protocol number is missing or invalid." }
$RoomProtocol = [int]$ProtocolMatch.Groups[1].Value
$PackageName = "LAN Launcher $ReleaseLabel"
$ExecutableNames = @('Host', 'Client')
$RuntimeFolder = 'Launcher Bin'
$BuildRoles = @('Client', 'Host', 'QuickStart')
if ($AllowMissingVlaRuntime) {
    $PackageName = 'Lan Launcher VLA Preview'
    $ExecutableNames = @('LAN Host VLA Preview', 'LAN Client VLA Preview')
    $BuildRoles = @('Client', 'Host')
} else {
    $ExecutableNames += 'Quick Start'
}
$PackageDirectory = Join-Path $OutputDirectory $PackageName
$StageDirectory = Join-Path $ProjectRoot "build\package_stage"

if (-not $AllowMissingVlaRuntime) {
    Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
    # A release folder is published once its manifest exists. Also recognize older ZIP releases.
    $PublishedVersions = @(
        foreach ($ReleaseRoot in (@((Split-Path -Parent $ProjectRoot), $OutputDirectory) | Select-Object -Unique)) {
            if (Test-Path -LiteralPath $ReleaseRoot -PathType Container) {
                Get-ChildItem -LiteralPath $ReleaseRoot -Directory -Filter 'Lan Launcher V0.9.*' |
                    ForEach-Object {
                        if ($_.Name -match '^Lan Launcher V(0\.9\.\d{2,})$') {
                            $Manifest = Join-Path $_.FullName 'Launcher Bin\Release\version.json'
                            if (Test-Path -LiteralPath $Manifest -PathType Leaf) {
                                [pscustomobject]@{ Version = [version]$Matches[1]; Manifest = $Manifest; Archive = $null }
                            }
                        }
                    }
                Get-ChildItem -LiteralPath $ReleaseRoot -File -Filter 'Lan Launcher V0.9.*.zip' |
                    ForEach-Object {
                        if ($_.Name -match '^Lan Launcher V(0\.9\.\d{2,})\.zip$') {
                            [pscustomobject]@{ Version = [version]$Matches[1]; Manifest = $null; Archive = $_ }
                        }
                    }
            }
        }
    )
    $LatestRelease = $PublishedVersions | Sort-Object Version -Descending | Select-Object -First 1
    if ($LatestRelease) {
        if ([version]$AppVersion -le $LatestRelease.Version) {
            $NextVersion = '0.9.{0:D2}' -f ($LatestRelease.Version.Build + 1)
            throw "Release $AppVersion has already been published or superseded. Bump the patch counter to $NextVersion in Source/lantool/_version.py."
        }
        if ($LatestRelease.Manifest) {
            $PreviousRelease = Get-Content -LiteralPath $LatestRelease.Manifest -Raw | ConvertFrom-Json
        } else {
            $PreviousZip = [IO.Compression.ZipFile]::OpenRead($LatestRelease.Archive.FullName)
            try {
                $ArchiveRoot = $LatestRelease.Archive.BaseName
                $Entry = $PreviousZip.GetEntry("$ArchiveRoot/Launcher Bin/Release/version.json")
                if (-not $Entry) { $Entry = $PreviousZip.GetEntry("$ArchiveRoot/version.json") }
                if (-not $Entry) { throw "The previous release archive is missing version.json." }
                $Reader = [IO.StreamReader]::new($Entry.Open())
                try { $PreviousRelease = $Reader.ReadToEnd() | ConvertFrom-Json } finally { $Reader.Dispose() }
            } finally { $PreviousZip.Dispose() }
        }
        if ($RoomProtocol -lt [int]$PreviousRelease.room_protocol) {
            throw "The room protocol cannot decrease from $($PreviousRelease.room_protocol) to $RoomProtocol."
        }
    }
}

if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf) -and
    -not (Get-Command $PythonExecutable -ErrorAction SilentlyContinue)) {
    throw "Windows x64 CPython 3.15.0 is required for release packaging."
}
& $PythonExecutable -c "import PyInstaller, cryptography, PySide6"
if ($LASTEXITCODE -ne 0) {
    throw "Build tools are missing. Run: python -m pip install -r `"$ProjectRoot\build-requirements.txt`""
}
$PythonTrustFiles = @(& $PythonExecutable -c "import ssl; from pathlib import Path; ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER); p = Path(ssl.__file__).with_name('codex-rejected-cas.pem'); print(p) if p.is_file() else None")
if ($LASTEXITCODE -ne 0) { throw 'The build Python could not initialize TLS. Check its OpenSSL installation and trust files.' }
if ($BuildBootloaderFromSource) {
    # Compiles PyInstaller's launcher stub on this PC instead of using the prebuilt one that
    # many antivirus products already know. Needs the Visual Studio C++ build tools.
    if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
        throw 'Building the PyInstaller bootloader needs the Visual Studio C++ build tools. Run this from a Developer PowerShell.'
    }
    $PyiVersion = (& $PythonExecutable -c "import PyInstaller; print(PyInstaller.__version__)").Trim()
    Write-Host "Rebuilding the PyInstaller $PyiVersion bootloader from source..."
    & $PythonExecutable -m pip install --force-reinstall --no-cache-dir --no-binary pyinstaller "pyinstaller==$PyiVersion"
    if ($LASTEXITCODE -ne 0) { throw 'Could not build the PyInstaller bootloader from source.' }
}
$PythonDllProbe = @'
import ctypes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)
get_module = kernel32.GetModuleHandleW
get_module.argtypes = [ctypes.c_wchar_p]
get_module.restype = ctypes.c_void_p
get_path = kernel32.GetModuleFileNameW
get_path.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
for name in ("python3t.dll", "python3.dll"):
    handle = get_module(name)
    if handle:
        path = ctypes.create_unicode_buffer(32768)
        if get_path(handle, path, len(path)):
            print(path.value)
'@
$PythonDllProbeB64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($PythonDllProbe))
$PythonDllProbeCommand = "import base64; exec(base64.b64decode('$PythonDllProbeB64'))"
$PythonAbiDlls = @(& $PythonExecutable -c $PythonDllProbeCommand | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) })
if ($LASTEXITCODE -ne 0 -or $PythonAbiDlls.Count -eq 0) {
    throw "This Python installation could not load cryptography's Ed25519 extension or locate its stable-ABI DLL. See the Python error above."
}

if ($HasVlaRuntime) {
    Push-Location $ProjectRoot
    try {
        & $PythonExecutable -c "from pathlib import Path; from silent_tunnel.installer import validate_package; validate_package(Path('vendor/vla'))"
        if ($LASTEXITCODE -ne 0) { throw 'The VLA native package failed identity, integrity or signature verification.' }
    } finally { Pop-Location }
} else {
    Write-Warning 'Building a separate VLA UI preview. Hosting and joining require the verified native VLA package.'
}
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
$PackageDirectory = Join-Path $OutputDirectory $PackageName
$StageDirectory = Join-Path $ProjectRoot "build\package_stage"
$StagedApps = @{}
$PayloadName = 'LAN Client'
$VersionResource = Join-Path $ProjectRoot "build\release-version.txt"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $VersionResource) | Out-Null
$VersionTuple = "0, 9, $PatchNumber, 0"
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($VersionTuple), prodvers=($VersionTuple),
                   mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'NN LAN Launcher'),
    StringStruct('FileDescription', 'NN LAN Launcher'),
    StringStruct('FileVersion', '$AppVersion'),
    StringStruct('InternalName', 'LAN Launcher'),
    StringStruct('OriginalFilename', 'LAN Launcher.exe'),
    StringStruct('ProductName', 'NN LAN Launcher'),
    StringStruct('ProductVersion', '$AppVersion')
  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
"@ | Set-Content -LiteralPath $VersionResource -Encoding UTF8
# Host and Client are separate entry points (run_host.py / run_client.py) that pin the
# role in code, so nothing depends on the final file name. Both builds import the same
# modules; the Client's runtime folder is used and the Host's is merged over it (new files only).
$PayloadNames = @{}
foreach ($Role in $BuildRoles) {
    $ExecutableName = switch ($Role) {
        'Client' { $ExecutableNames[1] }
        'Host' { $ExecutableNames[0] }
        'QuickStart' { $ExecutableNames[2] }
    }
    $PayloadName = "LAN $Role"
    $PayloadNames[$ExecutableName] = $PayloadName
    $pyinstallerArgs = @(
        "-m", "PyInstaller", "--noconfirm", "--onedir", "--windowed", "--noupx",
        "--contents-directory", $RuntimeFolder,
        "--name", $PayloadName, "--distpath", $StageDirectory,
        "--workpath", (Join-Path $ProjectRoot "build\pyinstaller\$($Role.ToLower())"),
        "--specpath", (Join-Path $ProjectRoot "build\spec"),
        "--version-file", $VersionResource,
        "--manifest", (Join-Path $PSScriptRoot 'app.manifest'),
        "--icon", (Join-Path $ProjectRoot 'lantool\qt\assets\launcher-icon.ico'),
        "--runtime-hook", (Join-Path $PSScriptRoot 'qt_runtime_hook.py'),
        "--exclude-module", "PySide6.QtWebEngineCore",
        "--exclude-module", "PySide6.QtWebEngineQuick",
        "--exclude-module", "PySide6.QtWebEngineWidgets",
        (Join-Path $ProjectRoot "run_$($Role.ToLower()).py")
    )
    # PyInstaller's PySide6 hooks otherwise collect optional Qt families that
    # this QtQuick/Widgets launcher never imports.
    foreach ($UnusedQtModule in @(
        'Qt3DAnimation', 'Qt3DCore', 'Qt3DExtras', 'Qt3DInput', 'Qt3DLogic',
        'Qt3DRender', 'QtCharts', 'QtDataVisualization', 'QtGraphs',
        'QtLocation', 'QtMultimedia', 'QtMultimediaWidgets', 'QtPdf',
        'QtPdfWidgets', 'QtPositioning', 'QtRemoteObjects', 'QtScxml',
        'QtSensors', 'QtSpatialAudio', 'QtSql', 'QtStateMachine',
        'QtTest', 'QtTextToSpeech', 'QtVirtualKeyboard', 'QtWebChannel',
        'QtWebSockets', 'QtWebView', 'QtQuick3D', 'QtQuick3DAssetImport',
        'QtQuick3DPhysics', 'QtQuick3DParticles', 'QtQuickTest'
    )) {
        $pyinstallerArgs += @('--exclude-module', "PySide6.$UnusedQtModule")
    }
    if ($Role -ne 'QuickStart') {
        $pyinstallerArgs += @('--collect-all', 'cryptography', '--collect-all', 'PIL')
        if ($HasVlaRuntime) { $pyinstallerArgs += @('--add-data', "$VlaPackageDirectory;vendor/vla") }
    }
    if ($CleanBuild) { $pyinstallerArgs += '--clean' }
    foreach ($PythonAbiDll in $PythonAbiDlls) {
        $pyinstallerArgs += @("--add-binary", "$PythonAbiDll;.")
    }
    foreach ($TrustFile in $PythonTrustFiles) {
        $pyinstallerArgs += @("--add-data", "$TrustFile;.")
    }
    Write-Host "Building $ExecutableName..."
    $BuildSucceeded = $false
    for ($Attempt = 1; $Attempt -le 3; $Attempt++) {
        Push-Location $ProjectRoot
        try {
            & $PythonExecutable @pyinstallerArgs
            $BuildExitCode = $LASTEXITCODE
        } finally {
            Pop-Location
        }
        if ($BuildExitCode -eq 0) {
            $BuildSucceeded = $true
            break
        }
        if ($BuildExitCode -eq -1073741819 -and $Attempt -lt 3) {
            Write-Warning "Windows reported a temporary access violation while PyInstaller analyzed $ExecutableName. Retrying automatically ($($Attempt + 1)/3)…"
            Start-Sleep -Seconds 2
            continue
        }
        if ($BuildExitCode -eq -1073741819) {
            throw "PyInstaller hit a Windows access violation three times while building $ExecutableName. This is a native Windows/Python crash, not a regular build error. Try the one-click build again or build on another Windows PC."
        }
        throw "PyInstaller failed for $ExecutableName (exit code $BuildExitCode)."
    }
    if (-not $BuildSucceeded) { throw "PyInstaller could not build $ExecutableName." }
    $StagedApp = Join-Path $StageDirectory $PayloadName
    if (-not (Test-Path -LiteralPath $StagedApp -PathType Container)) {
        throw "PyInstaller output was not found: $StagedApp"
    }
    $StagedApps[$ExecutableName] = $StagedApp
}

# LAN Helper: the one small elevated program (fixed action list, no UI, no Qt). The launcher
# starts it for UAC operations instead of re-launching the whole app as administrator.
$HelperStage = Join-Path $StageDirectory 'LAN Helper'
if (-not $SkipHelper) {
    $HelperVersionResource = Join-Path $ProjectRoot "build\helper-version.txt"
    (Get-Content -LiteralPath $VersionResource -Raw).Replace('FileDescription'', ''NN LAN Launcher', 'FileDescription'', ''NN LAN Launcher Helper (administrator operations)').Replace('LAN Launcher.exe', 'LAN Helper.exe') |
        Set-Content -LiteralPath $HelperVersionResource -Encoding UTF8
    $helperArgs = @(
        "-m", "PyInstaller", "--noconfirm", "--onedir", "--windowed", "--noupx",
        "--contents-directory", "Helper",
        "--name", "LAN Helper", "--distpath", $StageDirectory,
        "--workpath", (Join-Path $ProjectRoot "build\pyinstaller\helper"),
        "--specpath", (Join-Path $ProjectRoot "build\spec"),
        "--version-file", $HelperVersionResource,
        "--manifest", (Join-Path $PSScriptRoot 'app.manifest'),
        "--icon", (Join-Path $ProjectRoot 'lantool\qt\assets\launcher-icon.ico'),
        "--collect-all", "cryptography",
        "--collect-submodules", "silent_tunnel",
        "--hidden-import", "lantool.netcore.adapter",
        "--exclude-module", "PySide6", "--exclude-module", "PIL", "--exclude-module", "tkinter",
        (Join-Path $ProjectRoot "lan_admin_helper.py")
    )
    if ($CleanBuild) { $helperArgs += '--clean' }
    foreach ($PythonAbiDll in $PythonAbiDlls) { $helperArgs += @("--add-binary", "$PythonAbiDll;.") }
    foreach ($TrustFile in $PythonTrustFiles) { $helperArgs += @("--add-data", "$TrustFile;.") }
    Write-Host "Building LAN Helper..."
    Push-Location $ProjectRoot
    try { & $PythonExecutable @helperArgs; $HelperExit = $LASTEXITCODE } finally { Pop-Location }
    if ($HelperExit -ne 0) { throw "PyInstaller failed for LAN Helper (exit code $HelperExit). Re-run with -SkipHelper to build without it (elevation then falls back to the launcher exe)." }
    if (-not (Test-Path -LiteralPath (Join-Path $HelperStage 'LAN Helper.exe') -PathType Leaf)) { throw "LAN Helper output was not found: $HelperStage" }
}

New-Item -ItemType Directory -Force -Path $PackageDirectory | Out-Null
$SourceDestination = Join-Path $PackageDirectory $RuntimeFolder
$ElevationDirectory = Join-Path $SourceDestination 'Elevation'
$ReleaseDirectory = Join-Path $SourceDestination 'Release'
foreach ($Directory in @($PackageDirectory, $SourceDestination, $ElevationDirectory, $ReleaseDirectory)) {
    if ((Test-Path -LiteralPath $Directory) -and
        ((Get-Item -LiteralPath $Directory).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing to update a linked package directory: $Directory"
    }
}
foreach ($ExecutableName in $ExecutableNames) {
    $StagedApp = $StagedApps[$ExecutableName]
    $ExeSource = Join-Path $StagedApp "$($PayloadNames[$ExecutableName]).exe"
    $ExeDestination = Join-Path $PackageDirectory "$ExecutableName.exe"
    Copy-Item -LiteralPath $ExeSource -Destination $ExeDestination -Force
}

if (-not $SkipHelper) {
    New-Item -ItemType Directory -Force -Path $ElevationDirectory | Out-Null
    Copy-Item -LiteralPath (Join-Path $HelperStage 'LAN Helper.exe') -Destination (Join-Path $ElevationDirectory 'LAN Helper.exe') -Force
    $HelperDestination = Join-Path $ElevationDirectory 'Helper'
    if ((Test-Path -LiteralPath $HelperDestination) -and
        ((Get-Item -LiteralPath $HelperDestination).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Refusing to update a linked helper directory.'
    }
    & robocopy.exe (Join-Path $HelperStage 'Helper') $HelperDestination '/E' '/PURGE' '/XJ' '/R:1' '/W:1' '/NFL' '/NDL' '/NJH' '/NJS' '/NP'
    if ($LASTEXITCODE -ge 8) { throw "Helper runtime copy failed ($LASTEXITCODE)" }
    $global:LASTEXITCODE = 0
}

$LegacyExecutable = Join-Path $PackageDirectory "LAN Launcher $AppVersion.exe"
if (Test-Path -LiteralPath $LegacyExecutable -PathType Leaf) {
    Remove-Item -LiteralPath $LegacyExecutable -Force
}

$ClientStage = $StagedApps[$ExecutableNames[1]]
# Parallel file transfer skips unchanged runtime files instead of deleting and
# recopying the entire Qt installation on every build. Purge is restricted to
# the generated Source directory; game files and configuration are outside it.
function Sync-BuildTree([string]$From, [string]$To, [string[]]$Exclude = @()) {
    $SafeRoot = [IO.Path]::GetFullPath($SourceDestination).TrimEnd('\')
    $Target = [IO.Path]::GetFullPath($To).TrimEnd('\')
    if ($Target -ne $SafeRoot -and -not $Target.StartsWith($SafeRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to sync outside generated runtime: $Target"
    }
    if ((Test-Path -LiteralPath $Target) -and
        ((Get-Item -LiteralPath $Target).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing to sync through a link: $Target"
    }
    $CopyArgs = @($From, $Target, '/E', '/PURGE', '/MT:8', '/XJ', '/R:1', '/W:1', '/NFL', '/NDL', '/NJH', '/NJS', '/NP')
    if ($Exclude.Count) { $CopyArgs += @('/XD') + $Exclude }
    & robocopy.exe @CopyArgs
    if ($LASTEXITCODE -ge 8) { throw "Runtime copy failed ($LASTEXITCODE): $Target" }
}
Sync-BuildTree (Join-Path $ClientStage $RuntimeFolder) $SourceDestination @('qt', 'art', 'games', 'Elevation', 'Release')
# Host build: add only files the Client build did not produce (never overwrite or purge).
$HostStage = $StagedApps[$ExecutableNames[0]]
if ($HostStage -and $HostStage -ne $ClientStage) {
    & robocopy.exe (Join-Path $HostStage $RuntimeFolder) $SourceDestination '/E' '/XC' '/XN' '/XO' '/XJ' '/XD' 'qt' 'art' 'games' '/MT:8' '/R:1' '/W:1' '/NFL' '/NDL' '/NJH' '/NJS' '/NP'
    if ($LASTEXITCODE -ge 8) { throw "Host runtime merge failed ($LASTEXITCODE)" }
}
# UI-only edits do not need to invalidate PyInstaller's dependency analysis.
Sync-BuildTree (Join-Path $ProjectRoot 'lantool\qt\qml') (Join-Path $SourceDestination 'qt\qml')
Sync-BuildTree (Join-Path $ProjectRoot 'lantool\qt\assets') (Join-Path $SourceDestination 'qt\assets')
# Remove content left by older builds of this version. The game directory at the
# package root is user-owned and is intentionally outside this generated runtime.
foreach ($LegacyDirectory in @('art', 'games')) {
    $LegacyPath = Join-Path $SourceDestination $LegacyDirectory
    if (Test-Path -LiteralPath $LegacyPath) {
        if ((Get-Item -LiteralPath $LegacyPath).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw "Refusing to remove linked legacy content: $LegacyPath"
        }
        Remove-Item -LiteralPath $LegacyPath -Recurse -Force
    }
}
$global:LASTEXITCODE = 0

& (Join-Path $PSScriptRoot 'trim_runtime.ps1') -RuntimeDirectory $SourceDestination -Apply

# Qt 6.12 uses Windows' ICU API. A private ICU selected while collecting
# unrelated QML plugins shadows System32's API and breaks QtWidgets imports.
$PrivateIcu = Join-Path $SourceDestination "icuuc.dll"
if ((Test-Path -LiteralPath (Join-Path $env:SystemRoot "System32\icuuc.dll")) -and
    (Test-Path -LiteralPath $PrivateIcu -PathType Leaf)) {
    Remove-Item -LiteralPath $PrivateIcu -Force
}

$GameDirectory = Join-Path $PackageDirectory "Game Directory"
New-Item -ItemType Directory -Force -Path $GameDirectory | Out-Null
$GameReadme = Join-Path $GameDirectory "README.txt"
if (-not (Test-Path -LiteralPath $GameReadme)) {
    @"
Copy each game's files into its own folder inside Game Directory.
Example: Game Directory\Battlefield 2\BF2.exe

On the Host, open Manage Game Directory, select a launch .exe, choose cover art,
and tick the game for the event playlist. Clients only see playlist games.
Clients check the selected .exe's path, name, and size before launch. If it differs,
the game files sync from the Host, and clients can then share verified files in the room.
"@ | Set-Content -LiteralPath $GameReadme -Encoding UTF8
}

$ProjectLicense = Join-Path (Split-Path -Parent $ProjectRoot) 'LICENSE'
if (-not (Test-Path -LiteralPath $ProjectLicense -PathType Leaf)) {
    throw "The project GPLv3 LICENSE file is missing: $ProjectLicense"
}
Copy-Item -LiteralPath $ProjectLicense -Destination (Join-Path $PackageDirectory 'LICENSE') -Force

# A successful PyInstaller exit does not prove that QML can create its root window.
# Check the assembled package before signing and hashing.
$SmokeDirectory = Join-Path $ProjectRoot 'build\qt-preview'
New-Item -ItemType Directory -Force -Path $SmokeDirectory | Out-Null
foreach ($Role in @('Client', 'Host')) {
    $Candidate = Join-Path $PackageDirectory "$Role.exe"
    $Capture = Join-Path $SmokeDirectory ("packaged-$Role.png")
    if (Test-Path -LiteralPath $Capture) { Remove-Item -LiteralPath $Capture -Force }
    $Smoke = Start-Process -FilePath $Candidate -ArgumentList @('--capture-ui', ('"' + $Capture + '"')) `
        -PassThru -WindowStyle Hidden
    try {
        if (-not $Smoke.WaitForExit(45000)) {
            $Smoke.Kill()
            throw "$Role package did not finish its Qt startup check within 45 seconds."
        }
        if ($Smoke.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $Capture -PathType Leaf)) {
            throw "$Role package could not load its Qt interface (exit code $($Smoke.ExitCode)). Release folder was not completed."
        }
    } finally {
        $Smoke.Dispose()
    }
}

if ($CodeSigningCertificateThumbprint) {
    if ($CodeSigningTimestampServer -notmatch '^https?://') {
        throw 'Supply -CodeSigningTimestampServer with the publisher timestamp service URL.'
    }
    & (Join-Path $PSScriptRoot 'sign_release.ps1') -PackageDirectory $PackageDirectory `
        -CertificateThumbprint $CodeSigningCertificateThumbprint -TimestampServer $CodeSigningTimestampServer
} else {
    Write-Warning 'Launcher executables are unsigned. Publisher signing and vendor false-positive review are required before claiming antivirus compatibility.'
}
# Zips downloaded from the internet carry Mark-of-the-Web, which triggers SmartScreen
# warnings on every file. This helper only clears that flag on this folder's files
# (no admin, no Defender or firewall changes). Written before hashing so it is listed.
$UnblockScript = @(
    '@echo off',
    'rem Clears the "downloaded from the internet" flag (Mark of the Web) on this folder only.',
    'pushd "%~dp0..\.." || exit /b 1',
    'powershell -NoProfile -Command "Get-ChildItem -LiteralPath ''.'' -Recurse -File -Force | Unblock-File"',
    'popd',
    'echo Done. Files in this folder are unblocked.',
    'pause'
) -join "`r`n"
New-Item -ItemType Directory -Force -Path $ReleaseDirectory | Out-Null
[IO.File]::WriteAllText((Join-Path $ReleaseDirectory 'Unblock downloaded files.cmd'), $UnblockScript + "`r`n", (New-Object Text.ASCIIEncoding))
# Release manifest: version.json plus SHA256SUMS.txt (sha256sum format) for the
# generated files only. Game Directory and portable user data are excluded, and
# this runs after signing so the hashes describe the final executables.
$IsSigned = [bool]$CodeSigningCertificateThumbprint
$VersionInfo = [ordered]@{
    version      = $AppVersion
    release      = $ReleaseLabel
    room_protocol = $RoomProtocol
    package      = $PackageName
    python       = "3.15.0"
    dependency_lock_sha256 = (Get-FileHash -LiteralPath (Join-Path $ProjectRoot "build-requirements.lock") -Algorithm SHA256).Hash.ToLowerInvariant()
    built_utc    = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    vla_runtime  = $HasVlaRuntime
    signed       = $IsSigned
    executables  = @($ExecutableNames | ForEach-Object { "$_.exe" }) + $(if ($SkipHelper) { @() } else { @('Launcher Bin/Elevation/LAN Helper.exe') })
    helper       = -not $SkipHelper
}
$VersionFile = Join-Path $ReleaseDirectory 'version.json'
[System.IO.File]::WriteAllText($VersionFile, ($VersionInfo | ConvertTo-Json -Depth 4) + "`r`n", [System.Text.UTF8Encoding]::new($false))

$HashFile = Join-Path $ReleaseDirectory 'SHA256SUMS.txt'
$PackageRoot = (Resolve-Path -LiteralPath $PackageDirectory).Path.TrimEnd('\') + '\'
$ExcludedTop = @('Game Directory', 'LanTool-data', 'portable.flag')
$ReleaseFiles = @(Get-ChildItem -LiteralPath $PackageDirectory -Recurse -File -Force |
    Where-Object {
        $Rel = $_.FullName.Substring($PackageRoot.Length)
        $Top = $Rel.Split('\')[0]
        $ExcludedTop -notcontains $Top -and $_.FullName -ne $HashFile
    } |
    Sort-Object FullName)
$HashLines = $ReleaseFiles |
    ForEach-Object {
        $Rel = $_.FullName.Substring($PackageRoot.Length).Replace('\', '/')
        $Hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$Hash *$Rel"
    }
[IO.File]::WriteAllText($HashFile, (($HashLines -join "`n") + "`n"), (New-Object Text.UTF8Encoding($false)))
Write-Host "Release manifest: $VersionFile, $HashFile ($(@($HashLines).Count) files)"
Write-Host "Created package: $PackageDirectory"
foreach ($ExecutableName in $ExecutableNames) {
    $ExeDestination = Join-Path $PackageDirectory "$ExecutableName.exe"
    Write-Host "Executable: $ExeDestination"
}
Write-Host "Runtime files: $SourceDestination"
Write-Host "Game files: $GameDirectory"
& (Join-Path $PSScriptRoot 'clean_build_staging.ps1')
if ($CleanOldReleases) { & (Join-Path $PSScriptRoot 'clean_old_releases.ps1') -AdditionalOutputDirectory $OutputDirectory }
