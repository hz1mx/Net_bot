@echo off
rem Stops the background bot and removes the start-on-boot task. Must be run as administrator.
net session >nul 2>&1
if errorlevel 1 (
  echo Right-click this file and choose "Run as administrator".
  pause
  exit /b 1
)
schtasks /end /tn NetAcademyBot >nul 2>&1
schtasks /delete /tn NetAcademyBot /f
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*bot.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Done. The bot is stopped and will no longer start on boot.
pause
