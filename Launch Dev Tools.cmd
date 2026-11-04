@echo off
cd /d "%~dp0"
python steam_cultivator_gui.py --devtools
if errorlevel 1 pause
