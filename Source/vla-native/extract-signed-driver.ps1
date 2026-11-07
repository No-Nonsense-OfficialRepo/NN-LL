[CmdletBinding()]
param([string]$MsiPath = (Join-Path (Split-Path $PSScriptRoot) 'vendor\ZeroTierOne.msi'))
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$MsiPath = (Resolve-Path -LiteralPath $MsiPath).Path
$lock = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'shared-driver-lock.json') -Raw | ConvertFrom-Json
$expectedMsi = $lock.source_msi_sha256
if ((Get-FileHash -LiteralPath $MsiPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $expectedMsi) { throw 'MSI differs from the inspected original package; refusing unverified extraction.' }
if (!('VlaMsiReadOnly' -as [type])) {
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class VlaMsiReadOnly {
  [DllImport("msi.dll", CharSet=CharSet.Unicode)] static extern uint MsiOpenDatabaseW(string path, IntPtr mode, out uint db);
  [DllImport("msi.dll", CharSet=CharSet.Unicode)] static extern uint MsiDatabaseOpenViewW(uint db, string sql, out uint view);
  [DllImport("msi.dll")] static extern uint MsiViewExecute(uint view, uint record);
  [DllImport("msi.dll")] static extern uint MsiViewFetch(uint view, out uint record);
  [DllImport("msi.dll")] static extern uint MsiRecordReadStream(uint record, uint field, [Out] byte[] buffer, ref uint bytes);
  [DllImport("msi.dll")] static extern uint MsiCloseHandle(uint handle);
  static void Check(uint result) { if (result != 0) throw new Win32Exception((int)result); }
  public static void ExtractCabinet(string msi, string destination) {
    uint db=0, view=0, record=0;
    try {
      Check(MsiOpenDatabaseW(msi, IntPtr.Zero, out db)); // MSIDBOPEN_READONLY
      Check(MsiDatabaseOpenViewW(db,"SELECT `Data` FROM `_Streams` WHERE `Name`='disk1.cab'",out view));
      Check(MsiViewExecute(view,0)); Check(MsiViewFetch(view,out record));
      using (var stream = new FileStream(destination,FileMode.Create,FileAccess.Write)) {
        byte[] buffer = new byte[65536];
        while (true) { uint bytes=(uint)buffer.Length; Check(MsiRecordReadStream(record,1,buffer,ref bytes)); if(bytes==0)break; stream.Write(buffer,0,(int)bytes); }
      }
    } finally { if(record!=0)MsiCloseHandle(record);if(view!=0)MsiCloseHandle(view);if(db!=0)MsiCloseHandle(db); }
  }
}
'@
}
$root = Join-Path $PSScriptRoot 'out\shared-driver-source'
$driver = Join-Path $root 'driver'
New-Item -ItemType Directory -Path $driver -Force | Out-Null
$cabinet = Join-Path $root 'disk1.cab'
# Reads the database stream, then expands three x64 cabinet members. No msiexec,
# installer actions, driver installation, services or package registration.
[VlaMsiReadOnly]::ExtractCabinet($MsiPath,$cabinet)
$expand = Join-Path $env:SystemRoot 'System32\expand.exe'
foreach ($name in @('zttap300.inf','zttap300.cat','zttap300.sys')) {
    & $expand ('-F:'+$name) $cabinet $driver *> (Join-Path $root ('expand-'+$name+'.log'))
    if ($LASTEXITCODE -or !(Test-Path -LiteralPath (Join-Path $driver $name))) { throw "Read-only cabinet extraction failed for $name." }
}
$files=[ordered]@{}
foreach($name in @('zttap300.inf','zttap300.cat','zttap300.sys')) { $files[$name]=(Get-FileHash -LiteralPath (Join-Path $driver $name) -Algorithm SHA256).Hash.ToLowerInvariant() }
foreach($entry in $lock.files.PSObject.Properties) { if($files[$entry.Name] -cne $entry.Value){throw "Extracted driver differs from the unchanged signed pin: $($entry.Name)"} }
[ordered]@{source_msi_sha256=$expectedMsi;source_product_version='1.16.2';source_component='zttap300.inf';source_component_condition='VersionNT64 AND NOT AiArm64';architecture='x64';unchanged_driver_files=$files;msi_installed=$false;driver_loaded=$false} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $root 'extraction.json') -Encoding utf8
Write-Host "Extracted unchanged x64 signed-driver files from the MSI: $driver"
