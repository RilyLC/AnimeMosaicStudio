@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem Builds AnimeMosaicStudioLauncher.exe from launcher.py.
rem The launcher is a tiny stdlib-only wrapper: it takes the Python interpreter
rem from config.json or AMS_PYTHON (asking the user to pick one on first run),
rem probes the runtime dependencies and starts AnimeMosaicStudio.pyw.

rem Resolve a console interpreter for the build.
if not defined PYTHON call "%~dp0_python_env.bat"
if not defined PYTHON if defined PYC set "PYTHON=%PYC%"
if not defined PYTHON set "PYTHON=python"

echo 使用 Python：%PYTHON%
echo.

"%PYTHON%" -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo 未找到 PyInstaller，请先安装构建依赖：
    echo     "%PYTHON%" -m pip install -r requirements.txt
    pause
    exit /b 1
)

rem Refresh assets\icon.ico from the in-app mark.  Best effort: a missing
rem PySide6/Pillow only means the exe falls back to the default icon.
if exist "%~dp0tools\make_icon.py" (
    echo 正在生成图标…
    "%PYTHON%" "%~dp0tools\make_icon.py" >nul 2>nul
)

set "ICON_ARG="
if exist "%~dp0assets\icon.ico" set ICON_ARG=--icon "%~dp0assets\icon.ico"

echo 正在构建启动器…
"%PYTHON%" -m PyInstaller ^
    --noconfirm --clean --onefile --console ^
    --name AnimeMosaicStudioLauncher ^
    %ICON_ARG% ^
    --distpath dist --workpath build ^
    launcher.py
if errorlevel 1 (
    echo.
    echo [错误] 构建失败。
    pause
    exit /b 1
)

copy /y "dist\AnimeMosaicStudioLauncher.exe" "AnimeMosaicStudioLauncher.exe" >nul
if errorlevel 1 (
    echo [错误] 无法把 exe 复制到项目根目录。
    pause
    exit /b 1
)

rem Drop everything the build produced besides the launcher itself; the
rem intermediate tree is hundreds of MB and nobody needs it after the copy.
if exist "%~dp0build" rmdir /s /q "%~dp0build"
if exist "%~dp0dist" rmdir /s /q "%~dp0dist"
if exist "%~dp0AnimeMosaicStudioLauncher.spec" del /q "%~dp0AnimeMosaicStudioLauncher.spec"

echo.
echo 构建完成：%~dp0AnimeMosaicStudioLauncher.exe
echo 双击 exe 即可启动界面；--check 可查看解析到的 Python 与依赖状态。
pause
