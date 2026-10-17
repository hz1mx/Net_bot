@echo off
rem One-time: links this folder to GitHub (hz1mx/Net_bot) so changes can be pushed and pulled,
rem updates the bot files to the latest version and restarts the bot. Run as administrator.
net session >nul 2>&1
if errorlevel 1 (
  echo Right-click this file and choose "Run as administrator".
  pause
  exit /b 1
)
cd /d "%~dp0"
set "BRANCH=claude/telegram-bot-class-monitor-5lwe8s"

echo [1/5] Checking Git...
where git >nul 2>&1
if errorlevel 1 if not exist "%ProgramFiles%\Git\cmd\git.exe" winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
where git >nul 2>&1
if errorlevel 1 set "PATH=%ProgramFiles%\Git\cmd;%PATH%"
where git >nul 2>&1
if errorlevel 1 (
  echo Could not install Git. Install it from https://git-scm.com/download/win and run this file again.
  pause
  exit /b 1
)

echo [2/5] Stopping the bot while its files are replaced...
schtasks /end /tn NetAcademyBot >nul 2>&1
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*bot.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"

echo [3/5] Linking the folder to GitHub and getting the latest version...
rem Your own files (.env, state.json, booking_template.json, ...) are not in GitHub and are left as they are.
if not exist .git (
  git init -q
  git remote add origin https://github.com/hz1mx/Net_bot.git
)
git fetch -q origin %BRANCH%:refs/remotes/origin/%BRANCH%
if errorlevel 1 (
  echo Could not reach GitHub. Check the internet connection and run this file again.
  pause
  exit /b 1
)
git reset -q --hard origin/%BRANCH%
git branch -q -M %BRANCH%
git branch -q -u origin/%BRANCH%
git config user.name "hz1mx"
git config user.email "hz1mx@users.noreply.github.com"
rem This window runs as administrator; give the files back to you so Git works without it later.
icacls "%~dp0." /setowner "%USERDOMAIN%\%USERNAME%" /T /C /Q >nul

echo [4/5] Signing in to GitHub (a browser window may open; this lets changes be uploaded)...
git push --dry-run -q origin %BRANCH%

echo [5/5] Starting the bot again...
call install_boot_task.bat
