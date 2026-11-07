[CmdletBinding()]
param([string]$SourcePath = (Join-Path $PSScriptRoot 'upstream'))
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$lock = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'source-lock.json') -Raw | ConvertFrom-Json
$SourcePath = (Resolve-Path -LiteralPath $SourcePath).Path
$head = (& git -C $SourcePath rev-parse HEAD).Trim()
if ($LASTEXITCODE -or $head -cne $lock.commit) { throw 'The source HEAD differs from the pinned upstream commit.' }
$patch = Join-Path $PSScriptRoot $lock.patch
if ((Get-FileHash -LiteralPath $patch -Algorithm SHA256).Hash.ToLowerInvariant() -cne $lock.patch_sha256) { throw 'Patch hash differs from source lock.' }
$allowed = @($lock.modified_files.PSObject.Properties.Name) + @($lock.deleted_files)
$actual = @(& git -C $SourcePath diff --name-only HEAD) + @(& git -C $SourcePath ls-files --others --exclude-standard)
foreach ($relative in $actual) {
    if ($relative -notin $allowed) { throw "Unexpected source change: $relative" }
}
foreach ($entry in $lock.modified_files.PSObject.Properties) {
    $path = Join-Path $SourcePath $entry.Name
    if (!(Test-Path -LiteralPath $path)) { throw "Missing patched source: $($entry.Name)" }
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($hash -cne $entry.Value) { throw "Patched source hash differs: $($entry.Name)" }
}
foreach ($relative in $lock.deleted_files) {
    if (Test-Path -LiteralPath (Join-Path $SourcePath $relative)) { throw "Obsolete source file remains: $relative" }
}
Write-Host 'Verified pinned upstream commit, patch integrity, and all modified source hashes.'
