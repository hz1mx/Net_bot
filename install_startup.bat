@echo off
rem Makes the bot start automatically (minimized) every time you sign in to Windows.
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
(
  echo @echo off
  echo start "Net Academy bot" /min "%~dp0run_bot.bat"
) > "%STARTUP%\net_academy_bot.bat"
echo Done. The bot will start automatically when you sign in to Windows.
echo To start it now, double-click run_bot.bat
pause
