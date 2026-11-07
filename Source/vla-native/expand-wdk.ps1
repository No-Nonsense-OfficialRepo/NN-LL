[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$lock = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'wdk-lock.json') -Raw | ConvertFrom-Json
foreach ($package in $lock.packages) {
    $name = $package.id+'.'+$lock.package_version
    $archive = Join-Path $PSScriptRoot ('out\wdk-downloads\'+$name+'.nupkg')
    if (!(Test-Path -LiteralPath $archive)) { throw "Missing $name. Run node acquire-wdk.mjs first." }
    if ((Get-Item -LiteralPath $archive).Length -ne $package.bytes -or
        (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -cne $package.sha256) {
        throw "Package failed the pinned hash check: $name"
    }
    $destination = Join-Path $PSScriptRoot ('out\wdk-packages\'+$name)
    # The framework extractor rejects paths escaping the extraction destination.
    [IO.Compression.ZipFile]::ExtractToDirectory($archive,$destination,$true)
    Write-Host "Verified and extracted $name within the project."
}
