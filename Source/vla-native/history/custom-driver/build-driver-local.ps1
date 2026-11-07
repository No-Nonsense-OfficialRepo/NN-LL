[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
& (Join-Path $PSScriptRoot 'verify-source.ps1')
$lock = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'wdk-lock.json') -Raw | ConvertFrom-Json
$version = $lock.package_version
$kit = $lock.kit_version
$packages = Join-Path $PSScriptRoot 'out\wdk-packages'
$wdk = Join-Path $packages "Microsoft.Windows.WDK.x64.$version\c"
$sdk = Join-Path $packages "microsoft.windows.sdk.cpp.$version\c"
$sdk64 = Join-Path $packages "microsoft.windows.sdk.cpp.x64.$version\c"
if (!(Test-Path -LiteralPath (Join-Path $wdk "Include\$kit\km\ndis.h"))) {
    throw 'Local WDK packages are absent. Run acquire-wdk.mjs and expand-wdk.ps1 first.'
}
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$visualStudio = (& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1)
if (!$visualStudio) { throw 'An installed x64 MSVC compiler is required.' }
$devcmd = Join-Path $visualStudio 'Common7\Tools\VsDevCmd.bat'
$start = [Diagnostics.ProcessStartInfo]::new()
$start.FileName = $env:ComSpec
$start.Arguments = '/d /s /c ""'+$devcmd+'" -no_logo -arch=x64 -host_arch=x64 >nul && set"'
$start.UseShellExecute = $false
$start.CreateNoWindow = $true
$start.RedirectStandardOutput = $true
$process = [Diagnostics.Process]::Start($start)
$lines = $process.StandardOutput.ReadToEnd() -split "`r?`n"
$process.WaitForExit()
if ($process.ExitCode) { throw 'Could not initialize the installed compiler environment.' }
foreach ($line in $lines) {
    $separator = $line.IndexOf('=')
    if ($separator -gt 0) { [Environment]::SetEnvironmentVariable($line.Substring(0,$separator),$line.Substring($separator+1),'Process') }
}
$compiler = (Get-Command cl.exe).Source
$linker = (Get-Command link.exe).Source
$resourceCompiler = Join-Path $sdk "bin\$kit\x64\rc.exe"
$source = Join-Path $PSScriptRoot 'upstream\windows\TapDriver6'
$output = Join-Path $PSScriptRoot 'out\driver-unsigned'
$objects = Join-Path $PSScriptRoot 'out\driver-local-obj'
New-Item -ItemType Directory -Path $output,$objects -Force | Out-Null
[xml]$project = [IO.File]::ReadAllText((Join-Path $source 'TapDriver6.vcxproj'))
$ns = [Xml.XmlNamespaceManager]::new($project.NameTable)
$ns.AddNamespace('m','http://schemas.microsoft.com/developer/msbuild/2003')
$sources = @($project.SelectNodes('//m:ClCompile[@Include]',$ns) | ForEach-Object { Join-Path $source $_.Include })
$arguments = [Collections.Generic.List[string]]::new()
@('/nologo','/c','/TC','/kernel','/O2','/Oi','/GS','/Gy','/Zl','/W3','/wd4996','/MP4','/Fo.\','/d2epilogunwind',
 '/D_WIN64','/D_AMD64_','/DAMD64','/DWIN32_LEAN_AND_MEAN','/D_WIN32_WINNT=0x0A00','/DNTDDI_VERSION=0x0A000000','/DNTSTRSAFE_LIB','/DNDEBUG') | ForEach-Object { $arguments.Add($_) }
