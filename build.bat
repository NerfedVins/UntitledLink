@echo off
cd /d "%~dp0"
echo Building a standalone convertex.exe. Nothing needs to be installed on the
echo machine that runs it - Python, yt-dlp and ffmpeg all go inside the exe.
echo.

python -m pip install -r requirements.txt pyinstaller pyinstaller-hooks-contrib
if errorlevel 1 goto :fail

REM Bake ffmpeg in rather than letting the exe fetch it on first run.
if not exist bin\ffmpeg.exe (
    echo Fetching ffmpeg to bundle...
    python -c "import convertex; convertex.fetch_ffmpeg(lambda a,b: None)"
)
if not exist bin\ffmpeg.exe (
    echo.
    echo STOPPING: ffmpeg is missing, and an exe without it cannot merge
    echo 1080p+ video or make mp3. Fix the download and run this again.
    pause
    exit /b 1
)

REM --collect-all yt_dlp: the extractors are imported lazily by name, so static
REM analysis alone misses most of them and the exe would only handle a handful
REM of sites. certifi carries the CA bundle requests needs once frozen.
pyinstaller --noconfirm --onefile --windowed --name convertex ^
    --add-binary "bin\ffmpeg.exe;bin" ^
    --add-binary "bin\ffprobe.exe;bin" ^
    --collect-all yt_dlp ^
    --collect-all certifi ^
    --hidden-import PIL._tkinter_finder ^
    convertex.py
if errorlevel 1 goto :fail

echo.
echo Built: dist\convertex.exe
echo Ship that single file. It needs nothing else installed.
echo.
echo Before shipping, smoke-test it on a machine without Python:
echo   1. scan a YouTube link  - resolutions and sizes must appear
echo   2. download an mp3 row  - proves the bundled ffmpeg works
echo   3. scan an X photo post - proves requests + certificates work
pause
exit /b 0

:fail
echo.
echo BUILD FAILED - see the output above.
pause
exit /b 1
