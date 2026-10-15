@echo off
rem Starts the bot in the background whenever the computer turns on, even before anyone signs in
rem (for example after a Windows Update restart at night). Needs no password. Run as administrator.
net session >nul 2>&1
if errorlevel 1 (
  echo Right-click this file and choose "Run as administrator".
  pause
  exit /b 1
)
cd /d "%~dp0"
rem The task runs as the system account, so save the full paths of your Python and browser now.
set "PYEXE="
for /f "delims=" %%p in ('py -3.13 -c "import sys; print(sys.executable)"') do set "PYEXE=%%p"
if not defined PYEXE (
  echo Could not find Python 3.13. Run:  py install 3.13
  pause
  exit /b 1
)
(
  echo set "BOT_PYTHON=%PYEXE%"
  echo set "PLAYWRIGHT_BROWSERS_PATH=%LOCALAPPDATA%\ms-playwright"
) > service_paths.bat
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d='%~dp0'; $a=New-ScheduledTaskAction -Execute ($d+'run_bot.bat') -WorkingDirectory $d; $t=New-ScheduledTaskTrigger -AtStartup; $t.Delay='PT1M'; $s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable; $p=New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount; Register-ScheduledTask -TaskName 'NetAcademyBot' -Action $a -Trigger $t -Settings $s -Principal $p -Force | Out-Null"
if errorlevel 1 (
  echo Failed. Nothing was changed.
  pause
  exit /b 1
)
rem The boot task replaces the sign-in shortcut, so remove that if it exists.
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\net_academy_bot.bat" 2>nul
schtasks /run /tn NetAcademyBot >nul
echo Done. The bot is now running in the background, and will start by itself whenever the computer turns on.
echo Send /check to the bot in Telegram to make sure it answers.
pause
