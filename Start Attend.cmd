@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Python environment not found. Follow the Windows setup commands in README.md.
  pause
  exit /b 1
)
echo Open http://127.0.0.1:5000/setup in your browser.
echo Keep this window open while using Attend. Press Ctrl+C to stop.
echo.
".venv\Scripts\python.exe" app.py
if errorlevel 1 pause
