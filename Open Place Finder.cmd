@echo off
cd /d "%~dp0"
uv run python -m placefinder.web
if errorlevel 1 pause
