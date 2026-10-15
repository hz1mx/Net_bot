@echo off
rem Runs the Net Academy bot and restarts it if it stops (crash, network drop, ...).
cd /d "%~dp0"
title Net Academy bot
rem Written by install_boot_task.bat: full paths, since the background task does not see your own PATH.
if exist service_paths.bat call service_paths.bat
:loop
if defined BOT_PYTHON ("%BOT_PYTHON%" bot.py) else (py -3.13 bot.py)
rem Exit code 3 means another copy is already running, so there is nothing to restart.
if %errorlevel%==3 exit /b
echo.
echo Bot stopped. Restarting in 30 seconds... (close this window to stop it)
rem ping instead of timeout: timeout fails when there is no console, as in the background task.
ping -n 31 127.0.0.1 >nul
goto loop
