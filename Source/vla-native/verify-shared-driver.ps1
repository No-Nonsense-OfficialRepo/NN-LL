[CmdletBinding()]
param([string]$SignToolPath)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$lock = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'shared-driver-lock.json') -Raw | ConvertFrom-Json
$root = Join-Path $PSScriptRoot 'out\shared-driver-source'
$driver = Join-Path $root 'driver'
foreach ($entry in $lock.files.PSObject.Properties) {
    if ((Get-FileHash -LiteralPath (Join-Path $driver $entry.Name) -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entry.Value) { throw "Original signed driver file differs from pin: $($entry.Name)" }
}
if (!$SignToolPath) {
    $local = Join-Path $PSScriptRoot 'out\wdk-packages\microsoft.windows.sdk.cpp.10.0.28000.2526\c\bin\10.0.28000.0\x64\signtool.exe'
    if (Test-Path -LiteralPath $local) { $SignToolPath=$local }
    else {
        $sdk=Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
        $candidate=@(Get-ChildItem -LiteralPath $sdk -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Where-Object {Test-Path -LiteralPath (Join-Path $_.FullName 'x64\signtool.exe')})
        if ($candidate.Count) { $SignToolPath=Join-Path $candidate[0].FullName 'x64\signtool.exe' }
    }
}
if (!$SignToolPath -or !(Test-Path -LiteralPath $SignToolPath)) { throw 'Pass an installed Microsoft SignTool path for static catalog/kernel-policy verification.' }
$catalog=Join-Path $driver 'zttap300.cat'
foreach ($name in @('zttap300.sys','zttap300.inf')) {
    & $SignToolPath verify /kp /v /c $catalog (Join-Path $driver $name) *> (Join-Path $root ('signature-'+$name+'.log'))
    if ($LASTEXITCODE) { throw "Microsoft SignTool kernel-policy/catalog verification failed: $name" }
}
[ordered]@{result='static-cryptographic-verification-passed';driver_mode=$lock.driver_mode;source_msi_sha256=$lock.source_msi_sha256;driver_files=$lock.files;catalog_membership_inf=$true;catalog_membership_sys=$true;signtool_kernel_policy=$true;driver_installed=$false;driver_loaded=$false;current_windows_runtime_policy_acceptance='not-tested';coexistence='not-tested'} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $root 'signature-verification.json') -Encoding utf8
Write-Host 'Original signed driver hashes, INF/SYS catalog membership and SignTool /kp checks passed.'
Write-Host 'This static result does not establish load acceptance, HVCI compatibility or runtime coexistence.'