foreach ($include in @((Join-Path $wdk "Include\$kit\km"),(Join-Path $wdk "Include\$kit\km\crt"),(Join-Path $sdk "Include\$kit\shared"),(Join-Path $sdk "Include\$kit\ucrt"),$source)) { $arguments.Add('/I"'+$include+'"') }
foreach ($file in $sources) { $arguments.Add('"'+$file+'"') }
$rsp = Join-Path $objects 'compile.rsp'
[IO.File]::WriteAllLines($rsp,$arguments,[Text.UTF8Encoding]::new($false))
Push-Location $objects
try {
    & $compiler ('@'+$rsp) *> (Join-Path $PSScriptRoot 'build-driver-local.log')
    if ($LASTEXITCODE) { throw 'Kernel source compilation failed; see build-driver-local.log.' }
    $resource = Join-Path $objects 'vlatap.res'
    & $resourceCompiler /nologo /d _WIN64 /i $source /i (Join-Path $sdk "Include\$kit\um") /i (Join-Path $sdk "Include\$kit\shared") /fo $resource (Join-Path $source 'resource.rc') *>> (Join-Path $PSScriptRoot 'build-driver-local.log')
    if ($LASTEXITCODE) { throw 'Driver resource compilation failed; see build-driver-local.log.' }
    $linkArguments = [Collections.Generic.List[string]]::new()
    @('/NOLOGO','/DRIVER','/KERNEL','/SUBSYSTEM:NATIVE,10.00','/MACHINE:X64','/ENTRY:GsDriverEntry','/NODEFAULTLIB','/OPT:REF','/OPT:ICF','/DYNAMICBASE','/NXCOMPAT','/INTEGRITYCHECK','/RELEASE') | ForEach-Object { $linkArguments.Add($_) }
    $linkArguments.Add('/OUT:"'+(Join-Path $output 'vlatap.sys')+'"')
    $linkArguments.Add('/LIBPATH:"'+(Join-Path $wdk "Lib\$kit\km\x64")+'"')
    foreach ($file in $sources) { $linkArguments.Add('"'+(Join-Path $objects ([IO.Path]::GetFileNameWithoutExtension($file)+'.obj'))+'"') }
    $linkArguments.Add('"'+$resource+'"')
    @('ntoskrnl.lib','hal.lib','wmilib.lib','ndis.lib','ntstrsafe.lib','wdmsec.lib','libcntpr.lib','BufferOverflowFastFailK.lib') | ForEach-Object { $linkArguments.Add($_) }
    $linkRsp = Join-Path $objects 'link.rsp'
    [IO.File]::WriteAllLines($linkRsp,$linkArguments,[Text.UTF8Encoding]::new($false))
    & $linker ('@'+$linkRsp) *>> (Join-Path $PSScriptRoot 'build-driver-local.log')
    if ($LASTEXITCODE) { throw 'Kernel driver link failed; see build-driver-local.log.' }
} finally { Pop-Location }
Copy-Item -LiteralPath (Join-Path $source 'vlatap.inf') -Destination (Join-Path $output 'vlatap.inf')
$infverif = Join-Path $wdk "tools\$kit\x64\infverif.exe"
foreach ($mode in @('h','w')) {
    & $infverif ('/'+$mode) /v (Join-Path $output 'vlatap.inf') *> (Join-Path $output ('infverif-'+$mode+'.log'))
    if ($LASTEXITCODE) { throw "INF validation /$mode failed; see output logs." }
}
$image = [IO.File]::ReadAllBytes((Join-Path $output 'vlatap.sys'))
$pe = [BitConverter]::ToInt32($image,0x3c)
$optional = $pe+24
$machine = [BitConverter]::ToUInt16($image,$pe+4)
$subsystem = [BitConverter]::ToUInt16($image,$optional+68)
$certificateSize = [BitConverter]::ToUInt32($image,$optional+112+4*8+4)
if ($machine -ne 0x8664 -or $subsystem -ne 1 -or $certificateSize -ne 0) {
    throw 'Built image did not match the expected unsigned x64 Native driver metadata.'
}
$dumpbin = (Get-Command dumpbin.exe).Source
& $dumpbin /headers /imports (Join-Path $output 'vlatap.sys') *> (Join-Path $output 'pe-inspection.txt')
if ($LASTEXITCODE) { throw 'Static kernel PE inspection failed.' }
$metadata = (Get-Item -LiteralPath (Join-Path $output 'vlatap.sys')).VersionInfo
if ($metadata.CompanyName -cne 'LAN Launcher VLA' -or $metadata.OriginalFilename -cne 'vlatap.sys' -or $metadata.ProductName -cne 'VLA - Virtual LAN Adaptor') {
    throw 'Driver resource identity differs from the VLA contract.'
}
$hashes = [ordered]@{}
foreach ($name in @('vlatap.sys','vlatap.inf')) { $hashes[$name]=(Get-FileHash -LiteralPath (Join-Path $output $name) -Algorithm SHA256).Hash.ToLowerInvariant() }
[ordered]@{result='built-and-statically-validated';architecture='x64';native_subsystem=$true;certificate_directory_bytes=$certificateSize;infverif_h=$true;infverif_w=$true;wdk_package_version=$version;kit_version=$kit;files=$hashes;driver_loaded=$false;runtime_tested=$false;production_signed=$false;catalog_created=$false} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $output 'build-verification.json') -Encoding utf8
Write-Host "Built unsigned x64 kernel driver: $output\vlatap.sys"
Write-Host 'Passed static PE/resource checks and Microsoft InfVerif /h and /w.'
Write-Host 'No catalog, signing, installation, driver loading or runtime test was performed.'
