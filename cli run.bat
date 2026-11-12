@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem Primary entry point: hand the arguments to the launcher, which takes the
rem interpreter from config.json or AMS_PYTHON (asking on first run) and runs
rem the CLI in this console.
if exist "%~dp0AnimeMosaicStudioLauncher.exe" (
    "%~dp0AnimeMosaicStudioLauncher.exe" --cli %*
    goto :finish
)

rem Fallback for a checkout without the exe.
call "%~dp0_python_env.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
"%PYC%" -m anime_mosaic.cli %*

:finish
set "RC=%ERRORLEVEL%"
pause
exit /b %RC%
