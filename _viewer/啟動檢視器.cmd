@echo off
REM Keep this file pure ASCII: cmd.exe mis-parses UTF-8 batch files.
REM All messages are printed by launch.py instead.
chcp 65001 >nul
cd /d "%~dp0"
python launch.py
if errorlevel 1 pause
