@echo off
rem Starts the bot in the background whenever the computer turns on, even before anyone signs in
rem (for example after a Windows Update restart at night). Must be run as administrator.
net session >nul 2>&1
if errorlevel 1 (
  echo Right-click this file and choose "Run as administrator".
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d='%~dp0'; $a=New-ScheduledTaskAction -Execute ($d+'run_bot.bat') -WorkingDirectory $d; $t=New-ScheduledTaskTrigger -AtStartup; $t.Delay='PT1M'; $s=New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable; $c=Get-Credential -UserName ($env:USERDOMAIN+'\'+$env:USERNAME) -Message 'Your Windows password (not the PIN)'; if(-not $c){exit 1}; Register-ScheduledTask -TaskName 'NetAcademyBot' -Action $a -Trigger $t -Settings $s -User $c.UserName -Password $c.GetNetworkCredential().Password -RunLevel Limited -Force | Out-Null"
if errorlevel 1 (
  echo Failed. Nothing was changed.
  pause
  exit /b 1
)
rem The boot task replaces the sign-in shortcut, so remove that if it exists.
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\net_academy_bot.bat" 2>nul
echo Done. The bot will start in the background about a minute after the computer turns on.
echo To start it right now without restarting:  schtasks /run /tn NetAcademyBot
pause
