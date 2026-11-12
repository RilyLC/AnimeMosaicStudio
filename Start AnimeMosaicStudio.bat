@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem Primary entry point: the compiled launcher owns interpreter resolution,
rem dependency probing and config.json handling.
if exist "%~dp0AnimeMosaicStudioLauncher.exe" (
    start "" "%~dp0AnimeMosaicStudioLauncher.exe"
    exit /b 0
)

rem Fallback for a checkout without the exe (development, first run).
call "%~dp0_python_env.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

"%PYC%" -c "import PySide6, numpy, cv2, PIL, requests" >nul 2>nul
if errorlevel 1 (
    echo.
    echo 首次运行：缺少运行依赖 ^(PySide6、numpy、opencv、Pillow、requests^)。
    echo.
    echo 当前选中的 Python 解释器：
    echo     "%PYC%"
    echo.
    echo 如需更换解释器：修改本目录 config.json 里的 "python_exe" 字段,^(文件不存在就新建一个^)
    echo 马赛克检测速度受到torch版本影响,建议手动安装CUDA版torch。
    echo.
    set /p "AMS_CONTINUE=按回车键开始安装依赖，按 Ctrl+C 取消..."
    ver >nul
    echo.
    "%PYC%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo.
        echo [错误] 依赖安装失败。请检查网络后重试，或手动运行：
        echo        "%PYC%" -m pip install -r requirements.txt
        pause
        exit /b 1
    )
)

start "" "%PYW%" "%~dp0AnimeMosaicStudio.pyw"
