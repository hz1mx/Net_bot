@echo off
rem One-time: installs Claude Code, signs you in, and starts Remote Control now and every time you
rem sign in to Windows. Run it normally (NOT as administrator).
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where claude >nul 2>&1
if errorlevel 1 (
  echo Installing Claude Code...
  curl -fsSL https://claude.ai/install.cmd -o "%TEMP%\claude-install.cmd" && call "%TEMP%\claude-install.cmd" && del "%TEMP%\claude-install.cmd"
)
where claude >nul 2>&1
if errorlevel 1 (
  echo Claude Code did not install. See https://code.claude.com/docs/en/setup
  pause
  exit /b 1
)
echo.
echo Step 1: sign in to Claude. Follow the steps in the window; when it is ready, type /exit
pause
claude
echo.
echo Step 2: starting Remote Control. Answer y to its questions (trust this folder, enable Remote Control).
pause
(
  echo @echo off
  echo start "Claude remote control - Net bot" /min "%~dp0start_remote.bat"
) > "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\net_bot_remote.bat"
call start_remote.bat
