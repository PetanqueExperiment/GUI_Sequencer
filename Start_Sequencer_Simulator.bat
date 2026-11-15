@echo off
REM Start the hardware-free sequencer simulator (for the Sequence Scheduler; no ARTIQ / PyCam / HERO)
cd /d "%~dp0"

if not exist "venv_sequencer\Scripts\python.exe" (
    echo Virtual environment not found: "%~dp0venv_sequencer\Scripts\python.exe"
    echo Create it or adjust the path in this script.
    pause
    exit /b 1
)

echo Starting sequencer simulator...
"venv_sequencer\Scripts\python.exe" -m sequencer_gui.simulator %*
if errorlevel 1 (
    echo Sequencer simulator exited with an error.
    pause
)
exit /b 0
