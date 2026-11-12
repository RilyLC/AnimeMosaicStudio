@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

call "%~dp0_python_env.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

echo 使用 Python：%PYC%
echo 建议手动安装 CUDA 版 torch 以获得更快的检测速度。
echo.
echo.
"%PYC%" -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo [错误] 依赖安装失败，请检查网络。
) else (
    echo.
    echo 依赖安装完成。
)
pause
