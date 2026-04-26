@echo off
REM Start the Petanque sequencer GUI (PyQt5)
cd /d "%~dp0"

if not exist "venv_sequencer\Scripts\python.exe" (
    echo Virtual environment not found: "%~dp0Sequencer_venv\Scripts\python.exe"
    echo Create it or adjust the path in this script.
    pause
    exit /b 1
)

echo Starting Sequencer GUI...
"venv_sequencer\Scripts\python.exe" -m sequencer_gui
if errorlevel 1 (
    echo Sequencer GUI exited with an error.
    pause
)
exit /b 0
