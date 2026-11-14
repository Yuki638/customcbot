@echo off
rem Starts customcbot on Windows. Double-click this file.
rem The first run downloads what it needs (about 1 GB), so it takes a few minutes.
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  if exist "%USERPROFILE%\.local\bin\uv.exe" (
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
  ) else (
    echo Installing uv, a small tool that sets up Python for this app...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
  )
)

uv run --no-dev customcbot %*
if errorlevel 1 (
  echo.
  echo customcbot stopped with an error. The message above says why.
  pause
)
