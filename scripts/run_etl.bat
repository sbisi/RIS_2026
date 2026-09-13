@echo off
cd /d %~dp0\..
call .venv\Scriptsctivate
python -m etl.build_database
pause
