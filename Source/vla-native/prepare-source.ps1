[CmdletBinding()]
param([switch]$Fetch)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$lock = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'source-lock.json') -Raw | ConvertFrom-Json
$source = Join-Path $PSScriptRoot 'upstream'
$patch = Join-Path $PSScriptRoot 'patches\0001-vla-windows.patch'
if ((Get-FileHash -LiteralPath $patch -Algorithm SHA256).Hash.ToLowerInvariant() -ne $lock.patch_sha256) {
    throw 'VLA patch hash does not match source-lock.json.'
}
if (!(Test-Path -LiteralPath (Join-Path $source '.git'))) {
    if (!$Fetch) { throw 'Source is absent. Run prepare-source.ps1 -Fetch to download the pinned upstream source.' }
    # Use Git's OpenSSL backend because Schannel has no credential context in
    # some restricted build sessions. This changes no global Git configuration.
    & git -c http.sslBackend=openssl clone --no-checkout --depth 1 --branch $lock.tag $lock.repository $source
    if ($LASTEXITCODE) { throw 'Could not download pinned source.' }
    & git -C $source checkout --detach $lock.commit
    if ($LASTEXITCODE) { throw 'Pinned source checkout failed.' }
}
$head = (& git -C $source rev-parse HEAD).Trim()
if ($LASTEXITCODE -or $head -cne $lock.commit) { throw 'Upstream checkout is not the pinned commit; refusing to change it.' }
& git -C $source apply --reverse --check --whitespace=nowarn $patch 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host 'Pinned VLA patch is already applied.'
    & (Join-Path $PSScriptRoot 'verify-source.ps1') -SourcePath $source
    return
}
$status = & git -C $source status --porcelain
if ($status) { throw 'Upstream source has other edits. Preserve them before preparing the VLA fork.' }
& git -C $source apply --check --whitespace=nowarn $patch
if ($LASTEXITCODE) { throw 'Pinned VLA source patch did not validate.' }
& git -C $source apply --whitespace=nowarn $patch
if ($LASTEXITCODE) { throw 'VLA source patch did not apply.' }
Write-Host "Prepared VLA fork from $($lock.commit)."
& (Join-Path $PSScriptRoot 'verify-source.ps1') -SourcePath $source
