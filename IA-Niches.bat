@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
python "01-scripts\launcher.py"
echo.
pause
