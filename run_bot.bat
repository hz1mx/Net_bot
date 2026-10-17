@echo off
rem Runs the Net Academy bot and restarts it if it stops (crash, network drop, update, ...).
cd /d "%~dp0"
title Net Academy bot
rem Written by install_boot_task.bat: full paths, since the background task does not see your own PATH.
if exist service_paths.bat call service_paths.bat
:loop
if defined BOT_PYTHON ("%BOT_PYTHON%" bot.py) else (py -3.13 bot.py)
set "CODE=%errorlevel%"
rem 3: another copy is already running, so there is nothing to restart.
if "%CODE%"=="3" exit /b
rem 4: bot.py changed on disk; start the new version right away.
if "%CODE%"=="4" goto loop
rem It crashed. If bot.py is not the last version that started fine, put that one back.
if exist bot.py.good (
  fc /b bot.py bot.py.good >nul 2>&1 || (
    copy /y bot.py.good bot.py >nul
    echo failed> update_failed.flag
    echo Restored the last working bot.py
  )
)
echo.
echo Bot stopped. Restarting in 30 seconds... (close this window to stop it)
rem ping instead of timeout: timeout fails when there is no console, as in the background task.
ping -n 31 127.0.0.1 >nul
goto loop
