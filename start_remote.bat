@echo off
rem Keeps a Claude Code Remote Control session open in this folder, so you can manage the bot
rem from the Claude app on your phone. Restarts it if it stops.
cd /d "%~dp0"
title Claude remote control - Net bot
set "PATH=%USERPROFILE%\.local\bin;%ProgramFiles%\Git\cmd;%PATH%"
:loop
claude remote-control --name "Net Bot"
echo.
echo Remote control stopped. Restarting in 30 seconds... (close this window to stop it)
ping -n 31 127.0.0.1 >nul
goto loop
