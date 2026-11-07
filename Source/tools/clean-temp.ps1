# Removes temporary test and cache files. Safe to run any time.
# Does not touch source, tests, build output, or saved app data.
$root = Split-Path -Parent $PSScriptRoot
$src = Join-Path $root 'Source'
Remove-Item -LiteralPath (Join-Path $src '.pytest_cache') -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath $src -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Write-Output 'Temporary test and cache files removed.'
