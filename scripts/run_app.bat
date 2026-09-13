@echo off
cd /d %~dp0\..
call .venv\Scriptsctivate
python app.py
pause
