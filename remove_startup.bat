@echo off
rem Stops the bot from starting automatically with Windows.
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\net_academy_bot.bat" 2>nul
echo Done. The bot will no longer start with Windows.
pause
