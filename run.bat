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

REM yt-dlp breaks whenever YouTube/X change something, so refresh it every
REM launch. Output is swallowed: pip warns about unrelated broken packages in
REM site-packages and that noise is not this app's business. A real failure is
REM reported below.
echo Updating yt-dlp...
python -m pip install -q --upgrade --disable-pip-version-check yt-dlp >nul 2>&1
if errorlevel 1 echo   update skipped - offline, or run the pip command by hand to see why.

python convertex.py
if errorlevel 1 pause
