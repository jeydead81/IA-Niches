@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
echo Demarrage de l'interface IA-Niches...
start "IA-Niches serveur" cmd /c "python web\server.py"
timeout /t 3 >nul
start "" http://127.0.0.1:8000
echo.
echo Interface ouverte sur http://127.0.0.1:8000
echo (Ferme la fenetre "IA-Niches serveur" pour arreter.)
