@echo off
setlocal
title Build Latest LAN Launcher
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Source\scripts\build_latest.ps1"
set "BUILD_EXIT=%ERRORLEVEL%"
echo.
if not "%BUILD_EXIT%"=="0" (
    echo Build failed. Read the error above and Source\build\logs\build-latest-lan-launcher.log.
) else (
    echo Build complete. The new release folder is inside Releases.
)
pause
exit /b %BUILD_EXIT%
