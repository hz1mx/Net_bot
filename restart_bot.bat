@echo off
rem Restarts the background bot, e.g. after replacing bot.py with a new version. Run as administrator.
net session >nul 2>&1
if errorlevel 1 (
  echo Right-click this file and choose "Run as administrator".
  pause
  exit /b 1
)
schtasks /end /tn NetAcademyBot >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*bot.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
schtasks /run /tn NetAcademyBot
if errorlevel 1 (
  echo The background task is not installed. Run install_boot_task.bat as administrator first.
  pause
  exit /b 1
)
echo Done. The bot restarted. Send it /check in Telegram to make sure it answers.
pause
