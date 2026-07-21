@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo [小u] 正在检查 Windows 和 Python 3.12...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\check_environment.ps1"
if errorlevel 1 goto :failed

echo [小u] 正在准备运行环境，第一次可能需要几分钟...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\setup_environment.ps1"
if errorlevel 1 goto :failed

echo [小u] 正在执行完整检查...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\test.ps1"
if errorlevel 1 goto :failed

echo [小u] 正在生成可以双击运行的 Windows 程序...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\scripts\build.ps1" -IncludeUserAssets
if errorlevel 1 goto :failed

echo.
echo 生成完成。
echo 请打开: dist\XiaoU\XiaoU.exe
start "" "%~dp0dist\XiaoU"
pause
exit /b 0

:failed
echo.
echo 生成未完成。请按上方中文提示安装缺少的软件，然后再次双击本文件。
pause
exit /b 1
