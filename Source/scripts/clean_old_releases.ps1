# Remove generated older releases only; leave games and unrecognized files intact.
[CmdletBinding(SupportsShouldProcess)]
param([string]$AdditionalOutputDirectory = '')
$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Workspace = (Resolve-Path (Join-Path $ProjectRoot '..')).Path
$VersionText = Get-Content -LiteralPath (Join-Path $ProjectRoot 'lantool\_version.py') -Raw
$Match = [regex]::Match($VersionText, '__version__ = "(\d+\.\d+\.\d+)"')
if (-not $Match.Success) { throw 'Cannot determine current release.' }
$CurrentVersion = [version]$Match.Groups[1].Value

function Remove-GeneratedItem([string]$Path, [string]$Parent) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $ResolvedParent = (Resolve-Path -LiteralPath $Parent).Path.TrimEnd('\') + '\'
    $Item = Get-Item -LiteralPath $Path -Force
    if (-not $Item.FullName.StartsWith($ResolvedParent, [StringComparison]::OrdinalIgnoreCase) -or
        ($Item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing cleanup outside its expected folder or through a link: $Path"
    }
    if ($PSCmdlet.ShouldProcess($Item.FullName, 'Remove obsolete generated build files')) {
        Remove-Item -LiteralPath $Item.FullName -Recurse -Force
    }
}

$Roots = @($Workspace, (Join-Path $Workspace 'Qt UI'), (Join-Path $Workspace 'Updated UI'))
if ($AdditionalOutputDirectory) { $Roots += $AdditionalOutputDirectory }
foreach ($Root in ($Roots | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { continue }
    foreach ($Release in Get-ChildItem -LiteralPath $Root -Directory) {
        if ($Release.Name -notmatch '^Lan Launcher Alpha (\d+\.\d+\.\d+)$') { continue }
        if ([version]$Matches[1] -ge $CurrentVersion) { continue }
        if ($Release.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
        Remove-GeneratedItem (Join-Path $Release.FullName 'Source') $Release.FullName
        foreach ($Exe in Get-ChildItem -LiteralPath $Release.FullName -File) {
            if ($Exe.Name -match '^LAN (Host|Client|Launcher) \d+\.\d+\.\d+\.exe$') {
                Remove-GeneratedItem $Exe.FullName $Release.FullName
            }
        }
        # An unused game folder contains only the generated README. Remove it
        # only if it exactly matches the current release's generated README.
        $OldGames = Join-Path $Release.FullName 'Game Directory'
        $CurrentReadme = Join-Path $Root "Lan Launcher Alpha $CurrentVersion\Game Directory\README.txt"
        if ((Test-Path -LiteralPath $OldGames -PathType Container) -and
            -not ((Get-Item -LiteralPath $OldGames).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            $GameItems = @(Get-ChildItem -LiteralPath $OldGames -Force)
            if ($GameItems.Count -eq 0) {
                Remove-GeneratedItem $OldGames $Release.FullName
            } elseif ($GameItems.Count -eq 1 -and $GameItems[0].Name -eq 'README.txt' -and
                -not $GameItems[0].PSIsContainer -and
                -not ($GameItems[0].Attributes -band [IO.FileAttributes]::ReparsePoint) -and
                (Test-Path -LiteralPath $CurrentReadme -PathType Leaf)) {
                if ((Get-FileHash -LiteralPath $GameItems[0].FullName).Hash -eq
                    (Get-FileHash -LiteralPath $CurrentReadme).Hash) {
                    Remove-GeneratedItem $OldGames $Release.FullName
                }
            }
        }
        # Keep configuration, bundles and all other user files.
        if (-not (Get-ChildItem -LiteralPath $Release.FullName -Force | Select-Object -First 1)) {
            Remove-GeneratedItem $Release.FullName $Root
        }
    }
}
foreach ($File in Get-ChildItem -LiteralPath $Workspace -File) {
    if ($File.Name -match '^(?:Build LANL |Start LANL |build-lanl-)(\d+\.\d+\.\d+)(?:\.pyw|\.vbs| Hidden\.cmd|\.log)$') {
        if ([version]$Matches[1] -lt $CurrentVersion) { Remove-GeneratedItem $File.FullName $Workspace }
    }
}
# These directories contain generated build output only. Keep the stable shared cache.
foreach ($CacheRoot in @('build\package_stage', 'build\pyinstaller')) {
    $CachePath = Join-Path $ProjectRoot $CacheRoot
    if (-not (Test-Path -LiteralPath $CachePath)) { continue }
    foreach ($Cache in Get-ChildItem -LiteralPath $CachePath -Directory) {
        if ($Cache.Name -match '^LAN (?:Client|Host|Launcher) (\d+\.\d+\.\d+)$') {
            if ([version]$Matches[1] -lt $CurrentVersion) { Remove-GeneratedItem $Cache.FullName $CachePath }
        }
    }
}
$SpecPath = Join-Path $ProjectRoot 'build\spec'
if (Test-Path -LiteralPath $SpecPath) {
    foreach ($Spec in Get-ChildItem -LiteralPath $SpecPath -File) {
        if ($Spec.Name -match '^LAN (?:Client|Host|Launcher) (\d+\.\d+\.\d+)\.spec$') {
            if ([version]$Matches[1] -lt $CurrentVersion) { Remove-GeneratedItem $Spec.FullName $SpecPath }
        }
    }
}
