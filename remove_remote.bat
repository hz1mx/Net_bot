@echo off
rem Stops Remote Control from starting with Windows. Close its window to stop the running one.
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\net_bot_remote.bat" 2>nul
echo Done. Remote Control will no longer start with Windows.
pause
