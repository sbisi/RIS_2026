@echo off
cd /d %~dp0\..
py -m venv .venv
call .venv\Scriptsctivate
python -m pip install --upgrade pip
pip install -r requirements.txt
copy /Y .env.example .env
pause
