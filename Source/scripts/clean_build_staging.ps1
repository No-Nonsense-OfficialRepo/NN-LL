param()
$ErrorActionPreference = 'Stop'
$buildRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\build')).TrimEnd('\')
$target = Join-Path $buildRoot 'package_stage'
if (Test-Path -LiteralPath $target) {
    $resolved = (Resolve-Path -LiteralPath $target).Path
    if ($resolved -ne $target -or !$resolved.StartsWith($buildRoot+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected staging cleanup path.' }
    $items = @((Get-Item -LiteralPath $target -Force)) + @(Get-ChildItem -LiteralPath $target -Recurse -Force)
    if ($items | Where-Object {$_.Attributes -band [IO.FileAttributes]::ReparsePoint}) { throw 'Linked build staging content refused.' }
    $bytes = ($items | Where-Object {!$_.PSIsContainer} | Measure-Object Length -Sum).Sum
    Remove-Item -LiteralPath $target -Recurse -Force
    Write-Host ('Removed temporary packaging copies: {0:N1} MiB' -f ($bytes/1MB))
}
