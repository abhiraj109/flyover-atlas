@echo off
cd /d "%~dp0"
uv run python -m placefinder.gui
if errorlevel 1 pause
