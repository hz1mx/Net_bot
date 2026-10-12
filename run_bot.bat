@echo off
rem Runs the Net Academy bot and restarts it if it stops (crash, network drop, ...).
cd /d "%~dp0"
title Net Academy bot
:loop
py -3.13 bot.py
echo.
echo Bot stopped. Restarting in 30 seconds... (close this window to stop it)
timeout /t 30 /nobreak >nul
goto loop
