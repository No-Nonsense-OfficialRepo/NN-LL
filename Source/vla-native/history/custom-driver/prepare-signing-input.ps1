[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
& (Join-Path $PSScriptRoot 'verify-source.ps1')
$lock = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'wdk-lock.json') -Raw | ConvertFrom-Json
$verification = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'out\driver-unsigned\build-verification.json') -Raw | ConvertFrom-Json
$source = Join-Path $PSScriptRoot 'out\driver-unsigned'
$destination = Join-Path $PSScriptRoot 'out\signing-input'
$driverDestination = Join-Path $destination 'driver'
New-Item -ItemType Directory -Path $driverDestination -Force | Out-Null
foreach ($entry in $verification.files.PSObject.Properties) {
    $file = Join-Path $source $entry.Name
    if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entry.Value) { throw 'Unsigned driver output differs from its build verification.' }
    Copy-Item -LiteralPath $file -Destination (Join-Path $driverDestination $entry.Name)
}
$service = Join-Path $PSScriptRoot 'out\user\vla-service.exe'
if (!(Test-Path -LiteralPath $service)) { throw 'Build the unsigned user-mode service before staging signing input.' }
Copy-Item -LiteralPath $service -Destination (Join-Path $destination 'vla-service.exe')
$wdk = Join-Path $PSScriptRoot ('out\wdk-packages\microsoft.windows.wdk.x64.'+$lock.package_version+'\c')
$inf2cat = Join-Path $wdk ('bin\'+$lock.kit_version+'\x86\Inf2Cat.exe')
$os = '10_RS3_X64,10_RS4_X64,10_RS5_X64,10_19H1_X64,10_VB_X64,10_CO_X64,10_NI_X64,10_GE_X64'
# This creates a real, unsigned hash catalog. It does not create a certificate,
# sign anything, install files or change the machine's driver signing policy.
& $inf2cat ('/driver:'+$driverDestination) ('/os:'+$os) /verbose *> (Join-Path $destination 'inf2cat.log')
if ($LASTEXITCODE -or !(Test-Path -LiteralPath (Join-Path $driverDestination 'vlatap.cat'))) { throw 'Microsoft Inf2Cat failed; see out/signing-input/inf2cat.log.' }
$files = [ordered]@{}
foreach ($relative in @('vla-service.exe','driver/vlatap.sys','driver/vlatap.inf','driver/vlatap.cat')) {
    $files[$relative]=(Get-FileHash -LiteralPath (Join-Path $destination $relative) -Algorithm SHA256).Hash.ToLowerInvariant()
}
[ordered]@{purpose='UNSIGNED developer signing input; not a production runtime package';catalog_created_by='Microsoft Inf2Cat';production_signed=$false;installed=$false;runtime_tested=$false;inf2cat_os_identifiers=$os;files=$files} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $destination 'UNSIGNED-ARTIFACTS.json') -Encoding utf8
@'
UNSIGNED DEVELOPMENT ARTIFACTS — DO NOT INSTALL OR DISTRIBUTE AS PRODUCTION

The service executable and kernel driver have no production signatures.
driver/vlatap.cat is a real unsigned Microsoft Inf2Cat-generated hash catalog.
It does not grant Windows kernel trust and is not a Microsoft-signed package.
No service/driver installation, loading, test signing, Secure Boot change or
runtime network test was performed by this staging script.

Use this folder as local input for the publisher's applicable Microsoft driver
submission/signing workflow. Further account setup, signing, validation and
deployment/coexistence testing are required. This folder intentionally has no
production vendor/vla/manifest.json. Preserve the pinned source, patch, driver
corresponding source/build files and component notices when distributing.
'@ | Set-Content -LiteralPath (Join-Path $destination 'UNSIGNED.txt') -Encoding utf8
Write-Host "Staged genuine unsigned service, SYS, INF and CAT: $destination"
Write-Host 'Production signing and actual deployment/coexistence validation remain outstanding.'
