@echo off
chcp 65001 >nul
title AbiiBot - Activator
cd /d "%~dp0"

set PYCMD=
where py >nul 2>nul && set PYCMD=py -3
where python >nul 2>nul && if not defined PYCMD set PYCMD=python

if not defined PYCMD (
  echo.
  echo  [!] Python not found.
  echo      1. Install Python 3.10+ from:  https://www.python.org/downloads/
  echo      2. IMPORTANT: tick "Add python.exe to PATH" during install.
  echo      3. Then double-click activate.bat again.
  echo.
  pause
  exit /b 1
)

%PYCMD% -X utf8 scripts\activate_windows.py %*
pause
