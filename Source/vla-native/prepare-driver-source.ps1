[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
& (Join-Path $PSScriptRoot 'verify-source.ps1')
$source=Join-Path $PSScriptRoot 'upstream'
$notices=Join-Path $PSScriptRoot 'out\shared-driver-source\notices'
New-Item -ItemType Directory -Path $notices -Force | Out-Null
$archive=Join-Path $notices 'zttap300-original-source.zip'
& git -C $source archive --format=zip ('--output='+$archive) HEAD windows/TapDriver6
if ($LASTEXITCODE) { throw 'Could not archive the original GPL driver source.' }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'licenses\GPL-2.0-only.txt') -Destination (Join-Path $notices 'zttap300-GPL-2.0.txt')
$text=@'
UNCHANGED SHARED ZEROTIER TAP DRIVER — SOURCE AND LICENSE

zttap300.inf / zttap300.cat / zttap300.sys retain original ZeroTier/OpenVPN
names, copyright notices and signatures. Their source-file/INF notices state
GNU General Public License version 2. The full GPL text is supplied alongside.

The files were read-only extracted from ZeroTierOne.msi ProductVersion 1.16.2,
MSI SHA-256 42514072b0fe44b8f66e0395bcd23a0b1d1642c28ed00831f1527b2f41b14670.
All three extracted files are byte-identical to the x64 prebuilt files in the
official ZeroTierOne 1.14.2 source tree (ext/bin/tap-windows-ndis6/x64).

zttap300-original-source.zip contains the unmodified windows/TapDriver6 source
and original build project from commit 185a3a2c76e6bf1b1c0415871f43076638eb007c.
That driver source and the x64 prebuilt files have no changes between the
official 1.14.2 and 1.16.2 source tags. The archive includes the GPL text as COPYING.
Original build files reference standard Microsoft Visual Studio/WDK tooling.
The signed binaries are used unchanged; no reproducible-binary claim is made.

Upstream source:
https://github.com/zerotier/ZeroTierOne/tree/185a3a2c76e6bf1b1c0415871f43076638eb007c/windows/TapDriver6

LAN Launcher VLA owns only its private service, configuration and individually
created/tagged/recorded adapter instances. The shared zttap300 kernel service
and Driver Store package are borrowed and are never explicitly deleted by VLA.
No endorsement by ZeroTier, OpenVPN or Microsoft is implied.
'@
[IO.File]::WriteAllText((Join-Path $notices 'zttap300-NOTICE.txt'),$text,[Text.UTF8Encoding]::new($false))
$zip=[IO.Compression.ZipFile]::Open($archive,[IO.Compression.ZipArchiveMode]::Update)
try {
    [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip,(Join-Path $notices 'zttap300-GPL-2.0.txt'),'windows/TapDriver6/COPYING') | Out-Null
    $entry=$zip.CreateEntry('SOURCE-REFERENCE.txt')
    $writer=[IO.StreamWriter]::new($entry.Open(),[Text.UTF8Encoding]::new($false))
    try {$writer.Write($text)} finally {$writer.Dispose()}
} finally {$zip.Dispose()}
Write-Host "Prepared original shared-driver source/license bundle: $notices"
