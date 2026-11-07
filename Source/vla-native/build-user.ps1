[CmdletBinding()]
param([string]$SourcePath = (Join-Path $PSScriptRoot 'upstream'))
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$SourcePath = (Resolve-Path -LiteralPath $SourcePath).Path
& (Join-Path $PSScriptRoot 'verify-source.ps1') -SourcePath $SourcePath
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (!(Test-Path -LiteralPath $vswhere)) { throw 'Visual Studio C++ build tools are required.' }
$visualStudio = (& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1)
if (!$visualStudio) { throw 'No installed x64 MSVC toolchain was found.' }
$devcmd = Join-Path $visualStudio 'Common7\Tools\VsDevCmd.bat'
# Capture the toolchain's environment in this process; no machine settings change.
$start = [Diagnostics.ProcessStartInfo]::new()
$start.FileName = $env:ComSpec
$start.Arguments = '/d /s /c ""'+$devcmd+'" -no_logo -arch=x64 -host_arch=x64 >nul && set"'
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.RedirectStandardOutput = $true
$environmentProcess = [Diagnostics.Process]::Start($start)
$environmentLines = $environmentProcess.StandardOutput.ReadToEnd() -split "`r?`n"
$environmentProcess.WaitForExit()
if ($environmentProcess.ExitCode) { throw 'Could not initialize the installed C++ toolchain.' }
foreach ($line in $environmentLines) {
    $separator = $line.IndexOf('=')
    if ($separator -gt 0) {
        [Environment]::SetEnvironmentVariable($line.Substring(0,$separator), $line.Substring($separator+1), 'Process')
    }
}
$compiler = (Get-Command cl.exe -ErrorAction Stop).Source
$output = Join-Path $PSScriptRoot 'out\user'
$objects = Join-Path $PSScriptRoot 'out\direct-obj'
New-Item -ItemType Directory -Path $output,$objects -Force | Out-Null
$projectPath = Join-Path $SourcePath 'windows\ZeroTierOne\ZeroTierOne.vcxproj'
[xml]$project = [IO.File]::ReadAllText($projectPath)
$namespace = [Xml.XmlNamespaceManager]::new($project.NameTable)
$namespace.AddNamespace('m', 'http://schemas.microsoft.com/developer/msbuild/2003')
$sources = @($project.SelectNodes('//m:ClCompile[@Include]', $namespace) | Where-Object {
    $_.Include -notmatch 'selftest\.cpp$'
} | ForEach-Object {
    [IO.Path]::GetFullPath((Join-Path (Split-Path $projectPath) $_.Include))
})
$arguments = [Collections.Generic.List[string]]::new()
@('/nologo','/O2','/Oi','/MT','/EHsc','/std:c++17','/W1','/wd4996','/guard:cf','/MP4','/Fo.\',
  '/DZT_SSO_ENABLED=0','/DZT_EXPORT','/DFD_SETSIZE=1024','/DSTATICLIB','/DZT_SALSA20_SSE','/DZT_USE_MINIUPNPC',
  '/DMINIUPNP_STATICLIB','/DWIN32','/DNOMINMAX','/DZT_BUILD_PLATFORM=2','/DZT_BUILD_ARCHITECTURE=2',
  '/DZT_SOFTWARE_UPDATE_DEFAULT=\"disable\"') | ForEach-Object { $arguments.Add($_) }
foreach ($include in @('ext','ext\prometheus-cpp-lite-1.0\core\include','ext\prometheus-cpp-lite-1.0\simpleapi\include')) {
    $arguments.Add('/I"'+(Join-Path $SourcePath $include)+'"')
}
foreach ($source in $sources) { $arguments.Add('"'+$source+'"') }
$arguments.Add('/Fe"'+(Join-Path $output 'vla-service.exe')+'"')
$arguments.Add('/link')
$arguments.Add('/OPT:REF')
$arguments.Add('/OPT:ICF')
$arguments.Add('/DYNAMICBASE')
$arguments.Add('/NXCOMPAT')
@('wbemuuid.lib','wsock32.lib','ws2_32.lib','Iphlpapi.lib','Rpcrt4.lib','bcrypt.lib','userenv.lib','crypt32.lib','secur32.lib','ncrypt.lib','ntdll.lib') | ForEach-Object { $arguments.Add($_) }
$response = Join-Path $objects 'compile.rsp'
[IO.File]::WriteAllLines($response, $arguments, [Text.UTF8Encoding]::new($false))
Push-Location $objects
try {
    & $compiler ('@'+$response) *> (Join-Path $PSScriptRoot 'build-user.log')
    $exitCode = $LASTEXITCODE
} finally { Pop-Location }
if ($exitCode) { throw "Native user-mode compile failed ($exitCode). See vla-native/build-user.log." }
$executable = Join-Path $output 'vla-service.exe'
$lock = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'source-lock.json') -Raw | ConvertFrom-Json
$binary = [IO.File]::ReadAllBytes($executable)
if ([Text.Encoding]::ASCII.GetString($binary).IndexOf('LanLauncherVLA') -lt 0) { throw 'Private SCM service identity is absent from the built executable.' }
[ordered]@{
    schema=1;backend='lan-launcher-vla';service_name='LanLauncherVLA'
    display_name='VLA - Virtual LAN Adaptor';executable='vla-service.exe';api_port=47993
    driver_mode='shared-signed';driver_service='zttap300';driver_component='zttap300'
    source_commit=$lock.commit;patch_sha256=$lock.patch_sha256
    executable_sha256=(Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output 'service-provenance.json') -Encoding utf8
Write-Host "Built unsigned user-mode artifact: $executable"
Write-Host 'Emitted service-provenance.json for the unchanged, shared signed zttap300 driver path.'
