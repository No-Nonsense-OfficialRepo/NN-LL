@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Connection Check.ps1"
echo.
echo Attach Connection Report.json when requesting connection help.
pause
