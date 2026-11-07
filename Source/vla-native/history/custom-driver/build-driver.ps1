[CmdletBinding()]
param([string]$MSBuildPath, [string]$SdkVersion)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (!$MSBuildPath -and !$SdkVersion -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'out\wdk-packages\microsoft.windows.wdk.x64.10.0.28000.2526\c\Include\10.0.28000.0\km\ndis.h'))) {
    & (Join-Path $PSScriptRoot 'build-driver-local.ps1')
    return
}
& (Join-Path $PSScriptRoot 'verify-source.ps1')
$kits = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10'
if (!$SdkVersion) {
    $versions = @(Get-ChildItem -LiteralPath (Join-Path $kits 'Include') -Directory -ErrorAction SilentlyContinue | Where-Object {
        Test-Path -LiteralPath (Join-Path $_.FullName 'km\ndis.h')
    } | Sort-Object Name -Descending)
    if ($versions.Count) { $SdkVersion = $versions[0].Name }
}
if (!$SdkVersion -or !(Test-Path -LiteralPath (Join-Path $kits "Include\$SdkVersion\km\ndis.h"))) {
    throw 'A traditional system WDK was not found. For the project-local build, run node acquire-wdk.mjs, expand-wdk.ps1, then build-driver-local.ps1. No system WDK installation is required.'
}
if (!$MSBuildPath) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    $visualStudio = & $vswhere -latest -products '*' -property installationPath | Select-Object -First 1
    if ($visualStudio) { $MSBuildPath = Join-Path $visualStudio 'MSBuild\Current\Bin\MSBuild.exe' }
}
if (!$MSBuildPath -or !(Test-Path -LiteralPath $MSBuildPath)) { throw 'Pass -MSBuildPath for a Visual Studio installation integrated with the WDK.' }
$output = Join-Path $PSScriptRoot 'out\driver-unsigned'
$objects = Join-Path $PSScriptRoot 'out\driver-obj'
New-Item -ItemType Directory -Path $output,$objects -Force | Out-Null
$project = Join-Path $PSScriptRoot 'upstream\windows\TapDriver6\TapDriver6.vcxproj'
# Build only. No installation, certificate creation or signing-policy changes.
& $MSBuildPath $project /t:Build /m /nologo /v:minimal '/p:Configuration=Win8 Release' /p:Platform=x64 /p:TargetVersion=Windows10 "/p:WindowsTargetPlatformVersion=$SdkVersion" "/p:OutDir=$output\" "/p:IntDir=$objects\" /p:SignMode=Off /p:DriverSignMode=Off *> (Join-Path $PSScriptRoot 'build-driver.log')
if ($LASTEXITCODE) { throw 'Unsigned driver build failed. See vla-native/build-driver.log; WDK compatibility may require further work.' }
Write-Host "Unsigned driver build output: $output"
Write-Host 'The renamed package requires validation and Microsoft production signing before distribution or loading.'
