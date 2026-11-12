@echo off
rem Shared interpreter lookup for the batch launchers.  Works with or without
rem the compiled launcher: sets PYW (windowed) and PYC (console) for the caller.
rem
rem Order -- nothing is scanned on disk:
rem   1. config.json -> python_exe (the launcher writes it; you can edit it)
rem   2. AMS_PYTHON
rem   3. python.exe / pythonw.exe on PATH, if it actually starts
rem   4. stop and tell the user what to configure
setlocal
set "PYW="
set "PYC="
set "PYPROBE="

rem 1a. Ask the compiled launcher when it exists; it is the authoritative reader.
if exist "%~dp0AnimeMosaicStudioLauncher.exe" goto :probe_exe
if exist "%~dp0config.json" goto :probe_json
goto :probe_done

:probe_exe
set "PYPROBE=%TEMP%\ams_py_%RANDOM%%RANDOM%.txt"
"%~dp0AnimeMosaicStudioLauncher.exe" --print-python > "%PYPROBE%" 2>nul
if exist "%PYPROBE%" set /p PYW=<"%PYPROBE%"
if exist "%PYPROBE%" del /q "%PYPROBE%" >nul 2>nul
if defined PYW if not exist "%PYW%" set "PYW="
if defined PYW goto :probe_done

rem 1b. No exe (source checkout): read python_exe out of config.json directly.
:probe_json
set "PYPROBE=%TEMP%\ams_py_%RANDOM%%RANDOM%.txt"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$c = ConvertFrom-Json (Get-Content -Raw -LiteralPath '%~dp0config.json'); if ($c.python_exe) { [IO.File]::WriteAllText('%PYPROBE%', $c.python_exe) }" >nul 2>nul
if exist "%PYPROBE%" set /p PYW=<"%PYPROBE%"
if exist "%PYPROBE%" del /q "%PYPROBE%" >nul 2>nul
if defined PYW if not exist "%PYW%" set "PYW="

:probe_done
rem 2. Explicit environment override.
if not defined PYW if defined AMS_PYTHON if exist "%AMS_PYTHON%" set "PYW=%AMS_PYTHON%"

rem 3. Whatever interpreter this Windows already offers: PATH first, then the
rem    py launcher.  Each candidate has to start, so the Microsoft Store
rem    placeholder is skipped.
if defined PYW goto :have_python
for /f "delims=" %%P in ('where pythonw.exe 2^>nul') do if not defined PYW call :try_path "%%P"
for /f "delims=" %%P in ('where python.exe 2^>nul') do if not defined PYW call :try_path "%%P"
if defined PYW goto :have_python
for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do if not defined PYW call :try_path "%%P"

:have_python
if not defined PYW goto :no_python

rem 3. A configured python.exe should still start without a console window.
if /i "%PYW:~-10%"=="python.exe" if exist "%PYW:~0,-10%pythonw.exe" set "PYW=%PYW:~0,-10%pythonw.exe"

set "PYC=%PYW:pythonw.exe=python.exe%"
if not exist "%PYC%" set "PYC=%PYW%"

endlocal & set "PYW=%PYW%" & set "PYC=%PYC%"
exit /b 0

:try_path
if not exist "%~1" exit /b 0
"%~1" -c "import sys" >nul 2>nul && set "PYW=%~1"
exit /b 0

:no_python
echo [error] No Python interpreter is configured yet.
echo         Set one of these, then run this script again:
echo           - config.json:   "python_exe": "D:\\path\\to\\python.exe"
echo           - environment:   set AMS_PYTHON=D:\\path\\to\\python.exe
echo           - or run AnimeMosaicStudioLauncher.exe once and pick it there.
endlocal & exit /b 1
