@echo off
cd /d "%~dp0"
echo Building a standalone UntitledLink.exe. Nothing needs to be installed on the
echo machine that runs it - Python, yt-dlp and ffmpeg all go inside the exe.
echo.

python -m pip install -r requirements.txt pyinstaller pyinstaller-hooks-contrib
if errorlevel 1 goto :fail

REM ffmpeg comes from the imageio-ffmpeg wheel now, so requirements.txt above
REM has already put it on disk and there is nothing to fetch here.
python -c "import imageio_ffmpeg,sys; p=imageio_ffmpeg.get_ffmpeg_exe(); print('bundling',p)"
if errorlevel 1 (
    echo.
    echo STOPPING: imageio-ffmpeg did not provide an ffmpeg binary, and an exe
    echo without one cannot merge 1080p+ video or make mp3.
    pause
    exit /b 1
)

REM --collect-all yt_dlp: the extractors are imported lazily by name, so static
REM analysis alone misses most of them and the exe would only handle a handful
REM of sites. Same for imageio_ffmpeg, whose binary is data rather than an
REM import. certifi carries the CA bundle requests needs once frozen.
REM
REM socks and urllib3.contrib.socks are PySocks and the adapter requests
REM reaches for the first time a socks5h:// proxy is used - which is what the
REM tor switch is. Both are imported by name at that moment, so nothing static
REM sees them and a frozen build would answer "Missing dependencies for SOCKS
REM support" the first time anyone ticked the box.
REM
REM ffprobe is deliberately not bundled: nothing in this app calls it, and it
REM is another 100 MB of exe for nothing.
REM --icon paints the exe in Explorer; --add-data carries the same artwork
REM inside, because the window asks for it again at runtime and a frozen build
REM has no source folder to read it from.
pyinstaller --noconfirm --onefile --windowed --name UntitledLink ^
    --icon icon.ico ^
    --add-data "icon.ico;." ^
    --add-data "icon.png;." ^
    --collect-all yt_dlp ^
    --collect-all imageio_ffmpeg ^
    --collect-all certifi ^
    --hidden-import PIL._tkinter_finder ^
    --hidden-import socks ^
    --hidden-import urllib3.contrib.socks ^
    untitledlink.py
if errorlevel 1 goto :fail

echo.
echo Built: dist\UntitledLink.exe
echo Ship that single file. It needs nothing else installed.
echo.
REM A build server has nobody to press a key, and the flags have to live in
REM one place or the exe that CI ships stops being the exe built here.
if defined CI exit /b 0

echo Before shipping, smoke-test it on a machine without Python:
echo   1. scan a YouTube link  - resolutions and sizes must appear
echo   2. download an mp3 row  - proves the bundled ffmpeg works
echo   3. scan an X photo post - proves requests + certificates work
echo   4. tick "all through tor" with Tor running - proves PySocks came along
pause
exit /b 0

:fail
echo.
echo BUILD FAILED - see the output above.
if not defined CI pause
exit /b 1
