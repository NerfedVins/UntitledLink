@echo off
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo Python not found on PATH. Install it from python.org and tick "Add to PATH".
    pause
    exit /b 1
)

python -c "import bs4, requests, yt_dlp, PIL" >nul 2>&1
if errorlevel 1 (
    echo First run - installing dependencies...
    python -m pip install -q -r requirements.txt
    if errorlevel 1 (
        echo Dependency install failed. Run this to see why:
        echo     python -m pip install -r requirements.txt
        pause
        exit /b 1
    )
)

REM pythonw is the console-less python: it launches the window and nothing
REM else, so this box closes instead of sitting behind the app all session.
REM A crash before the window appears has no console to print to, so the app
REM writes crash.log beside itself and shows the error in a dialog.
REM
REM yt-dlp refreshes itself from inside the app now, on a background thread,
REM which is what the "Updating yt-dlp..." line here used to be for.
where pythonw >nul 2>&1
if errorlevel 1 goto :noconsole_missing
start "" pythonw convertex.py
exit /b 0

:noconsole_missing
REM No pythonw (a stripped or non-standard install). Fall back to python and
REM keep the window, because it is the only place an error could show up.
python convertex.py
if errorlevel 1 pause
