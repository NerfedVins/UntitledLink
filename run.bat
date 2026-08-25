@echo off
cd /d "%~dp0"

REM Three ways in:
REM   (no argument) a double click. Hands straight over to Convertex.vbs,
REM                 which runs this file again with no console. Windows still
REM                 shows this one for the second it takes to start cmd, which
REM                 is why Convertex.vbs is the one to double-click.
REM   quiet         the everyday launch. Checks the stamp file and starts the
REM                 app. Says 2 and stops if anything needs installing, since
REM                 there is no console here to install it in front of.
REM   setup         the first run, or after an edit to requirements.txt. Runs
REM                 pip where it can be watched, then starts the app.

if "%~1"=="quiet" goto :quiet
if "%~1"=="setup" goto :setup
if exist "%~dp0Convertex.vbs" (
    start "" wscript //nologo "%~dp0Convertex.vbs"
    exit /b 0
)
goto :setup

:quiet
REM Only the stamp file is checked here, and only against requirements.txt:
REM importing the five packages to be sure costs the best part of two seconds
REM of console on every single launch. If something was uninstalled behind our
REM back the app fails on its own imports and shows its crash dialog, which is
REM the same answer two seconds later.
where pythonw >nul 2>&1
if errorlevel 1 exit /b 2
if not exist ".deps-ok" exit /b 2
python -c "import os,sys; sys.exit(0 if os.path.getmtime('.deps-ok') >= os.path.getmtime('requirements.txt') else 1)" >nul 2>&1
if errorlevel 1 exit /b 2
start "" pythonw convertex.py
exit /b 0

:setup
where python >nul 2>&1
if errorlevel 1 (
    echo Python not found on PATH. Install it from python.org and tick "Add to PATH".
    pause
    exit /b 1
)

REM Two questions, because an import check alone answers only the first:
REM   1. is everything importable at all?
REM   2. is what is installed still what requirements.txt asks for?
REM (2) matters because the floors in requirements.txt are invisible to an
REM import - an ancient Pillow imports perfectly well.
set NEED=0
python -c "import bs4, requests, yt_dlp, PIL, imageio_ffmpeg" >nul 2>&1
if errorlevel 1 set NEED=1
python -c "import os,sys; sys.exit(0 if os.path.exists('.deps-ok') and os.path.getmtime('.deps-ok') >= os.path.getmtime('requirements.txt') else 1)" >nul 2>&1
if errorlevel 1 set NEED=1

if "%NEED%"=="1" (
    echo Installing dependencies - this only happens on a first run or after an update...
    python -m pip install -q -r requirements.txt
    if errorlevel 1 (
        echo Dependency install failed. Run this to see why:
        echo     python -m pip install -r requirements.txt
        pause
        exit /b 1
    )
    python -c "open('.deps-ok','w').close()" >nul 2>&1
)

REM pythonw is the console-less python: it launches the window and nothing
REM else, so this box closes instead of sitting behind the app all session.
REM A crash before the window appears has no console to print to, so the app
REM writes crash.log beside itself and shows the error in a dialog.
REM
REM yt-dlp refreshes itself from inside the app now, on a background thread,
REM which is what the "Updating yt-dlp..." line here used to be for.
where pythonw >nul 2>&1
if errorlevel 1 goto :no_pythonw
start "" pythonw convertex.py
exit /b 0

:no_pythonw
REM No pythonw (a stripped or non-standard install). Fall back to python and
REM keep the window, because it is the only place an error could show up.
python convertex.py
if errorlevel 1 pause
