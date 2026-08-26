#!/usr/bin/env python3
"""convertex - paste a link, see what is downloadable, grab it clean.

Media links go through yt-dlp (YouTube, X/Twitter, Instagram, TikTok, Reddit, ...).
Anything else falls back to scraping the page for images and files.
Downloads are stripped of identifying metadata before they land on disk.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import tkinter as tk
import webbrowser
from tkinter import filedialog, font as tkfont, messagebox, ttk
from urllib.parse import urljoin, urlparse, unquote


# Pillow is only ever handed partial data here - previews are capped and the
# dimension probe reads a header-sized slice on purpose - so refusing truncated
# input would reject exactly the cases this app creates deliberately.

from i18n import COOKIE_BROWSERS, LANGUAGES, NO_COOKIES, Tr

APP = "convertex"
VERSION = "0.1.0"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# What the Tor Browser says it is, sent while the tor switch is on.
#
# A Chrome-on-Windows string arriving from a Tor exit node is a combination
# nobody else has: it says "a scraper is using Tor" as clearly as a signature
# would, and it is what Wikimedia answered with its robot policy. Every Tor
# Browser on the same platform sends exactly this instead, which is the point -
# the crowd is the cover.
#
# Read off the installed bundle rather than invented: Tor Browser 15.0.20
# reports Firefox 140.14.0 in application.ini and resistFingerprinting rounds
# that to the ESR major. Bump TOR_FIREFOX when Tor Browser moves to the next
# ESR; a stale version here is its own small fingerprint.
TOR_FIREFOX = "140.0"
TOR_UA = (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{TOR_FIREFOX}) "
          f"Gecko/20100101 Firefox/{TOR_FIREFOX}")

# Set by the tor switch. A module-level flag for the same reason PRIVATE is
# one: the network helpers are plain functions, called from threads that never
# see the window.
TOR_MODE = False


def user_agent() -> str:
    return TOR_UA if TOR_MODE else UA


def accept_language() -> str:
    """Tor Browser sends q=0.5, so an app claiming to be one has to as well."""
    return "en-US,en;q=0.5" if TOR_MODE else "en-US,en;q=0.9"

# What each extension is, for links that carry one. Missing an extension
# here is not a wrong answer but an invisible link: the scraper collects what
# it can name, so anything absent is never listed at all.
#
# .ts is the awkward one - an MPEG transport stream, which is what an HLS
# stream is cut into, and also TypeScript source. Video is the reading that
# belongs in a downloader, and the content type settles it on the way past.
FILE_EXT = {
    "image": ".jpg .jpeg .jfif .png .gif .webp .bmp .avif .tif .tiff .svg "
             ".heic .heif .ico",
    "video": ".mp4 .webm .mkv .mov .avi .m4v .mpg .mpeg .ts .m2ts .mts .flv "
             ".wmv .3gp .ogv",
    "audio": ".mp3 .m4a .m4b .aac .opus .ogg .oga .wav .flac .wma .aiff .aif "
             ".mka",
    "doc": ".pdf .epub .mobi .azw3 .doc .docx .xls .xlsx .ppt .pptx .odt .ods "
            ".odp .rtf .txt .md .csv .srt .vtt .ass .ssa",
    "archive": ".zip .rar .7z .tar .gz .tgz .bz2 .xz .zst .iso .cab .dmg",
}
EXT_KIND = {e: k for k, exts in FILE_EXT.items() for e in exts.split()}

# yt-dlp colourises its errors even with a custom logger attached
ANSI = re.compile(r"\x1b\[[0-9;]*m")

# ponytail: hard cap on playlist/channel expansion. Raise if someone actually
# wants to queue a 5000-video channel.
MAX_ENTRIES = 200

# Tries per item, including the first. Retries resume from the .part file, so a
# second attempt continues rather than restarting.
ATTEMPTS = 3

# ponytail: four at once saturates a home line without making any single site
# think it is being scraped. Raise it in settings if your pipe is fatter.
PARALLEL = 4
MAX_PARALLEL = 8

# Width of the status label, in characters of the mono font. Fixed so the
# progress bar and the download button beside it never jump around; the log
# keeps the full line either way. Clipping is measured in pixels rather than
# characters - see App.fit_status - because the Greek wording of a message runs
# longer than the English, and a character count clips one and not the other.
STATUS_CHARS = 68

# The preview pane takes a share of the window rather than a fixed slice, so
# maximising the window grows the picture instead of handing every extra pixel
# to a NAME column that had nothing to do with it. Clamped at both ends: below
# PREVIEW_W the pane stops being useful, above PREVIEW_MAX it starves the list.
PREVIEW_W = 240            # narrowest the preview pane goes, in pixels
PREVIEW_MAX = 620          # widest, however big the window gets
PREVIEW_SHARE = 0.27       # of the results area, when that lands between them
CHECKBOX = 16              # mark-column checkbox, in pixels
IMAGE_HEADER_BYTES = 65536  # enough for any JPEG/PNG/WebP size header
PREVIEW_MAX_BYTES = 8 << 20
MAX_THUMB_CACHE = 60       # decoded previews kept before the cache is dropped
MAX_HTML_BYTES = 8 << 20   # a page bigger than this is not a page worth parsing

# Fallback quality picker, used for playlist entries where per-format sizes are
# not known up front. (selector with ffmpeg, selector without it)
FORMATS = {
    "best": ("bv*+ba/b", "b"),
    "2160p": ("bv*[height<=2160]+ba/b[height<=2160]", "b[height<=2160]"),
    "1440p": ("bv*[height<=1440]+ba/b[height<=1440]", "b[height<=1440]"),
    "1080p": ("bv*[height<=1080]+ba/b[height<=1080]", "b[height<=1080]"),
    "720p": ("bv*[height<=720]+ba/b[height<=720]", "b[height<=720]"),
    "audio only": ("ba/b", "ba/b"),
    "mp3": ("ba/b", "ba/b"),          # handled by a postprocessor, needs ffmpeg
}

MP3_BITRATE = "320"   # best mp3 the source can justify

# ponytail: 60s of silence is a dead socket, not a slow one. Without this a
# stalled server pins the download thread forever.
SOCKET_TIMEOUT = 60

# A 429 is a request to back off, not a transient error. These are the waits
# used when the host does not send a Retry-After header of its own.
RATE_LIMIT_BASE_WAIT = 5
RATE_LIMIT_MAX_WAIT = 120

C = {
    "bg": "#0b0f14",
    "panel": "#11161d",
    "line": "#233040",
    "fg": "#c9d5e1",
    "dim": "#6e7f91",
    "green": "#3fb950",
    "amber": "#d29922",
    "red": "#f85149",
    "cyan": "#39c5cf",
}


# Keyed by Item.kind, which is now a closed set: every row lands on one of
# these, so nothing falls through to a catch-all colour any more.
TAG_COLOURS = {"video": C["green"], "audio": C["amber"], "image": C["cyan"],
               "doc": C["fg"], "archive": C["dim"], "file": C["dim"]}

APP_DIR = os.path.dirname(os.path.abspath(
    sys.executable if getattr(sys, "frozen", False) else __file__))


def _writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write-test")
        with open(probe, "w"):
            pass
        os.remove(probe)
        return True
    except OSError:
        return False


def pillow():
    """Pillow's Image, with the truncated-image flag set.

    requests, bs4 and Pillow together cost about half a second to import, and
    none of them is needed to put a window on screen - the first scan is the
    earliest any of them matters. They are imported where they are used, and
    warmed on a thread once the window is up, so the wait lands in neither
    place. LOAD_TRUNCATED_IMAGES rides along here because it has to be set
    before anything opens a half-downloaded preview.
    """
    from PIL import Image, ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    return Image


def warm_imports() -> None:
    """Pull the heavy imports in behind the window, not in front of it."""
    try:
        import requests            # noqa: F401
        import bs4                 # noqa: F401
        pillow()
    except Exception:
        pass                       # the real import will report it properly


def _data_dir() -> str:
    """Where settings and a fetched ffmpeg live.

    Beside the app when that folder is writable, which keeps a portable copy on
    a USB stick self-contained. Dropped into the user profile when it is not -
    an exe in Program Files cannot write next to itself, and silently losing
    every setting is a miserable way to find that out.
    """
    if _writable(APP_DIR):
        return APP_DIR
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    fallback = os.path.join(base, APP)
    return fallback if _writable(fallback) else APP_DIR


DATA_DIR = _data_dir()
# Set from the settings dialog. A module-level flag because the crash handler
# runs outside the App and still has to know not to write a file.
PRIVATE = False

SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
DEFAULT_OUTDIR = os.path.join(os.path.expanduser("~"), "Downloads", APP)


def load_settings() -> dict:
    """Remembered preferences. Deliberately holds no link history."""
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def clamp_int(text, default: int, lo: int, hi: int) -> int:
    """A usable int out of a settings file or a Spinbox, both of which can hold
    anything the user typed. Out-of-range is pulled back to the nearest end -
    a hand-edited "parallel": 99 means "lots", not "crash".
    """
    try:
        return max(lo, min(hi, int(text)))
    except (TypeError, ValueError):
        return default


def save_settings(data: dict) -> None:
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError:
        pass  # read-only folder is not worth interrupting the user over


def ffmpeg_path() -> str | None:
    """Where ffmpeg is. Beside the app first, then the wheel, then PATH.

    It used to be fetched from gyan.dev at runtime, which meant this app
    downloading and running a 100 MB executable it had no way to verify. The
    imageio-ffmpeg wheel is that same gyan.dev build, delivered through PyPI
    where pip checks the hash on the way in - so the verification is somebody
    else's already-solved problem and there is no pinned digest to go stale.

    A copy in ./bin still wins, so dropping a newer or differently-built ffmpeg
    next to the app overrides the packaged one.
    """
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    roots = []
    bundled = getattr(sys, "_MEIPASS", None)  # PyInstaller unpack dir
    if bundled:
        roots.append(os.path.join(bundled, "bin"))
    roots.append(os.path.join(APP_DIR, "bin"))
    for root in roots:
        candidate = os.path.join(root, name)
        if os.path.exists(candidate):
            return candidate
    try:
        import imageio_ffmpeg
        found = imageio_ffmpeg.get_ffmpeg_exe()
        if found and os.path.exists(found):
            return found
    except Exception:
        pass  # not installed, or it cannot find its own binary
    return shutil.which("ffmpeg")


# Every child process this app has running. Nothing it starts is allowed to
# outlive the window: a pip left behind by a closed app is exactly the thing
# in the background that nobody asked for and nobody can see to stop.
_CHILDREN: set = set()
_CHILDREN_LOCK = threading.Lock()


def quiet_run(cmd: list[str], capture_output: bool = False,
              text: bool = False, timeout: float | None = None):
    """subprocess.run with nothing on screen and nothing left behind.

    CREATE_NO_WINDOW keeps the process we start from opening a console, and
    says nothing about what that process starts in turn: pip launches cmd.exe,
    which got a console of its own and flashed one up two seconds after the app
    had appeared. A hidden STARTUPINFO is what those inherit, so it covers the
    part the flag cannot reach.

    Popen rather than run(), only so the child can be found and killed when the
    window closes - see stop_children().
    """
    import subprocess
    hidden = {}
    if os.name == "nt":
        info = subprocess.STARTUPINFO()
        info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        info.wShowWindow = subprocess.SW_HIDE
        hidden = {"startupinfo": info,
                  "creationflags": subprocess.CREATE_NO_WINDOW}
    pipe = subprocess.PIPE if capture_output else None
    proc = subprocess.Popen(cmd, stdout=pipe, stderr=pipe, text=text, **hidden)
    with _CHILDREN_LOCK:
        _CHILDREN.add(proc)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise
    finally:
        with _CHILDREN_LOCK:
            _CHILDREN.discard(proc)
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def stop_children() -> int:
    """Kill anything this app started, and say how many there were.

    Closing the window is meant to end the session, not hand parts of it to the
    background: a pip mid-download or an ffmpeg mid-strip would otherwise carry
    on with nothing on screen to show for it.
    """
    with _CHILDREN_LOCK:
        live = [p for p in _CHILDREN if p.poll() is None]
    for proc in live:
        try:
            proc.kill()
        except OSError:
            pass
    return len(live)


def installed_version(package: str) -> str:
    """What is on disk right now, read fresh rather than from the import."""
    try:
        from importlib.metadata import version, PackageNotFoundError
        return version(package)
    except Exception:
        return ""


def update_ytdlp(log, proxy: str | None = None) -> None:
    """Refresh yt-dlp quietly, in the background.

    It breaks whenever a site changes its markup, so the copy that worked last
    week may not work today. It runs on the first scan rather than at launch,
    and through whatever route that scan is using: at launch it was the one
    connection that ignored the proxy, so a session meant to go entirely
    through Tor started by telling PyPI, in the clear, that this machine had
    just opened the app.

    The new version applies at the next launch: yt-dlp is already imported by
    the time a scan happens, and swapping the files under it would not change
    that. A frozen build carries its own copy and cannot pip into itself.
    """
    if getattr(sys, "frozen", False):
        return
    import requests
    import subprocess
    have = installed_version("yt-dlp")

    # PyPI is asked directly rather than left to pip, because pip cannot be
    # made to tell the truth here: with the package already present and the
    # index unreachable it prints "Requirement already satisfied" and exits 0,
    # with no warning that it never got to look. That came back as "yt-dlp up
    # to date" - a claim nobody had checked. This way an unanswered question
    # reads as one, and pip is only started when there is something to install.
    try:
        latest = session_for(proxy).get(
            "https://pypi.org/pypi/yt-dlp/json", timeout=30
        ).json()["info"]["version"]
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        log(f"yt-dlp not checked ({have or 'version unknown'} in place) :: "
            f"{type(exc).__name__}", "warn")
        return

    if latest == have:
        log(f"yt-dlp up to date ({have})")
        return

    log(f"yt-dlp {have or '?'} -> {latest}, updating")
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "-q",
           "--disable-pip-version-check"]
    if proxy:
        cmd += ["--proxy", proxy]
    try:
        quiet_run(cmd + ["yt-dlp"], capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"yt-dlp update failed :: {exc}", "warn")
        return
    now = installed_version("yt-dlp")
    if now == latest:
        log(f"yt-dlp updated to {now} - applies at the next launch")
    else:
        log(f"yt-dlp update did not take ({now or '?'} still in place)", "warn")


# --------------------------------------------------------------------------
# metadata stripping
# --------------------------------------------------------------------------

def _strip_jpeg(data: bytes) -> bytes | None:
    """Drop EXIF/XMP/IPTC/comment segments. Lossless - entropy data untouched."""
    if data[:2] != b"\xff\xd8":
        return None
    # Keep APP0 (JFIF) and APP14 (Adobe colour transform): some decoders need
    # them and neither carries anything personal.
    keep = {0xE0, 0xEE}
    out = bytearray(b"\xff\xd8")
    i = 2
    while i + 1 < len(data):
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        if marker == 0xDA:  # start of scan - everything after is image data
            out += data[i:]
            return bytes(out)
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            out += data[i:i + 2]
            i += 2
            continue
        if i + 4 > len(data):
            break
        seglen = int.from_bytes(data[i + 2:i + 4], "big")
        drop = (0xE1 <= marker <= 0xEF and marker not in keep) or marker == 0xFE
        if not drop:
            out += data[i:i + 2 + seglen]
        i += 2 + seglen
    return bytes(out)


def _strip_png(data: bytes) -> bytes | None:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    drop = {b"tEXt", b"iTXt", b"zTXt", b"eXIf", b"tIME"}
    out = bytearray(data[:8])
    i = 8
    while i + 8 <= len(data):
        length = int.from_bytes(data[i:i + 4], "big")
        ctype = data[i + 4:i + 8]
        end = i + 12 + length
        if end > len(data):
            break
        if ctype not in drop:
            out += data[i:end]
        i = end
        if ctype == b"IEND":
            break
    return bytes(out)


def drop_mark_of_the_web(path: str) -> None:
    """Windows tags every download with a Zone.Identifier stream naming the source URL."""
    if os.name != "nt":
        return
    try:
        os.remove(path + ":Zone.Identifier")
    except OSError:
        pass


def strip_metadata(path: str) -> bool:
    """Remove identifying metadata in place. True if the file was rewritten."""
    drop_mark_of_the_web(path)
    try:
        with open(path, "rb") as fh:
            head = fh.read(16)
    except OSError:
        return False

    cleaned = None
    if head[:2] == b"\xff\xd8":
        with open(path, "rb") as fh:
            cleaned = _strip_jpeg(fh.read())
    elif head[:8] == b"\x89PNG\r\n\x1a\n":
        with open(path, "rb") as fh:
            cleaned = _strip_png(fh.read())

    if cleaned:
        with open(path, "wb") as fh:
            fh.write(cleaned)
        return True

    # ponytail: everything else (mp4/webm/webp/gif) rides on an ffmpeg stream
    # copy when it is installed. No ffmpeg means those types keep their tags.
    ff = ffmpeg_path()
    if ff:
        import subprocess
        tmp = path + ".clean" + os.path.splitext(path)[1]
        # -bitexact stops ffmpeg stamping its own encoder tag back on
        cmd = [ff, "-y", "-loglevel", "error", "-i", path,
               "-map_metadata", "-1", "-fflags", "+bitexact", "-bitexact",
               "-c", "copy", tmp]
        try:
            done = quiet_run(cmd, capture_output=True)
            if done.returncode == 0 and os.path.getsize(tmp) > 0:
                os.replace(tmp, path)
                return True
        except OSError:
            pass
        if os.path.exists(tmp):
            os.remove(tmp)
    return False


# --------------------------------------------------------------------------
# scanning
# --------------------------------------------------------------------------

class Item:
    """One downloadable thing.

    kind and quality used to be the same field, which is why a list could show
    "1080p" and "image" and "media" in one column as if they were the same sort
    of answer. kind is now only ever what the thing IS - video, audio, image,
    doc, archive, file - and quality carries how good a copy it is.
    """

    __slots__ = ("url", "name", "kind", "quality", "res", "length", "size",
                 "via", "fmt", "thumb", "info", "details", "page")

    def __init__(self, url, name, kind, size=0, via="file", fmt=None, thumb=None,
                 info="", details="", quality="", length="", res="", page=""):
        self.url, self.name, self.kind = url, name, kind
        self.quality = quality  # "1080p mp4", "mp3 320k" - display only
        self.res = res          # "1080x1920"; a column, not a word inside info
        self.length = length    # "2:41"; likewise
        self.size, self.via = size, via
        self.fmt = fmt  # explicit yt-dlp format selector; None = use the dropdown
        self.thumb = thumb      # url to show in the preview pane
        self.info = info        # one-line technical summary for the list
        self.details = details  # multi-line block for the preview pane
        # The page this was found on, sent back as the Referer. Plenty of hosts
        # hand over a file only to a request that says which page asked for it,
        # and refuse everything else with a 403 that looks like a dead link.
        self.page = page


def checkbox_images(size: int = CHECKBOX) -> dict:
    """The three states of the mark column, drawn rather than typed.

    ☐ and ☑ are missing from plenty of monospaced fonts and land as tofu boxes,
    and "[x]" never looked like something you could click. These are drawn four
    times up and shrunk back down, which is what gets the edges smooth.

    Needs a Tk root to already exist - PhotoImage cannot be built before one.
    """
    from PIL import Image, ImageDraw, ImageTk

    scale = 4
    big = size * scale
    pad = scale
    out = {}
    for name, edge, fill in (("off", C["dim"], None),
                             ("on", C["green"], C["green"]),
                             ("cut", C["red"], None)):
        img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([pad, pad, big - pad - 1, big - pad - 1],
                            radius=scale * 3, outline=edge, width=scale,
                            fill=fill)
        if name == "on":      # a tick, in the panel colour so it reads as cut out
            d.line([(big * .30, big * .52), (big * .44, big * .68),
                    (big * .72, big * .32)],
                   fill=C["bg"], width=scale * 2, joint="curve")
        elif name == "cut":   # a dash: pulled from the queue, not unticked
            d.line([(big * .32, big * .5), (big * .68, big * .5)],
                   fill=C["red"], width=scale * 2)
        out[name] = ImageTk.PhotoImage(
            img.resize((size, size), Image.LANCZOS))
    return out


def clock(seconds) -> str:
    """Seconds as 2:41 or 1:02:03. Empty when the source did not say."""
    if not seconds:
        return ""
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, sec = divmod(rest, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def codec_name(codec) -> str:
    """av01.0.08M.08 -> av01, avc1.640028 -> avc1, mp4a.40.2 -> mp4a."""
    if not codec or codec == "none":
        return ""
    return str(codec).split(".")[0]


def counted(n) -> str:
    """56071 -> 56.1K, 2400000 -> 2.4M. Views and likes, not bytes."""
    if not n:
        return ""
    for cut, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= cut:
            return f"{n / cut:.1f}{suffix}"
    return str(int(n))


def size_cell(it: Item, measured: bool) -> str:
    """The SIZE column, where two different unknowns used to look alike.

    "-" is a question that was asked and came back empty. The middle dot is one
    that has not been asked yet: the discreet scan measures nothing until a row
    is opened, and a column of dashes said "this file has no size" when it
    meant "click it and I will go and find out".
    """
    if it.size or measured or it.via == "ytdlp":
        return human(it.size)
    return "·"


def human(n: int) -> str:
    if not n:
        return "-"
    size = float(n)
    for unit in ("B", "K", "M", "G"):
        if size < 1024 or unit == "G":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return "?"


# Where Tor listens, in the order worth trying. 9050 is the tor service or
# the expert bundle; 9150 is the copy that comes inside the Tor Browser and
# runs while that browser is open. Which one exists depends on how Tor was
# installed, which is not a question the window should be asking anybody.
TOR_PORTS = (9050, 9150)

# Tor's own service, which answers whether it sees you arriving over Tor. Used
# by the button in settings, and by nothing else: it is the one question this
# app cannot answer about itself.
TOR_CHECK_URL = "https://check.torproject.org/api/ip"


def tor_proxy(host: str = "127.0.0.1", ports: tuple[int, ...] = TOR_PORTS,
              timeout: float = 1.5) -> str | None:
    """The address of a Tor that is actually running, or None.

    socks5h rather than socks5: the h is what sends the hostname through the
    circuit instead of resolving it here first, and a local DNS lookup tells
    your provider which site you are about to visit however the traffic then
    leaves. Ticking the box does nothing on its own - Tor has to be there -
    and without this check the answer arrives as a wall of failed requests,
    one per row.
    """
    import socket
    for port in ports:
        try:
            with socket.create_connection((host, port), timeout):
                return f"socks5h://{host}:{port}"
        except OSError:
            continue
    return None


PROXY_SCHEMES = ("http://", "https://", "socks4://", "socks5://", "socks5h://")


def normalise_proxy(text: str) -> str | None:
    """What the proxy box means, or None when it means nothing usable.

    The box used to take anything at all. "127.0.0.1:9050" became an *http*
    proxy as far as requests was concerned, so it spoke the wrong protocol at
    Tor's SOCKS port and the answer arrived as one ProxyError per row; "tor"
    was accepted as a hostname. A bare host:port is read as SOCKS now, which is
    what anyone typing one into this app means, and what the hint suggests.

    socks5 is upgraded to socks5h for the same reason Tor uses it: without the
    h the hostname is resolved here, so the traffic leaves through the proxy
    while the local resolver has already been told where it is going.
    """
    text = (text or "").strip()
    if not text:
        return None
    if text.startswith("socks5://"):
        text = "socks5h://" + text[len("socks5://"):]
    if text.startswith(PROXY_SCHEMES):
        return text if text.split("://", 1)[1] else None
    host, _, port = text.rpartition(":")
    if host and port.isdigit() and "/" not in text:
        return f"socks5h://{text}"
    return None


def with_circuit(proxy: str, tag: str) -> str:
    """The same Tor, asked for a circuit of its own.

    Tor hands a separate circuit to each SOCKS username/password it is given -
    IsolateSOCKSAuth, which is on by default. Without it every scan and every
    download in a session leaves by the same exit node, which can see that one
    client looked at this, then that, then fetched the other. A tag per action
    breaks the thread between them.

    Anything that is not Tor is handed back untouched: a VPN endpoint has no
    idea what to do with credentials it never asked for.
    """
    if not tag or not proxy.startswith(("socks5://", "socks5h://")) or "@" in proxy:
        return proxy
    scheme, host = proxy.split("://", 1)
    return f"{scheme}://{tag}:x@{host}"


def session_for(proxy: str | None) -> requests.Session:
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": user_agent(),
                      "Accept-Language": accept_language()})
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    return s


def upgrade_image(url: str) -> list[str]:
    """Candidate full-resolution variants of a thumbnail URL, best guess first."""
    out = []
    # WordPress and friends: name-800x600.jpg -> name.jpg
    resized = re.sub(r"-\d{2,4}x\d{2,4}(?=\.\w{3,4}(?:$|\?))", "", url)
    if resized != url:
        out.append(resized)
    # ?w=300&h=200&quality=70 style server-side resizing
    stripped = re.sub(r"[?&](w|h|width|height|size|resize|quality|q|fit)=[^&]*", "", url)
    stripped = stripped.replace("?&", "?").rstrip("?&")
    if stripped != url:
        out.append(stripped)
    # MediaWiki: /thumb/a/ab/X.jpg/500px-X.jpg -> /a/ab/X.jpg
    wiki = re.sub(r"/thumb/(.+?)/\d+px-[^/]+$", r"/\1", url)
    if wiki != url:
        out.append(wiki)
    for a, b in (("_thumb", ""), ("_small", ""), ("/thumbs/", "/"), ("/thumb/", "/"),
                 ("_t.", "."), (":small", ":orig"), (":thumb", ":orig")):
        if a in url:
            out.append(url.replace(a, b))
    return [u for u in dict.fromkeys(out) if u != url]


def best_from_srcset(srcset: str, base: str) -> str | None:
    best, best_w = None, -1
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        width = 0
        if len(bits) > 1 and bits[1].endswith("w"):
            width = int(bits[1][:-1] or 0)
        if width >= best_w:
            best, best_w = urljoin(base, bits[0]), width
    return best


# CON, NUL, COM1 and friends are devices, not files, on every Windows there
# has ever been - opening one succeeds and writes nowhere, or fails with an
# error that says nothing about the name. The extension does not save you:
# "nul.jpg" is still the device.
RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)", re.I)


def safe_name(text: str, limit: int = 120) -> str:
    """A filename Windows will actually accept. Trailing dots and spaces too -
    NTFS silently drops those and the rename then hits the wrong path."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text).strip()
    cleaned = cleaned[:limit].rstrip(". ")
    if RESERVED.match(cleaned):
        cleaned = "_" + cleaned
    return cleaned or "file"


def name_from_url(url: str) -> str:
    return safe_name(unquote(os.path.basename(urlparse(url).path)) or "file")


def kind_of(url: str) -> str | None:
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    return EXT_KIND.get(ext)


# What a link that hands over a file tends to say when it has no extension to
# say it with: eClass and Moodle serve everything through document/index.php
# and mod/resource/view.php, Drive through export=download, plenty of sites
# through a download.php with the real name in a header.
DOWNLOAD_HINTS = ("download", "attachment", "getfile", "get_file", "/dl/",
                  "export=download", "mod/resource", "document/index.php",
                  "file.php", "fileid=", "file_id=", "docid=", "attach")


# A stream is served as a playlist of segments, not as a file: .m3u8 for HLS,
# .mpd for DASH. Saving the manifest gets you a two-kilobyte text file that
# lists the video, which is why these never belonged in the extension table.
# yt-dlp knows how to follow one and hand back a single playable file, so they
# are collected as its rows rather than as downloads.
STREAM_EXT = (".m3u8", ".mpd")


# Quoted paths that end in something this app can name, wherever they are
# written: a script, a data attribute, an inline style. Built from the
# extension table so the two cannot drift apart, and quoted so it matches an
# address rather than any word ending in .mp4 in a sentence. Relative paths
# count - a player config says "/stream.m3u8" far more often than it spells
# out the host.
def _asset_pattern() -> "re.Pattern":
    exts = "|".join(sorted((e.lstrip(".") for e in
                            list(EXT_KIND) + list(STREAM_EXT)), key=len,
                           reverse=True))
    return re.compile(r"""['"]([^'"<>\s]{2,300}?\.(?:%s)(?:\?[^'"]{0,200})?)['"]"""
                      % exts, re.I)


def is_stream(url: str) -> bool:
    return os.path.splitext(urlparse(url).path)[1].lower() in STREAM_EXT


def better_name(current: str, offered: str) -> str:
    """Prefer the name the server offered, when the one we have is a page.

    "index.php" is what a link with the name in its headers looks like from
    the outside, and it is no better as a filename on disk than it is as a row
    in the list.
    """
    if not offered:
        return current
    ours = os.path.splitext(current)[1].lower()
    return offered if ours in ("", ".php", ".asp", ".aspx", ".jsp", ".cgi",
                               ".html", ".htm") else current


def looks_like_download(url: str) -> bool:
    """A link with no known extension that still smells like a file.

    Collecting only known extensions meant a page of lecture handouts came
    back empty rather than wrong - nothing to be clicked, no reason given.
    These are listed as files and the content type settles it: the full scan
    drops the ones that answer with a page, and the discreet scan says so when
    the row is opened.
    """
    if kind_of(url):
        return False
    parts = urlparse(url)
    if not parts.path or parts.path.endswith("/"):
        return False
    hay = (parts.path + "?" + parts.query).lower()
    return any(h in hay for h in DOWNLOAD_HINTS)


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    """Width and height straight out of a JPEG's SOF marker.

    Pillow refuses a truncated JPEG while it is still parsing markers, and
    LOAD_TRUNCATED_IMAGES only relaxes decoding, not that. Walking the segments
    ourselves reads the size from a header-sized slice regardless.
    """
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 <= len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker == 0xDA:  # start of scan - no size past here
            return None
        if marker in (0xD8, 0x01, 0xFF) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        # SOF0..SOF15 carry the dimensions; C4/C8/CC are tables, not frames
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height = int.from_bytes(data[i + 5:i + 7], "big")
            width = int.from_bytes(data[i + 7:i + 9], "big")
            return (width, height) if width and height else None
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    return None


def image_dimensions(s: requests.Session, url: str) -> str:
    """WxH read from an image's header, without downloading the whole file.

    JPEG, PNG and WebP all put their dimensions near the front, so a ranged
    request for the first chunk is enough. Returns "" when it cannot be read -
    an empty cell beats a wrong one.
    """
    import io
    import requests
    try:
        r = s.get(url, timeout=15, stream=True,
                  headers={"Range": f"bytes=0-{IMAGE_HEADER_BYTES - 1}"})
        r.raise_for_status()
        data = r.raw.read(IMAGE_HEADER_BYTES, decode_content=True)
        r.close()
    except requests.RequestException:
        return ""

    size = jpeg_size(data)
    if size:
        return f"{size[0]}x{size[1]}"
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        return f"{img.width}x{img.height}"
    except Exception:
        return ""


def offered_name(headers) -> str:
    """The filename a server offers in Content-Disposition, or "".

    A link like document/index.php?download=/1 has no name worth having in it;
    the name lives in the header instead, and without reading it both the row
    and the saved file end up called index.php.
    """
    disp = headers.get("content-disposition", "")
    if "filename" not in disp.lower():
        return ""
    # filename*=UTF-8''name.pdf wins over filename="name.pdf" when both are
    # there, which is the whole point of the starred one.
    for pattern in (r"filename\*\s*=\s*[^']*'[^']*'([^;]+)",
                    r'filename\s*=\s*"([^"]+)"',
                    r"filename\s*=\s*([^;]+)"):
        found = re.search(pattern, disp, re.I)
        if found:
            return safe_name(unquote(found.group(1).strip().strip('"')))
    return ""


def head(s: requests.Session, url: str,
         referer: str = "") -> tuple[int, str, str]:
    """(content-length, content-type, offered filename).

    (0, "", "") when the URL is not reachable."""
    import requests
    sent = {"Referer": referer} if referer else {}
    try:
        r = s.head(url, timeout=12, allow_redirects=True, headers=sent)
        if r.status_code >= 400:  # plenty of CDNs refuse HEAD
            r = s.get(url, timeout=12, stream=True, headers=sent)
            r.close()
        if r.status_code >= 400:
            return 0, "", ""
        return (int(r.headers.get("content-length") or 0),
                r.headers.get("content-type", ""),
                offered_name(r.headers))
    except (requests.RequestException, ValueError):
        return 0, "", ""


def probe_all(items: list[Item], s: requests.Session,
              workers: int = PARALLEL) -> list[Item]:
    """HEAD every item. For images also try higher-res variants and keep the
    biggest one that actually exists. Drops anything that answers with HTML -
    a link ending in .ogg can still be a wiki page about an .ogg."""
    from concurrent.futures import ThreadPoolExecutor

    def probe(it: Item):
        if it.via == "ytdlp":
            # A manifest has a size of its own and it means nothing: two
            # kilobytes of text listing an hour of video.
            return it
        it.size, ctype, offered = head(s, it.url, it.page)
        if "html" in ctype:
            return None
        it.name = better_name(it.name, offered)
        if it.kind == "image":
            for cand in upgrade_image(it.url):
                size, ctype, _ = head(s, cand, it.page)
                if size > it.size and "html" not in ctype:
                    it.url, it.size = cand, size
        return it

    # Most scrapes are one host, so the worker count is the per-host cap in
    # practice - which makes it the same question the download setting already
    # answers, so it uses that rather than a hard-coded six. Set it to 1 and the
    # probes leave one at a time, which is what a small site wants to see.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        probed = [it for it in pool.map(probe, items) if it]
    # two thumbnails can resolve to the same original, so dedupe after upgrading
    return list({it.url: it for it in probed}.values())


ASSET_RE = _asset_pattern()


# Built once. Listing them is cheap, but matching a URL walks all 1751 of them,
# so the list itself is not rebuilt for every iframe on a page.
_EXTRACTORS: list | None = None

# An article with more embeds than this is a listing page, and each one costs a
# round trip to the site it points at.
MAX_EMBEDS = 4


def embed_urls(soup, base: str) -> list[str]:
    """iframe sources on a page that yt-dlp has a real extractor for.

    An article embeds its video rather than linking to the file, so a scrape
    that only reads <img> and <a> comes back with the photos and misses the
    thing the article is actually about.

    Which iframes are worth following is a question yt-dlp can already answer,
    and asking it beats keeping a list of video hosts in here that would be out
    of date by next month. It also drops the tracking pixels and the social
    buttons for free: nothing has an extractor for those.
    """
    global _EXTRACTORS
    try:
        if _EXTRACTORS is None:
            from yt_dlp.extractor import gen_extractor_classes
            _EXTRACTORS = [ie for ie in gen_extractor_classes()
                           if ie.ie_key() != "Generic"]
    except ImportError:
        return []

    seen, out = set(), []
    for tag in soup.find_all("iframe"):
        # Lazy-loaded embeds park the real address in a data attribute and only
        # move it to src once the frame scrolls into view, which never happens
        # to a page nobody is looking at.
        raw = next((tag.get(a) for a in ("src", "data-src", "data-lazy-src")
                    if tag.get(a)), None)
        if not raw:
            continue
        full = urljoin(base, raw.strip())
        if not full.startswith(("http://", "https://")) or full in seen:
            continue
        seen.add(full)
        if any(ie.suitable(full) for ie in _EXTRACTORS):
            out.append(full)
    return out


def scrape_page(url: str, proxy: str | None, log, embeds: bool = True,
                workers: int = PARALLEL, quiet: bool = False) -> list[Item]:
    """Every downloadable thing a page links to.

    quiet=True is the discreet scan: the page is read and nothing else is
    touched. The rows arrive with no size, and the one you click gets measured
    then - which is one request per row you look at instead of one per link on
    the page, plus the extra HEADs a full-resolution hunt costs.
    """
    s = session_for(proxy)
    # streamed so the body can be read in a bounded slice below
    r = s.get(url, timeout=25, stream=True)
    spoken = http_reason(r.status_code, TOR_MODE)
    if spoken:
        # This one reaches the status line, where "403 Client Error: Forbidden
        # for url: https://..." told nobody anything they could act on.
        raise RuntimeError(f"{urlparse(url).netloc} {spoken}")
    r.raise_for_status()
    if "html" not in r.headers.get("content-type", ""):
        size = int(r.headers.get("content-length") or 0)
        return [Item(url, name_from_url(url), kind_of(url) or "file", size)]

    # Bounded read: BeautifulSoup sniffs the encoding out of the bytes itself,
    # and r.text would happily pull a runaway response into memory first.
    from bs4 import BeautifulSoup
    body = r.raw.read(MAX_HTML_BYTES, decode_content=True)
    soup = BeautifulSoup(body, "html.parser")
    found: dict[str, str] = {}
    offered: dict[str, str] = {}     # url -> the name the page suggested
    streams: set[str] = set()        # manifests, which yt-dlp downloads

    def add(raw, forced: str = "", name: str = ""):
        if not raw or raw.startswith(("data:", "javascript:", "#")):
            return
        full = urljoin(url, raw.strip()).split("#")[0]
        if is_stream(full):
            streams.add(full)
            found.setdefault(full, "video")
            return
        kind = (forced or kind_of(full)
                or ("file" if looks_like_download(full) else ""))
        if kind:
            found.setdefault(full, kind)
            if name:
                offered.setdefault(full, safe_name(name))

    for tag in soup.find_all(["a", "img", "source", "video", "audio", "embed",
                              "object", "track"]):
        # download="Lecture 3.pdf" is the page saying outright that this is a
        # file and what it is called - the one marker that needs no guessing,
        # and it was being ignored along with the name it carries.
        marked = tag.name == "a" and tag.has_attr("download")
        given = tag.get("download") if isinstance(tag.get("download"), str) else ""
        for attr in ("href", "src", "data", "data-src", "data-original",
                     "data-full", "data-url", "data-file", "data-href",
                     "data-download", "data-mp4", "data-video", "poster"):
            add(tag.get(attr), "file" if marked else "", given)
        if tag.get("srcset"):
            add(best_from_srcset(tag["srcset"], url))
    for meta in soup.find_all("meta"):
        if meta.get("property") in ("og:image", "og:video") or meta.get("name") == "twitter:image":
            add(meta.get("content"))

    # Whatever the tags did not carry. Players keep their sources in a script
    # as JSON - "file":"https:\/\/host\/lecture.mp4" - galleries keep theirs
    # in a style attribute as url(...), and neither is a tag with an attribute
    # to read. Only addresses that already name a type this app knows are
    # taken, so the sweep adds files rather than noise.
    text = body.decode("utf-8", "replace").replace("\/", "/")
    text = text.replace("&amp;", "&")
    for match in re.finditer(r"""https?://[^\s"'<>\)]{4,}""", text):
        add(match.group(0))
    for match in ASSET_RE.finditer(text):
        # A slash is what separates an address from a name: download="Notes.pdf"
        # and alt="photo.jpg" are labels, and joining them to the page invents
        # a link that was never there.
        if "/" in match.group(1):
            add(match.group(1))
    for match in re.finditer(r"""url\(\s*['"]?([^)'"]+)""", text):
        add(match.group(1))

    # A manifest is usually called index.m3u8 or master.m3u8, which says
    # nothing about what it is; the page's own title does.
    titled = (soup.title.get_text().strip() if soup.title else "") or ""
    items = [Item(u,
                  (safe_name(titled) if u in streams and titled
                   else offered.get(u) or name_from_url(u)),
                  k, thumb=u if k == "image" else None, page=url,
                  via="ytdlp" if u in streams else "file",
                  quality="as set" if u in streams else "",
                  info="HLS" if u.lower().endswith(".m3u8") else
                       ("DASH" if u in streams else ""))
             for u, k in found.items()]
    if quiet:
        # Nothing is probed, so nothing can be dropped either: a link that ends
        # in .ogg but serves a wiki page stays in the list until the row is
        # clicked and its content type gives it away.
        log(f"{len(items)} candidates, sizes measured on demand")
    else:
        log(f"{len(items)} candidates, probing sizes and full-res variants...")
        items = probe_all(items, s, workers)
    items.sort(key=lambda i: (i.kind, -i.size))

    # Embedded video goes on top: on a page that has one, it is usually the
    # thing the page is about, and the images are the furniture around it.
    # Skipped when the caller has already resolved the embeds itself.
    return (embedded_media(soup, url, proxy, log) if embeds else []) + items


def embedded_media(soup, url: str, proxy: str | None, log) -> list[Item]:
    """Resolve the page's video embeds into rows, in parallel.

    Each one is a round trip to whichever site it points at, so they run
    together rather than one after another, and the count is capped.
    """
    from concurrent.futures import ThreadPoolExecutor

    embeds = embed_urls(soup, url)
    if not embeds:
        return []
    if len(embeds) > MAX_EMBEDS:
        log(f"{len(embeds)} embeds, looking at the first {MAX_EMBEDS}")
        embeds = embeds[:MAX_EMBEDS]
    log(f"{len(embeds)} embedded video(s) - asking yt-dlp about them...")

    def resolve(embed):
        try:
            found, err = scan_media(embed, proxy, log)
            if err:
                log(f"embed skipped :: {err}")
            return found
        except Exception as exc:      # one bad embed must not sink the scrape
            log(f"embed failed :: {embed} :: {exc}")
            return []

    with ThreadPoolExecutor(max_workers=MAX_EMBEDS) as pool:
        rows = [it for group in pool.map(resolve, embeds) for it in group]
    if rows:
        log(f"{len(rows)} row(s) from embedded video")
    return rows


class _Hush:
    """yt-dlp still prints extractor errors on stderr unless it has a logger."""
    def debug(self, msg): pass
    info = warning = error = debug


def _fsize(f: dict) -> int:
    return f.get("filesize") or f.get("filesize_approx") or 0


def merge_mark(progressive: bool, have_ffmpeg: bool) -> str:
    """The ' *' suffix warning that a row cannot be downloaded as things stand.

    A progressive format is a finished file. A split one only needs the warning
    while ffmpeg is missing - once it is installed the row works, so the star
    would just be noise.
    """
    return "" if progressive or have_ffmpeg else " *"


def has_audio(f: dict) -> bool:
    """Does this format already carry sound, so no merge is needed?

    yt-dlp writes the *string* "none" for a stream that is genuinely absent.
    None means unknown - which is what X/Twitter reports for its plain http mp4s,
    and those are complete files. Treating unknown as missing made every Twitter
    video demand ffmpeg it did not need.
    """
    return f.get("acodec") != "none"


def media_variants(info: dict, title: str, url: str) -> list[Item]:
    """One row per available resolution, with the real byte size of what would
    actually be downloaded (video plus the audio track merged into it)."""
    formats = info.get("formats") or []
    if not formats:
        return []
    thumb = info.get("thumbnail")
    have_ffmpeg = bool(ffmpeg_path())
    duration = clock(info.get("duration"))

    # The preview pane has room the list does not, so the slow-changing facts
    # about the video itself live there and the list keeps the per-row ones.
    head = []
    if info.get("uploader") or info.get("channel"):
        head.append(info.get("uploader") or info.get("channel"))
    stamp = str(info.get("upload_date") or "")
    if len(stamp) == 8:
        head.append(f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}")
    if duration:
        head.append(duration)
    if info.get("view_count"):
        head.append(f"{counted(info['view_count'])} views")
    if info.get("like_count"):
        head.append(f"{counted(info['like_count'])} likes")
    head = "\n".join(head)

    audio_only = [f for f in formats if f.get("vcodec") == "none" and f.get("acodec") != "none"]
    # One row per distinct track rather than only the best one, the same way
    # video gets a row per resolution. Deduped on codec and bitrate because a
    # site will happily list the same track under several format ids.
    per_track: dict[tuple, dict] = {}
    for f in sorted(audio_only, key=lambda f: _fsize(f), reverse=True):
        per_track.setdefault((codec_name(f.get("acodec")),
                              round(f.get("abr") or 0), f.get("ext")), f)
    tracks = sorted(per_track.values(),
                    key=lambda f: (f.get("abr") or 0, _fsize(f)), reverse=True)
    best_audio = tracks[0] if tracks else None
    audio_bytes = _fsize(best_audio) if best_audio else 0

    per_height: dict[int, tuple[dict, int]] = {}
    for f in formats:
        height = f.get("height")
        if not height or f.get("vcodec") == "none":
            continue
        progressive = has_audio(f)
        total = _fsize(f) + (0 if progressive else audio_bytes)
        best = per_height.get(height)
        # prefer the bigger file at a given height - that is the better bitrate
        if not best or total > best[1]:
            per_height[height] = (f, total)

    items = []
    for height in sorted(per_height, reverse=True):
        f, total = per_height[height]
        width = f.get("width") or 0
        # A resolution label names the short side. Using the height is only
        # right for landscape: a 1080x1920 vertical video is a 1080p video,
        # and calling it "1920p" is a number nobody uses.
        label = f"{min(width, height) if width else height}p"
        progressive = has_audio(f)
        # Anything above ~360p on YouTube ships video and audio separately, so
        # the row is flagged and download_media refuses it without ffmpeg
        # rather than silently handing back a silent video.
        fmt = f["format_id"] if progressive else f"{f['format_id']}+ba/b[height<={height}]"
        mark = merge_mark(progressive, have_ffmpeg)
        bits = []
        if f.get("fps"):
            bits.append(f"{round(f['fps'])}fps")
        bits.append(codec_name(f.get("vcodec")))
        if f.get("dynamic_range") and f["dynamic_range"] != "SDR":
            bits.append(f["dynamic_range"])
        detail = [f"video  {codec_name(f.get('vcodec'))}  "
                  f"{f.get('width') or '?'}x{height}"
                  + (f"  {round(f['fps'])}fps" if f.get("fps") else "")]
        if f.get("tbr"):
            detail.append(f"bitrate  {round(f['tbr'])}k")
        if not progressive and best_audio:
            detail.append(f"audio  {codec_name(best_audio.get('acodec'))}"
                          + (f"  {round(best_audio['abr'])}k" if best_audio.get("abr") else "")
                          + "  (merged in)")
        detail.append(f"container  {f.get('ext') or '?'}")
        items.append(Item(url, title, "video", total, via="ytdlp", fmt=fmt,
                          quality=f"{label} {f.get('ext') or ''}{mark}".strip(),
                          res=f"{width or '?'}x{height}",
                          length=duration, thumb=thumb,
                          info="  ".join(b for b in bits if b),
                          details=head + "\n\n" + "\n".join(detail)))

    for track in tracks:
        acodec = codec_name(track.get("acodec"))
        # Bitrate and container are already the quality cell, so the info line
        # carries only what is not being said there twice.
        abits = [acodec]
        if track.get("asr"):
            abits.append(f"{round(track['asr'] / 1000)}kHz")
        if track.get("audio_channels") == 2:
            abits.append("stereo")
        elif track.get("audio_channels"):
            abits.append(f"{track['audio_channels']}ch")
        aquality = track.get("ext") or "audio"
        if track.get("abr"):
            aquality += f" {round(track['abr'])}k"
        adetail = [f"audio  {acodec}  source track, not re-encoded",
                   f"container  {track.get('ext') or '?'}"]
        if track.get("abr"):
            adetail.insert(1, f"bitrate  {round(track['abr'])}k")
        items.append(Item(url, title, "audio", _fsize(track), via="ytdlp",
                          fmt=track["format_id"], quality=aquality,
                          length=duration, thumb=thumb,
                          info="  ".join(b for b in abits if b),
                          details=head + "\n\n" + "\n".join(adetail)))

    if best_audio:
        # Last, and after every source track: an mp3 is not a better copy of
        # any of them, it is one of them decoded and encoded again. It is here
        # because things that will not play an opus file still exist.
        star = merge_mark(False, have_ffmpeg)
        items.append(Item(url, title, "audio",
                          audio_bytes, via="ytdlp", fmt="mp3", thumb=thumb,
                          quality=f"mp3 {MP3_BITRATE}k{star}", length=duration,
                          info=f"from {codec_name(best_audio.get('acodec'))}",
                          details=head + f"\n\naudio  mp3  {MP3_BITRATE}k"
                                         f"\nre-encoded from the source track"
                                         f"\ncontainer  mp3"))
    return items


# X/Twitter serve their pages as JavaScript, so scraping one yields avatars and
# icons. The public embed endpoint - the one powering embedded tweets - returns
# the real media as JSON, including the photos yt-dlp ignores entirely.
TWEET_ID = re.compile(r"(?:twitter|x)\.com/(?:[^/]+/)?status(?:es)?/(\d+)")
SYNDICATION = "https://cdn.syndication.twimg.com/tweet-result"


def tweet_id(url: str) -> str | None:
    m = TWEET_ID.search(url)
    return m.group(1) if m else None


def _syndication_token(tweet: str) -> str:
    """A token for the embed endpoint.

    Twitter's own script prints ((id / 1e15) * pi) in base 36 with zeros and
    the dot stripped. This is the decimal fraction instead, which is not the
    same string - and does not need to be: the endpoint accepts any non-empty
    token and only rejects a missing one. If that ever changes, base 36 is the
    thing to implement.
    """
    return ("%f" % ((int(tweet) / 1e15) * math.pi)).split(".")[-1]


def twitter_media(url: str, proxy: str | None, log) -> tuple[list[Item], str]:
    """Photos and videos from a public tweet. Returns (items, reason-if-empty)."""
    import requests
    tweet = tweet_id(url)
    if not tweet:
        return [], ""
    try:
        r = session_for(proxy).get(
            SYNDICATION,
            params={"id": tweet, "token": _syndication_token(tweet), "lang": "en"},
            timeout=20)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as exc:
        log(f"tweet embed lookup failed :: {exc}")
        return [], ""

    if data.get("__typename") == "TweetTombstone":
        # The embed API is explicit where yt-dlp is vague: the post exists but
        # is not visible to a logged-out reader.
        return [], "this post is not publicly viewable - it needs a login"

    return tweet_items(data, tweet), ""


def tweet_items(data: dict, tweet: str) -> list[Item]:
    """Turn an embed-API payload into rows. Photos first, then video variants."""
    title = safe_name((data.get("text") or "").split("\n")[0], 70) or f"tweet {tweet}"
    items = []
    for n, m in enumerate(data.get("mediaDetails") or [], 1):
        base = m.get("media_url_https")
        if m.get("type") == "photo":
            # ?name=orig is the untouched upload, not the display-sized copy
            if base:
                size = m.get("original_info") or {}
                dims = (f"{size['width']}x{size['height']}"
                        if size.get("width") else "")
                items.append(Item(f"{base}?name=orig", f"{title} [{n}].jpg",
                                  "image", thumb=f"{base}?name=small",
                                  quality="original", res=dims,
                                  details=f"photo  original upload\n{dims}"))
            continue
        variants = [v for v in (m.get("video_info") or {}).get("variants") or []
                    if v.get("content_type") == "video/mp4" and v.get("url")]
        for v in sorted(variants, key=lambda x: x.get("bitrate") or 0, reverse=True):
            wh = re.search(r"/(\d+)x(\d+)/", v["url"])
            label = f"{wh.group(2)}p" if wh else "video"
            dims = f"{wh.group(1)}x{wh.group(2)}" if wh else ""
            secs = (data.get("duration_millis") or 0) / 1000
            items.append(Item(v["url"], f"{title} [{n}] [{label}]", "video",
                              size=int((v.get("bitrate") or 0) / 8 * secs),
                              quality=f"{label} mp4", res=dims,
                              length=clock(secs),
                              thumb=base,
                              info="mp4",
                              details=f"video  mp4  {dims}\n"
                                      f"bitrate  {round((v.get('bitrate') or 0) / 1000)}k"))
    return items


def scan_media(url: str, proxy: str | None, log,
               cookies: str = "") -> tuple[list[Item], str]:
    """Ask yt-dlp what lives at this URL.

    Returns (items, error). Empty items with an empty error means 'not a media
    site, go scrape it'. Empty items *with* an error means yt-dlp recognised the
    site but could not read it - private video, geoblock, login wall - and that
    reason is worth showing instead of a blank result.
    """
    try:
        from yt_dlp import YoutubeDL
    except ImportError:
        log("yt-dlp not installed - falling back to page scraping")
        return [], ""
    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "cachedir": False, "noprogress": True, "extract_flat": "in_playlist",
        "http_headers": {"User-Agent": user_agent()},
        "logger": _Hush(), "no_color": True,
        # without this a site that accepts the connection and then says nothing
        # holds the scan open for as long as it likes
        "socket_timeout": SOCKET_TIMEOUT,
    }
    if proxy:
        opts["proxy"] = proxy
    if cookies:
        opts["cookiesfrombrowser"] = (cookies,)
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        reason = ANSI.sub("", str(exc)).replace("ERROR: ", "").strip()
        # "This is not a media site" has to be told apart from "this site is a
        # media site and something went wrong", because the first one means go
        # and scrape the page and the second one is worth showing the user.
        #
        # yt-dlp says the first with UnsupportedError, wrapped inside the
        # DownloadError it actually raises - reachable through .exc_info. That
        # was previously guessed at from the message text, which never matched,
        # so every ordinary web page came back as a hard error and the page
        # scraper below was unreachable.
        from yt_dlp.utils import UnsupportedError
        inner = getattr(exc, "exc_info", (None, None, None))[1]
        if isinstance(inner, UnsupportedError) or isinstance(exc, UnsupportedError):
            return [], ""
        # A generic-extractor miss means the same thing: it looked, and there
        # was no media on the page for it to take.
        if reason.lower().startswith("[generic]"):
            return [], ""
        return [], reason
    if not info:
        return [], ""

    entries = info.get("entries")
    if entries is None:
        # Single video: we already have the full format list, so offer every
        # resolution with its real size instead of a blind quality guess.
        title = (info.get("title") or name_from_url(url)).strip()
        variants = media_variants(info, title, url)
        if variants:
            starred = sum(1 for v in variants if v.name.endswith("*]"))
            note = " :: * needs ffmpeg" if starred and not ffmpeg_path() else ""
            log(f"{len(variants)} variants :: pick a resolution{note}")
            return variants, ""
        # No per-format list, so the resolution is whatever the quality
        # setting asks for at download time rather than something to pick here.
        return [Item(url, title, "video", _fsize(info), via="ytdlp",
                     thumb=info.get("thumbnail"), quality="as set",
                     length=clock(info.get("duration")))], ""

    entries = list(entries)
    if len(entries) > MAX_ENTRIES:
        log(f"capped at {MAX_ENTRIES} of {len(entries)} entries")
        entries = entries[:MAX_ENTRIES]

    items = []
    for e in entries:
        if not e:
            continue
        link = e.get("webpage_url") or e.get("url") or url
        title = (e.get("title") or name_from_url(link)).strip()
        size = e.get("filesize") or e.get("filesize_approx") or 0
        # extract_flat means the formats are not known yet, so these download
        # at whatever the quality setting says. Hence "as set" rather than a
        # resolution this cannot honestly promise.
        items.append(Item(link, title, "video", size, via="ytdlp",
                          thumb=e.get("thumbnail"), quality="as set",
                          length=clock(e.get("duration"))))
    return items, ""


# Hosts where a page scrape returns avatars and site furniture rather than the
# thing you asked for. If yt-dlp finds no media on one of these, say so instead
# of quietly handing back junk images.
MEDIA_HOSTS = ("x.com", "twitter.com", "instagram.com", "tiktok.com",
               "facebook.com", "youtube.com", "youtu.be", "reddit.com")


def is_media_host(url: str) -> bool:
    host = urlparse(url).netloc.lower().removeprefix("www.").removeprefix("m.")
    return any(host == h or host.endswith("." + h) for h in MEDIA_HOSTS)


def scan(url: str, proxy: str | None, log, cookies: str = "",
         no_video_msg: str = "", cookies_msg: str = "",
         workers: int = PARALLEL, quiet: bool = False,
         scanning_msg: str = "") -> list[Item]:
    # log() here is the status line, so it is read by whoever is waiting:
    # the name of the tool doing the work is not what they are waiting for.
    log(scanning_msg or "asking yt-dlp...")
    items, err = scan_media(url, proxy, log, cookies)
    if items:
        if not is_media_host(url):
            # yt-dlp reads a random page through its generic extractor, which
            # follows an embedded video and hands back that - and only that.
            # The page's own photographs are still worth having, and asking for
            # a link's media should not mean picking one or the other.
            #
            # Media hosts are left alone: scraping one of those returns avatars
            # and interface icons, which is why they are excluded by name.
            try:
                items = items + scrape_page(url, proxy, log, embeds=False,
                                            workers=workers, quiet=quiet)
            except Exception as exc:
                log(f"the page itself would not scrape :: {exc}")
        return items

    why = ""
    if tweet_id(url):
        # yt-dlp's twitter extractor only handles video, so a photo tweet lands
        # here with "no video could be found". The embed API has the photos.
        log("no video from yt-dlp - asking the tweet embed API...")
        items, why = twitter_media(url, proxy, log)
        if items:
            return items

    if why or err or is_media_host(url):
        # Scraping x.com for a login-walled or video-less post yields avatars
        # and icons, which reads as "found nothing useful" with no explanation.
        # One reason, best first: the embed API is more specific than yt-dlp,
        # and the generic line is only for when neither said anything.
        reason = why or err or no_video_msg or f"{urlparse(url).netloc} served no media"
        parts = [reason]
        if not cookies and is_media_host(url):
            parts.append(cookies_msg)
        raise RuntimeError(" :: ".join(p for p in parts if p))

    log("not a known media site - scraping the page...")
    return scrape_page(url, proxy, log, workers=workers, quiet=quiet)


# --------------------------------------------------------------------------
# downloading
# --------------------------------------------------------------------------

# Two workers can pick the same free filename in the gap between checking and
# writing, so claiming a name and moving the file into it is one atomic step.
NAME_LOCK = threading.Lock()

# Parallelism that all lands on one host is what trips rate limiters. The
# worker count is the overall budget; this caps how much of it any single host
# can see at once, so a batch spread over several sites still runs wide.
HOST_LIMIT = 2
_host_slots: dict[str, threading.Semaphore] = {}
_host_lock = threading.Lock()


def host_slot(url: str) -> threading.Semaphore:
    host = urlparse(url).netloc.lower()
    with _host_lock:
        return _host_slots.setdefault(host, threading.Semaphore(HOST_LIMIT))


def part_path(outdir: str, name: str, url: str) -> str:
    """Where a partial download lives.

    Keyed by URL, not just filename: two different files can share a name, and
    in parallel they would otherwise append into each other's .part. Same URL
    still maps to the same path, so resume keeps working.
    """
    tag = hashlib.sha1(url.encode("utf-8", "replace")).hexdigest()[:8]
    return os.path.join(outdir, f"{name}.{tag}.part")


def drop_part(it, outdir: str) -> None:
    """Bin a resume file that nothing is ever going to finish.

    Kept after a cancel on purpose - the whole point of keying .part by URL is
    that pulling an item out of the queue and asking for it again later picks
    up where it stopped. Only a failure retrying cannot fix is litter.
    """
    try:
        os.remove(part_path(outdir, it.name, it.url))
    except OSError:
        pass


def already_here(existing: set[str], it: Item) -> bool:
    """Is this row's file already sitting in the download folder?

    Nothing was ever said about it: unique_path quietly wrote "clip (2).mp4"
    beside the clip you already had, and you found out by looking at the
    folder afterwards.

    A yt-dlp row cannot be matched exactly - its name is decided by a template
    at download time, with the id and the extension filled in then - so the
    title is matched as a prefix. A scraped row has its real filename already.
    """
    if it.via == "ytdlp":
        stem = safe_name(it.name)[:40]
        return bool(stem) and any(f.startswith(stem) for f in existing)
    return safe_name(it.name) in existing


def unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{stem} ({n}){ext}"):
        n += 1
    return f"{stem} ({n}){ext}"


def http_reason(status: int, over_tor: bool = False) -> str:
    """What a status code means to somebody waiting for a file.

    "403 Client Error: Forbidden for url: https://..." is the protocol talking
    to itself. These four are the ones worth translating, because each points
    at a different thing to do next - and a refusal while tor is on usually
    means the exit node, not the account.
    """
    if status in (401, 403):
        if over_tor:
            return (f"refused ({status}) - sites often turn away tor exit "
                    f"nodes; try without tor, or scan again for a new circuit")
        return (f"refused ({status}) - it may want a login: turn on browser "
                f"cookies in settings")
    if status in (404, 410):
        return f"not there any more ({status})"
    if status == 451:
        return f"blocked for legal reasons ({status})"
    return ""


class Permanent(Exception):
    """A failure retrying cannot fix - do not burn attempts on it."""


class Cancelled(Exception):
    """The user pulled this item out of the queue mid-flight."""


class RateLimited(Exception):
    """The host asked us to slow down. Retrying in a second only annoys it."""

    def __init__(self, wait: float):
        super().__init__(f"rate limited, waiting {int(wait)}s")
        self.wait = wait


def retry_after(response, attempt: int) -> float:
    """How long to wait after a 429/503.

    Hosts that bother to send Retry-After mean it, so that wins. Otherwise back
    off far harder than for an ordinary error - a rate limiter is not a blip,
    and hammering it just extends the block.
    """
    floor = RATE_LIMIT_BASE_WAIT * (3 ** (attempt - 1))
    header = (response.headers.get("Retry-After") or "").strip()
    if header.isdigit():
        # Obey a longer request, but do not trust a very short one: hosts that
        # say "1s" while still refusing just burn the retry budget.
        floor = max(float(header), floor)
    return min(floor, RATE_LIMIT_MAX_WAIT)


def resume_plan(have: int, status: int, length: int) -> tuple[str, int, int]:
    """Decide how to continue a partial download.

    have    bytes already sitting in the .part file
    status  HTTP status of the ranged request
    length  content-length of *this* response

    Returns (open mode, bytes already counted, total size). A 206 means the
    server honoured the range, so we append and the total is what we had plus
    what is coming. Anything else means we start over.
    """
    if have and status == 206:
        return "ab", have, have + length
    return "wb", 0, length


def download_file(it: Item, outdir: str, proxy: str | None, clean: bool,
                  progress, attempt: int = 1) -> str:
    s = session_for(proxy)
    # Stable .part name so a retry picks up where the last attempt stopped;
    # the unique suffix is only decided once the file is whole.
    part = part_path(outdir, it.name, it.url)
    saved_as = it.name
    have = os.path.getsize(part) if os.path.exists(part) else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    if it.page:
        headers["Referer"] = it.page

    with s.get(it.url, stream=True, timeout=40, headers=headers) as r:
        if r.status_code in (429, 503):
            wait = retry_after(r, attempt)
            r.close()
            raise RateLimited(wait)
        if have and r.status_code == 416:  # already have the whole thing
            r.close()
            done = have
            mode, total = "ab", have
        else:
            # Said in words before the protocol says it in numbers.
            spoken = http_reason(r.status_code, TOR_MODE)
            if spoken:
                raise Permanent(spoken)
            r.raise_for_status()
            # Saving a pdf as index.php because that is what the link looked
            # like is the same mistake twice: the header knows better. Kept
            # local rather than written back onto the row - the .part is keyed
            # by the name this attempt started with, and a retry has to find
            # the same one.
            saved_as = better_name(it.name, offered_name(r.headers))
            if "html" in r.headers.get("content-type", ""):
                # Nothing the scraper collects is served as html: every
                # extension it knows is a real file. So this is a login wall,
                # an error page, or a link that only looked like a download -
                # and saving it would leave a web page on disk called .ogg.
                # Permanent, because the next attempt fetches the same page.
                raise Permanent("serves a web page, not a file")
            length = int(r.headers.get("content-length") or 0)
            mode, done, total = resume_plan(have, r.status_code, length)
            # What the server promised for this response, as opposed to what
            # the row happens to say. it.size can be stale or plain wrong, and
            # a wrong figure here would fail a download that is actually whole.
            promised = 0 if r.headers.get("content-encoding") else total
            total = total or it.size
            with open(part, mode) as fh:
                for chunk in r.iter_content(262144):
                    fh.write(chunk)
                    done += len(chunk)
                    progress(done, total)  # raises Cancelled if pulled from the pool
            # A connection that dies mid-file usually raises, but a server that
            # closes cleanly after a short body does not - and renaming the
            # .part would turn half a file into a finished-looking one and throw
            # away the bytes the next attempt could have resumed from.
            if promised and done < promised:
                raise IOError(f"stopped short :: {done} of {promised} bytes")

    with NAME_LOCK:
        dest = unique_path(os.path.join(outdir, saved_as))
        os.replace(part, dest)
    if clean:
        strip_metadata(dest)
    return dest


def subtitle_opts(lang: str, wanted: bool) -> dict:
    """yt-dlp options for subtitles, or nothing at all.

    Both the written ones and the machine transcript: a lecture or a seminar
    often has only the second, and getting nothing back for a video that
    visibly has captions reads as a broken setting rather than a choice.

    The window's language first, then English. Anything else that exists is
    left where it is - all of them would mean twenty files beside one video.
    They land as .srt next to it rather than muxed in, which needs no ffmpeg
    and leaves a file a text editor can open.
    """
    if not wanted:
        return {}
    return {"writesubtitles": True, "writeautomaticsub": True,
            "subtitleslangs": [lang, "en"], "subtitlesformat": "srt/vtt/best"}


def download_media(it: Item, outdir: str, proxy: str | None, quality: str,
                   clean: bool, progress, cookies: str = "",
                   subs: str = "") -> str:
    from yt_dlp import YoutubeDL

    ff = ffmpeg_path()
    want_mp3 = it.fmt == "mp3" or (not it.fmt and quality == "mp3")
    if it.fmt and "+" in it.fmt and not ff:
        raise Permanent("this resolution ships video and audio separately - "
                        "click 'get ffmpeg' first")
    if want_mp3 and not ff:
        raise Permanent("mp3 needs ffmpeg to re-encode - click 'get ffmpeg' first")
    fmt = "ba/b" if want_mp3 else (it.fmt or FORMATS[quality][0 if ff else 1])
    holder: dict[str, str] = {}

    def hook(d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            # yt-dlp swallows most exceptions from hooks, so a cancel is turned
            # into its own abort signal and re-raised once extract_info returns.
            try:
                progress(d.get("downloaded_bytes", 0), total)
            except Cancelled:
                holder["cancelled"] = "1"
                raise
        elif d["status"] == "finished":
            holder["path"] = d.get("filename", "")

    opts = {
        "format": fmt,
        "outtmpl": os.path.join(outdir, "%(title).120B [%(id)s].%(ext)s"),
        "quiet": True, "no_warnings": True, "noprogress": True,
        "cachedir": False, "noplaylist": True,
        "continuedl": True, "retries": 5, "fragment_retries": 5,
        "socket_timeout": SOCKET_TIMEOUT,
        "writeinfojson": False, "writethumbnail": False,
        "http_headers": {"User-Agent": user_agent()},
        "progress_hooks": [hook],
    }
    opts.update(subtitle_opts(subs, bool(subs)))
    if proxy:
        opts["proxy"] = proxy
    if cookies:
        opts["cookiesfrombrowser"] = (cookies,)
    if ff:
        opts["ffmpeg_location"] = ff
        if subs:
            # The format selector only picks among what the site offers, and
            # Wikimedia offers vtt - measured. srt is the one every player and
            # every text editor understands, and converting needs the ffmpeg
            # this app already carries.
            opts.setdefault("postprocessors", []).append(
                {"key": "FFmpegSubtitlesConvertor", "format": "srt"})
        if want_mp3:
            opts.setdefault("postprocessors", []).append(
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                 "preferredquality": MP3_BITRATE})
        else:
            opts["merge_output_format"] = "mp4"
            if clean:
                opts["postprocessor_args"] = {"merger": ["-map_metadata", "-1"]}

    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(it.url, download=True)
    except Exception:
        if holder.get("cancelled"):
            raise Cancelled from None
        raise

    # Postprocessing renames the file, so the hook's path can already be stale.
    candidates = [d.get("filepath") for d in (info or {}).get("requested_downloads") or []]
    candidates.append(holder.get("path"))
    if want_mp3 and holder.get("path"):
        candidates.append(os.path.splitext(holder["path"])[0] + ".mp3")
    path = next((c for c in candidates if c and os.path.exists(c)), None)
    if path:
        if clean:
            strip_metadata(path)
        return path
    return outdir


# --------------------------------------------------------------------------
# ui
# --------------------------------------------------------------------------

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.items: list[Item] = []
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self.prefs = load_settings()
        self.t = Tr(self.prefs.get("language", "en"))
        self.marked: set[str] = set()
        self.cancelled: set[int] = set()   # item indices pulled mid-download
        self.sized: set[int] = set()       # rows already measured on demand
        self.scanning = False
        # Bumped to abandon a scan. The worker cannot be killed - it is parked
        # in a socket read - so instead its result is dropped when it finally
        # lands, and the window is handed back immediately.
        self.scan_token = 0

        root.title(f"{APP} {VERSION}")
        root.configure(bg=C["bg"])
        root.geometry("1140x700")
        root.minsize(940, 540)

        # Tk variables, so the settings dialog and a language rebuild both keep
        # working against the same state instead of re-reading widgets.
        self.url_var = tk.StringVar()
        self.outdir_var = tk.StringVar(
            value=self.prefs.get("outdir") or DEFAULT_OUTDIR)
        self.proxy_var = tk.StringVar(value=self.prefs.get("proxy", ""))
        self.clean_var = tk.BooleanVar(value=self.prefs.get("strip_metadata", True))
        self.cookies_var = tk.StringVar(
            value=self.prefs.get("cookies") or NO_COOKIES)
        # Off by default: a double click is easy to do by accident, and the
        # accident here starts a download rather than opening something.
        self.dblclick_var = tk.BooleanVar(
            value=bool(self.prefs.get("double_click_downloads", False)))
        # Deliberately not remembered. A privacy mode you get by accident,
        # because it was on last week, is not one you can reason about - and
        # remembering it would mean writing the very file it suppresses.
        # On by default. Measured on a 20-link page: the full scan costs 31
        # requests, this one costs 1, and the difference is paid only where you
        # look - one HEAD per row you open. The full scan is what to switch on
        # when sizes to sort by are worth a request per link.
        self.quiet_var = tk.BooleanVar(value=bool(self.prefs.get("quiet_scan", True)))
        # Off by default: it is another file per download, and most downloads
        # are not lectures. On, it is the only part of a video that a text
        # search can reach.
        self.subs_var = tk.BooleanVar(value=bool(self.prefs.get("subtitles", False)))
        self.private_var = tk.BooleanVar(value=False)
        self.private_var.trace_add("write", lambda *_: self.apply_private())
        # Not remembered either, and for a plainer reason than private mode:
        # Tor has to be running for it to mean anything, and a box that was
        # ticked last week is a scan that fails for a reason nobody remembers.
        self.tor_var = tk.BooleanVar(value=False)
        self.tor_addr: str | None = None      # filled in when the box goes on
        self.tor_circuit = ""                 # rotates per scan and per download
        self.route_label = None               # lives only while settings is open
        self.tor_var.trace_add("write", lambda *_: self.apply_tor())
        self.quality_var = tk.StringVar(value=self.prefs.get("quality", "best"))
        # StringVar, not IntVar: an IntVar raises TclError the moment it holds
        # anything non-numeric, and both a hand-edited settings file and the
        # Spinbox itself can put junk in there. Coerced on read instead.
        self.attempts_var = tk.StringVar(
            value=str(clamp_int(self.prefs.get("attempts"), ATTEMPTS, 1, 10)))
        self.parallel_var = tk.StringVar(
            value=str(clamp_int(self.prefs.get("parallel"), PARALLEL, 1, MAX_PARALLEL)))

        self.mono = self.pick_font()
        self.f = tkfont.Font(family=self.mono, size=10)
        self.fb = tkfont.Font(family=self.mono, size=10, weight="bold")
        self.fh = tkfont.Font(family=self.mono, size=15, weight="bold")

        self.style()
        self.build()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.tick = root.after(80, self.pump)
        self.ytdlp_checked = False   # the update rides along with the first scan
        # After the window is drawn, not during: started here it competed with
        # the build for the interpreter and cost more than it saved - measured
        # at 1129ms to a window against 967ms before it existed at all.
        root.after(250, lambda: threading.Thread(target=warm_imports,
                                                 daemon=True).start())
        if not ffmpeg_path():
            # Nothing to click and nothing to download: ffmpeg rides in with the
            # dependencies. Missing it means the pip install did not finish, and
            # the log is where that gets said.
            self.log("ffmpeg not found - 1080p+ merging and mp3 are unavailable. "
                     "Run: pip install -r requirements.txt", "warn")

    def close(self):
        self.remember()
        left = stop_children()
        if left:
            self.log(f"stopped {left} background process(es) on the way out")
        self.root.after_cancel(self.tick)  # otherwise pump fires post-destroy
        self.root.destroy()

    def apply_private(self):
        global PRIVATE
        PRIVATE = bool(self.private_var.get())
        self.refresh_hint()

    def apply_tor(self):
        # Kept in step with the switch, below, once the address is known.
        """Tick the box and every request goes through Tor - if Tor is there.

        Nothing else in the window can tell you it is not: the scan would just
        fail, once per row, with a connection error that names a port. So the
        box refuses to stay on rather than promising something it cannot do.
        """
        global TOR_MODE
        TOR_MODE = bool(self.tor_var.get())
        if self.tor_var.get():
            self.tor_addr = tor_proxy()
            if not self.tor_addr:
                self.tor_var.set(False)      # traces again, and lands below
                self.say(self.t("tor_missing"), C["amber"])
                self.log("tor: nothing listening on "
                         + " or ".join(f"127.0.0.1:{p}" for p in TOR_PORTS)
                         + " - start the Tor Browser or the tor service", "warn")
                return
            self.log(f"tor: routing everything through {self.tor_addr}")
            if not self.private_var.get():
                # Hiding the address while the session is written to disk is
                # half a job, so the private one comes on with it. Turned on,
                # not held on: switch it back off and it stays off - someone
                # may want their settings remembered and only the route hidden.
                self.private_var.set(True)
                self.say(self.t("tor_private"), C["green"])
            elif not self.quiet_var.get():
                # Only when there was no private-session message to show: two
                # status lines in a row means seeing the second one only.
                self.say(self.t("tor_slow_scan"), C["amber"])
            if not self.quiet_var.get():
                self.log("tor: every request costs seconds now - the discreet "
                         "scan asks the site once per page instead of once per "
                         "link", "info")
        self.refresh_hint()

    def remember(self):
        if self.private_var.get():
            return          # nothing about this session goes to disk
        save_settings({
            "language": self.t.lang,
            "outdir": self.outdir_var.get().strip(),
            "proxy": self.proxy_var.get().strip(),
            "quality": self.quality_var.get(),
            "strip_metadata": bool(self.clean_var.get()),
            "cookies": self.cookies(),
            "double_click_downloads": bool(self.dblclick_var.get()),
            "quiet_scan": bool(self.quiet_var.get()),
            "subtitles": bool(self.subs_var.get()),
            "attempts": self.attempts(),
            "parallel": self.workers(),
        })

    def attempts(self) -> int:
        return clamp_int(self.attempts_var.get(), ATTEMPTS, 1, 10)

    def workers(self) -> int:
        return clamp_int(self.parallel_var.get(), PARALLEL, 1, MAX_PARALLEL)

    def check_route(self):
        """Ask what the far end actually sees.

        With no route set there is nothing to ask: the answer is known, and
        putting the question to a service on the internet would mean handing
        it your address for the privilege of being told your address.
        """
        proxy = self.proxy()
        if not self.route_label or not self.route_label.winfo_exists():
            return
        if not proxy:
            self.route_label.config(text=self.t("route_none"))
            return
        self.route_label.config(text=self.t("route_checking"))
        threading.Thread(target=self._route_worker, args=(proxy,),
                         daemon=True).start()

    def _route_worker(self, proxy):
        try:
            seen = session_for(proxy).get(TOR_CHECK_URL, timeout=45).json()
        except Exception as exc:
            self.q.put(("route", self.t("route_failed", why=type(exc).__name__),
                        None))
            return
        key = "route_tor" if seen.get("IsTor") else "route_proxy"
        self.q.put(("route", self.t(key, ip=seen.get("IP") or "?"), None))

    def new_circuit(self):
        """Ask Tor for a fresh circuit for whatever is about to happen.

        Called when a scan starts and when a download starts, so the two are
        not visibly the same client to whoever is carrying them.
        """
        import secrets
        self.tor_circuit = secrets.token_hex(8)

    def proxy(self) -> str | None:
        """Where every request goes out: Tor when it is on, otherwise whatever
        is typed in settings, otherwise straight out.

        The Tor address is the one found when the box was ticked, rather than
        a fresh look each time: this is asked once per scan and once per
        download, and the answer does not move while the app is open.
        """
        if self.tor_var.get() and self.tor_addr:
            return with_circuit(self.tor_addr, self.tor_circuit)
        return normalise_proxy(self.proxy_var.get())

    def cookies(self) -> str:
        """The browser to lift cookies from, or "" for none.

        The dropdown shows a word for the off position so the box is never
        blank; everything downstream still wants an empty string.
        """
        if self.private_var.get():
            return ""       # private mode never touches the browser's cookies
        chosen = self.cookies_var.get()
        return "" if chosen == NO_COOKIES else chosen

    def pick_font(self) -> str:
        fams = set(tkfont.families(self.root))
        for name in ("Cascadia Mono", "Cascadia Code", "JetBrains Mono",
                     "Consolas", "DejaVu Sans Mono", "Menlo", "Courier New"):
            if name in fams:
                return name
        return "TkFixedFont"

    def style(self):
        st = ttk.Style()
        st.theme_use("clam")
        st.configure("T.Treeview", background=C["panel"], fieldbackground=C["panel"],
                     foreground=C["fg"], borderwidth=0, rowheight=26,
                     font=(self.mono, 10))
        st.configure("T.Treeview.Heading", background=C["bg"], foreground=C["dim"],
                     borderwidth=0, font=(self.mono, 9, "bold"), padding=(6, 4))
        st.map("T.Treeview.Heading", background=[("active", C["line"])])
        st.map("T.Treeview", background=[("selected", C["line"])],
               foreground=[("selected", C["green"])])
        st.configure("T.Vertical.TScrollbar", background=C["line"], troughcolor=C["bg"],
                     bordercolor=C["bg"], arrowcolor=C["dim"], borderwidth=0)
        st.configure("T.Horizontal.TProgressbar", background=C["green"],
                     troughcolor=C["panel"], bordercolor=C["panel"],
                     lightcolor=C["green"], darkcolor=C["green"], borderwidth=0)
        for accent in ("green", "cyan", "amber", "red", "dim"):
            # "big" is the same button with more presence, for download - the
            # thing every visit to this window is actually for.
            for prefix, size, pad_xy in (("", 10, (14, 5)), ("big", 12, (26, 9))):
                name = f"{prefix}{accent}.T.TButton"
                st.configure(name, background=C["panel"], foreground=C[accent],
                             font=(self.mono, size, "bold"), borderwidth=0,
                             relief="flat", padding=pad_xy, anchor="center",
                             width=0)
                # Button.focus is the element that drew clam's dashed rectangle
                # inside the button, and it draws it whatever -focusthickness
                # says, so the element is taken out of the layout rather than
                # configured. Button.border stays: it is what paints the
                # background these buttons are made of.
                st.layout(name, [("Button.border", {
                    "sticky": "nswe", "border": "1", "children": [
                        ("Button.padding", {"sticky": "nswe", "children": [
                            ("Button.label", {"sticky": "nswe"})]})]})])
                # Pressed inverts - the accent fills the button and the text
                # goes dark - so a click is unmistakable without a border to
                # announce it. Focus and hover take the lighter panel, which
                # still tells a keyboard user where they are. First match wins,
                # so pressed leads. Disabled keeps dim text: it was the line
                # colour, near enough to the background that the word
                # disappeared and the button read as an empty box.
                st.map(name,
                       background=[("pressed", C[accent]), ("active", C["line"]),
                                   ("focus", C["line"])],
                       foreground=[("pressed", C["bg"]), ("disabled", C["dim"])])
        st.configure("T.TCombobox", fieldbackground=C["panel"], background=C["panel"],
                     foreground=C["fg"], arrowcolor=C["dim"], bordercolor=C["line"],
                     selectbackground=C["panel"], selectforeground=C["fg"])
        # These boxes are state="readonly" for their whole life, and clam maps
        # readonly to a light grey field and readonly+focus to blue - both of
        # which won over the configure() above and left the chosen value
        # unreadable. Mapping the same states here is the only way to win.
        # Order matters: the first matching spec is the one that applies, so
        # focus sits ahead of readonly to tint the current value green.
        st.map("T.TCombobox",
               fieldbackground=[("readonly", C["panel"]), ("disabled", C["panel"])],
               background=[("readonly", C["panel"]), ("active", C["panel"])],
               foreground=[("disabled", C["dim"]), ("focus", C["green"]),
                           ("readonly", C["fg"])],
               selectbackground=[("readonly", C["panel"])],
               selectforeground=[("focus", C["green"]), ("readonly", C["fg"])],
               arrowcolor=[("active", C["green"]), ("readonly", C["dim"])],
               bordercolor=[("focus", C["green"]), ("readonly", C["line"])],
               lightcolor=[("focus", C["green"]), ("readonly", C["panel"])],
               darkcolor=[("focus", C["green"]), ("readonly", C["panel"])])
        self.root.option_add("*TCombobox*Listbox.background", C["panel"])
        self.root.option_add("*TCombobox*Listbox.foreground", C["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", C["line"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", C["green"])
        self.root.option_add("*TCombobox*Listbox.font", (self.mono, 10))

    # -- widget helpers ----------------------------------------------------

    def entry(self, parent, width=20, textvariable=None):
        # disabledbackground is a system colour unless it is said out loud, so
        # a box switched off - the proxy one, while tor is on - came out white
        # in the middle of a dark window.
        e = tk.Entry(parent, bg=C["panel"], fg=C["fg"], font=self.f, width=width,
                     relief="flat", insertbackground=C["green"],
                     textvariable=textvariable,
                     disabledbackground=C["panel"], disabledforeground=C["dim"],
                     readonlybackground=C["panel"],
                     highlightthickness=1, highlightbackground=C["line"],
                     highlightcolor=C["green"], selectbackground=C["line"])
        return self.wire_entry(e)

    def button(self, parent, text, cmd, accent="green", big=False):
        """A real button, not a Label that happens to react to clicks.

        ttk.Button is what gives Tab focus, Space and Return activation, and
        the control an accessibility tool needs to announce as a button. The
        Label version looked identical and was reachable by mouse only.
        """
        prefix = "big" if big else ""
        return ttk.Button(parent, text=text, command=cmd, takefocus=True,
                          cursor="hand2", style=f"{prefix}{accent}.T.TButton")

    def label(self, parent, text):
        return tk.Label(parent, text=text, bg=C["bg"], fg=C["dim"], font=self.f)

    # -- clipboard ---------------------------------------------------------
    # Tk binds Ctrl+V to the *keysym*, so on a Greek (or any non-Latin) layout
    # the V key reports a Greek letter and the built-in binding never fires.
    # Physical key codes are layout-independent, so we drive it off those.

    CTRL_CODES = {65: "all", 67: "copy", 86: "paste", 88: "cut"}

    def on_ctrl(self, event):
        if not event.state & 0x4:  # Control held
            return None
        action = self.CTRL_CODES.get(event.keycode)
        if not action:
            return None
        widget = self.root.focus_get()
        if isinstance(widget, ttk.Treeview) or widget is None:
            if action == "all":
                self.mark_all(on=len(self.marked) != len(self.tree.get_children()))
                return "break"
            return None
        if not isinstance(widget, tk.Entry):
            return None
        self.edit(widget, action)
        return "break"

    def edit(self, widget: tk.Entry, action: str):
        """Clipboard actions driven by us, not by Tk's layout-bound defaults."""
        has_sel = widget.selection_present()
        if action == "all":
            widget.select_range(0, "end")
            widget.icursor("end")
        elif action in ("copy", "cut") and has_sel:
            self.root.clipboard_clear()
            self.root.clipboard_append(widget.selection_get())
            if action == "cut":
                widget.delete("sel.first", "sel.last")
        elif action == "paste":
            try:
                text = self.root.clipboard_get()
            except tk.TclError:
                return  # empty or non-text clipboard
            if has_sel:
                widget.delete("sel.first", "sel.last")
            # a copied link often drags newlines and stray spaces along
            widget.insert("insert", " ".join(text.split()))

    def wire_entry(self, widget: tk.Entry):
        """Right-click menu plus layout-proof clipboard keys for one field."""
        menu = tk.Menu(self.root, tearoff=0, bg=C["panel"], fg=C["fg"],
                       activebackground=C["line"], activeforeground=C["green"],
                       font=self.f, borderwidth=0, relief="flat")
        for label, action in ((self.t("cut"), "cut"), (self.t("copy"), "copy"),
                              (self.t("paste"), "paste"),
                              (self.t("select_all"), "all")):
            menu.add_command(label=label,
                             command=lambda a=action, w=widget: self.edit(w, a))

        def popup(event):
            widget.focus_set()
            menu.tk_popup(event.x_root, event.y_root)
            menu.grab_release()

        widget.bind("<Button-3>", popup)
        return widget

    # -- layout ------------------------------------------------------------

    def build(self):
        pad = dict(padx=16)

        head = tk.Frame(self.root, bg=C["bg"])
        head.pack(fill="x", pady=(14, 2), **pad)
        tk.Label(head, text=APP, bg=C["bg"], fg=C["green"], font=self.fh).pack(side="left")
        # Settings sits top right, out of the way of the things you touch on
        # every run. The hint beside it is the one thing worth seeing without
        # opening the dialog: what is currently switched on.
        self.button(head, self.t("settings"), self.open_settings,
                    "cyan").pack(side="right", pady=(2, 0))
        self.settings_hint = tk.Label(head, bg=C["bg"], fg=C["dim"], font=self.f)
        self.settings_hint.pack(side="right", padx=(0, 12), pady=(5, 0))
        self.refresh_hint()

        tk.Frame(self.root, bg=C["line"], height=1).pack(fill="x", pady=(8, 12), **pad)

        row = tk.Frame(self.root, bg=C["bg"])
        row.pack(fill="x", **pad)
        tk.Label(row, text=self.t("source"), bg=C["bg"], fg=C["green"],
                 font=self.fb).pack(side="left", padx=(0, 10))
        self.url = self.entry(row, textvariable=self.url_var)
        self.url.pack(side="left", fill="x", expand=True, ipady=5)
        self.url.bind("<Return>", lambda _e: self.do_scan())
        self.scan_btn = self.button(row, self.t("scan"), self.do_scan)
        self.scan_btn.pack(side="left", padx=(8, 0))
        self.button(row, self.t("clear"), self.do_clear,
                    "dim").pack(side="left", padx=(6, 0))
        self.refresh_btn = self.button(row, self.t("refresh"), self.do_refresh, "cyan")
        self.refresh_btn.pack(side="left", padx=(6, 0))

        out = tk.Frame(self.root, bg=C["bg"])
        out.pack(fill="x", pady=(12, 0), **pad)
        self.label(out, self.t("save_to")).pack(side="left")
        # Download goes on first so it keeps the right-hand end whatever the
        # path is doing, and the path box no longer swallows the whole row -
        # a download folder is a short piece of text that was given the width
        # of a URL.
        self.outdir = self.entry(out, width=46, textvariable=self.outdir_var)
        self.outdir.pack(side="left", padx=(6, 6), ipady=3)
        self.button(out, self.t("browse"), self.pick_dir, "cyan").pack(side="left")
        self.button(out, self.t("open"), self.open_dir,
                    "cyan").pack(side="left", padx=(6, 0))
        # Right beside the folder it will download into, and the biggest thing
        # on the row - it is what every visit to this window is for.
        self.dl_btn_top = self.button(out, self.t("download"), self.do_download,
                                      "amber", big=True)
        self.dl_btn_top.pack(side="left", padx=(18, 0))
        # Private mode is a per-run decision - it is deliberately not
        # remembered - so it belongs where the run starts rather than three
        # clicks deep. The dialog keeps its copy and its explanation; both
        # drive the same variable, so either one moves the other.
        self.private_box = tk.Checkbutton(
            out, text=self.t("dlg_private"), variable=self.private_var,
            bg=C["bg"], fg=C["dim"], font=self.f, selectcolor=C["panel"],
            activebackground=C["bg"], activeforeground=C["green"],
            highlightthickness=0, borderwidth=0, cursor="hand2")
        self.private_box.pack(side="right")
        self.tor_box = tk.Checkbutton(
            out, text=self.t("dlg_tor"), variable=self.tor_var,
            bg=C["bg"], fg=C["dim"], font=self.f, selectcolor=C["panel"],
            activebackground=C["bg"], activeforeground=C["green"],
            highlightthickness=0, borderwidth=0, cursor="hand2")
        self.tor_box.pack(side="right", padx=(0, 14))

        # --- results: list on the left, preview on the right ---------------
        wrap = tk.Frame(self.root, bg=C["bg"])
        wrap.pack(fill="both", expand=True, pady=(14, 0), **pad)

        # Packed further down, after the preview pane. When the two together
        # want more width than there is, pack squeezes whichever was packed
        # last - and with a wide NAME column the list wants plenty, which had
        # the preview collapsing to a strip. The list is the one that can give
        # way: its columns shrink, the preview just gets smaller.
        left = tk.Frame(wrap, bg=C["bg"])
        # Every row of one video carries the same title, so it is said once here
        # and the NAME column is dropped rather than repeated ten times across
        # the widest part of a maximised window.
        self.source_line = tk.Label(left, bg=C["bg"], fg=C["fg"], font=self.fb,
                                    anchor="w")
        self.table = tk.Frame(left, bg=C["bg"])
        self.table.pack(fill="both", expand=True)
        # The checkbox lives in the tree column (#0) because that is the only
        # one Treeview will draw an image in, so "tree headings" rather than
        # the "headings" this used when the mark was the text "[x]".
        self.boxes = checkbox_images()
        self.tree = ttk.Treeview(self.table,
                                 columns=("kind", "quality", "res", "length",
                                          "size", "info", "name"),
                                 show="tree headings", style="T.Treeview",
                                 selectmode="extended")
        self.tree.heading("#0", text="")
        self.tree.column("#0", width=38, minwidth=38, stretch=False,
                         anchor="center")
        # Everything is centred, heading and cell alike, so a column reads as
        # one block instead of contents hugging one edge under a title hugging
        # the other. INFO and NAME both stretch: NAME folds away for a single
        # video, and without a second stretching column the table would stop
        # short and leave dead space to the right of it.
        for col, txt, w in (("kind", self.t("col_type"), 86),
                            ("quality", self.t("col_quality"), 116),
                            ("res", self.t("col_res"), 112),
                            ("length", self.t("col_length"), 76),
                            ("size", self.t("col_size"), 76),
                            ("info", self.t("col_info"), 190),
                            ("name", self.t("col_name"), 240)):
            self.tree.heading(col, text=txt, anchor="center")
            self.tree.column(col, width=w, anchor="center", minwidth=56,
                             stretch=(col in ("info", "name")))
        sb = ttk.Scrollbar(self.table, orient="vertical", command=self.tree.yview,
                           style="T.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for kind, colour in TAG_COLOURS.items():
            self.tree.tag_configure(kind, foreground=colour)
        self.tree.tag_configure("marked", background=C["line"])
        self.tree.bind("<Button-1>", self.on_row_click)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.show_preview())
        self.tree.bind("<Double-1>", self.on_double_click)
        # Marking was mouse-only: arrow keys moved the selection but there was
        # no way to actually mark a row without clicking it.
        self.tree.bind("<space>", self.on_row_key)
        self.tree.bind("<Return>", self.on_row_key)
        self.root.bind_all("<Control-KeyPress>", self.on_ctrl)

        self.preview_w = PREVIEW_W
        self.right = tk.Frame(wrap, bg=C["panel"], width=PREVIEW_W + 20)
        self.right.pack(side="right", fill="y", padx=(12, 0))
        left.pack(side="left", fill="both", expand=True)
        self.right.pack_propagate(False)
        self.thumb_box = tk.Label(self.right, bg=C["panel"], fg=C["dim"], font=self.f,
                                  text="\n\n" + self.t("preview_hint"), justify="center")
        self.thumb_box.pack(pady=(10, 6), padx=10)
        self.meta_box = tk.Label(self.right, bg=C["panel"], fg=C["dim"], font=self.f,
                                 justify="left", anchor="nw",
                                 wraplength=PREVIEW_W, text="")
        self.meta_box.pack(fill="x", padx=10)
        self.thumb_ref = None   # PhotoImage must outlive this call
        self.thumb_img = None   # the full-size PIL copy, to redraw on a resize
        self.thumb_cache: dict[str, object] = {}
        self.preview_token = 0  # ignore thumbnails that arrive after a new pick
        wrap.bind("<Configure>", self.on_wrap_resize)

        # --- log panel, hidden until asked for or until something breaks ---
        self.log_frame = tk.Frame(self.root, bg=C["bg"])
        self.log_text = tk.Text(self.log_frame, height=8, bg=C["panel"], fg=C["fg"],
                                font=(self.mono, 9), relief="flat", wrap="word",
                                insertbackground=C["green"],
                                highlightthickness=1, highlightbackground=C["line"])
        log_sb = ttk.Scrollbar(self.log_frame, orient="vertical",
                               command=self.log_text.yview,
                               style="T.Vertical.TScrollbar")
        self.log_text.configure(yscrollcommand=log_sb.set, state="disabled")
        self.log_text.pack(side="left", fill="both", expand=True)
        log_sb.pack(side="right", fill="y")
        for level, colour in (("info", C["dim"]), ("ok", C["green"]),
                              ("warn", C["amber"]), ("error", C["red"])):
            self.log_text.tag_configure(level, foreground=colour)

        tk.Frame(self.root, bg=C["line"], height=1).pack(fill="x", pady=(12, 0), **pad)
        bar = tk.Frame(self.root, bg=C["bg"])
        bar.pack(fill="x", pady=(8, 14), **pad)
        # Log controls sit hard right; the action group - status, bar, download -
        # stays together on the left where the size total already is.
        self.button(bar, self.t("log"), self.toggle_log,
                    "cyan").pack(side="right", padx=(6, 0))
        self.button(bar, self.t("copy_log"), self.copy_log,
                    "cyan").pack(side="right")

        self.status = tk.Label(bar, text=self.t("ready"), bg=C["bg"], fg=C["dim"],
                               font=self.f, anchor="w", width=STATUS_CHARS)
        # what fit_status is allowed to fill, in pixels, from the same font the
        # label draws with
        self.status_px = self.f.measure("0" * STATUS_CHARS)
        self.status.pack(side="left")
        self.prog = ttk.Progressbar(bar, style="T.Horizontal.TProgressbar",
                                    length=200, maximum=100)
        self.prog.pack(side="left", padx=(10, 10))
        self.dl_btn = self.button(bar, self.t("download"), self.do_download,
                                  "amber", big=True)
        self.dl_btn.pack(side="left")
        self.stop_btn = self.button(bar, self.t("stop"), self.stop_all, "red")

    # -- marking, preview, log --------------------------------------------

    def on_row_click(self, event):
        """Only the checkbox marks a row. A click anywhere else just shows it.

        Marking used to happen wherever you clicked, so there was no way to
        look at a row without queueing it - and looking is the more common
        thing to want. Everything outside the box is left to Treeview, which
        also keeps shift and ctrl selecting ranges the way they should.
        """
        # "tree" is the checkbox column; "cell" is the rest of the row.
        if self.tree.identify("region", event.x, event.y) != "tree":
            return None
        row = self.tree.identify_row(event.y)
        if not row:
            return None
        if self.busy:
            self.pull_from_queue(row)
        else:
            self.toggle_mark(row)
        self.tree.selection_set(row)  # ticking it shows it too
        return "break"

    def on_double_click(self, _event):
        """Start the download, if the user asked for that to be a thing.

        Off unless switched on: the first click of the pair has already marked
        or unmarked the row, so a stray double click would queue whatever was
        under the pointer.
        """
        if self.dblclick_var.get():
            self.do_download()
        return "break"

    def on_row_key(self, _event):
        """Space or Return on the focused row - the keyboard twin of a click."""
        row = self.tree.focus()
        if not row:
            return None
        if self.busy:
            self.pull_from_queue(row)
        else:
            self.toggle_mark(row)
        return "break"

    def pull_from_queue(self, row):
        """Click a row mid-download to drop it. The in-flight one aborts at its
        next chunk, which is the way out when a server stops responding."""
        index = self.tree.index(row)
        if index in self.cancelled:
            return
        self.cancelled.add(index)
        self.tree.item(row, image=self.boxes["cut"])
        self.log(f"pulled from queue :: {self.items[index].name}", "warn")
        self.say(self.t("pulled", n=len(self.cancelled)), C["amber"])

    def stop_all(self):
        if not self.busy:
            return
        if self.scanning:
            # The request itself keeps running until the socket gives up - that
            # is the one thing a thread cannot be talked out of. What stopping
            # can do is give the window back now and ignore the answer.
            self.scanning = False
            self.scan_token += 1
            self.log("stop :: scan abandoned, the request winds down on its own",
                     "warn")
            self.say(self.t("stopping"), C["amber"])
            self.q.put(("busy", False, None))
            self.q.put(("hide_stop", None, None))
            return
        self.cancelled.update(range(len(self.items)))
        for row in self.tree.get_children():
            self.tree.item(row, image=self.boxes["cut"])
        self.log("stop :: cancelling everything still queued", "warn")
        self.say(self.t("stopping"), C["amber"])

    def do_clear(self):
        """Empty the link box and the results with it."""
        if self.busy:
            return
        self.url_var.set("")
        self.tree.delete(*self.tree.get_children())
        self.items = []
        self.marked.clear()
        self.sized.clear()
        self.show_source_line([])
        self.clear_thumb(self.t("preview_hint"))
        self.meta_box.config(text="")
        self.url.focus_set()
        self.say(self.t("ready"))

    def do_refresh(self):
        """Re-scan the link that is already in the box."""
        if self.busy or not self.url.get().strip():
            return
        self.log("refresh", "info")
        self.do_scan()

    def toggle_mark(self, row, force=None):
        on = (row not in self.marked) if force is None else force
        if on:
            self.marked.add(row)
        else:
            self.marked.discard(row)
        self.tree.item(row, image=self.boxes["on" if on else "off"])
        tags = [t for t in self.tree.item(row, "tags") if t != "marked"]
        self.tree.item(row, tags=tags + (["marked"] if on else []))
        self.count_marks()

    def mark_all(self, on=True):
        for row in self.tree.get_children():
            self.toggle_mark(row, force=on)

    def count_marks(self):
        n = len(self.marked)
        if not n:
            self.say(self.t("nothing_marked"))
            return
        total = sum(self.items[self.tree.index(r)].size for r in self.marked)
        self.say(self.t("marked", n=n, size=human(total)), C["green"])

    # Quality is mostly technical strings - "1080p mp4", "mp3 320k" - which are
    # the same in every language and stay put. These few are ordinary words
    # standing in for a value, so they get translated like any other label.
    QUALITY_WORDS = {"as set": "q_as_set", "original": "q_original",
                     "audio": "q_audio"}

    def info_cell(self, it: Item, here: set[str]) -> str:
        """The INFO column, with a word when the file is already downloaded."""
        if not already_here(here, it):
            return it.info
        return " :: ".join(b for b in (self.t("have_already"), it.info) if b)

    def quality_text(self, quality: str) -> str:
        key = self.QUALITY_WORDS.get(quality)
        return self.t(key) if key else quality

    def show_source_line(self, items):
        """Name the thing that was scanned, once, above the list.

        A single video hands back one row per resolution, all sharing a title,
        so the NAME column was the same string over and over - and on a
        maximised window that string had the most space of anything on screen.
        When the rows disagree, as they do for a scraped page, NAME is the only
        thing telling them apart and stays.
        """
        names = {it.name for it in items}
        shared = items and len(names) == 1
        columns = ("kind", "quality", "res", "length", "size", "info")
        if shared:
            self.source_line.config(text=next(iter(names)))
            self.source_line.pack(before=self.table, fill="x", pady=(0, 8))
            self.tree.configure(displaycolumns=columns)
        else:
            self.source_line.pack_forget()
            self.tree.configure(displaycolumns=columns + ("name",))

    def show_preview(self):
        rows = self.tree.selection()
        if not rows:
            return
        index = self.tree.index(rows[0])
        it = self.items[index]
        self.measure(index, it)
        self.preview_token += 1
        token = self.preview_token
        head_bits = "  ".join(b for b in (self.t("kind_" + it.kind),
                                          self.quality_text(it.quality),
                                          it.res) if b)
        block = [f"{head_bits}  ::  {human(it.size)}", "", it.name]
        if it.details:
            block += ["", it.details]
        block += ["", it.url[:200]]
        self.meta_box.config(text="\n".join(block))
        if not it.thumb:
            self.clear_thumb(self.t("no_preview"))
            return
        cached = self.thumb_cache.get(it.thumb)
        if cached is not None:
            # False is remembered failure; anything else is a PIL image
            if cached:
                self.show_thumb(cached)
            else:
                self.clear_thumb(self.t("preview_failed"))
            return
        self.clear_thumb(self.t("loading"))
        threading.Thread(
            target=self._thumb_worker,
            args=(it.thumb, it.url if it.kind == "image" else "", token,
                  self.proxy()),
            daemon=True).start()

    def measure(self, index: int, it: Item):
        """Fill in a row's size the first time it is opened.

        The discreet scan measures nothing up front, so this is where a row
        gets its size: one HEAD, for the row you actually looked at. Rows that
        came back with a size already, and yt-dlp's rows - whose URL is a page
        rather than a file - are left alone.
        """
        if it.size or it.via == "ytdlp" or index in self.sized:
            return
        self.sized.add(index)
        threading.Thread(
            target=self._size_worker,
            args=(index, it.url, it.page, self.scan_token,
                  self.proxy()),
            daemon=True).start()

    def _size_worker(self, index, url, referer, token, proxy):
        size, ctype, offered = head(session_for(proxy), url, referer)
        self.q.put(("size", (index, size, token, offered), ctype))

    def _thumb_worker(self, url, real_url, token, proxy):
        try:
            from PIL import ImageTk  # noqa: F401  (imported for the main thread)
            import io
            Image = pillow()
            session = session_for(proxy)
            r = session.get(url, timeout=20, stream=True)
            r.raise_for_status()
            # ponytail: cap the fetch - a preview never needs a 40 MB original
            data = r.raw.read(PREVIEW_MAX_BYTES + 1, decode_content=True)
            img = Image.open(io.BytesIO(data))
            dims = f"{img.width}x{img.height}"
            # sized for the widest the pane can get, so growing the window
            # redraws from real pixels rather than upscaling a small copy
            img.thumbnail((PREVIEW_MAX, PREVIEW_MAX), Image.LANCZOS)
            # The preview may be a thumbnail while the download is the upgraded
            # original. Reporting the preview's size would be a lie about what
            # you are about to get, so measure the real file's header instead.
            if real_url and real_url != url:
                dims = image_dimensions(session, real_url) or ""
            self.q.put(("thumb", (url, token, img), dims))
        except Exception as exc:
            self.q.put(("thumb", (url, token, None), str(exc)))

    def fill_dimensions(self, thumb_url, dims):
        """Write an image's real size into its INFO cell once the preview has
        told us what it is. Free - the bytes were fetched for the preview."""
        if not dims:
            return
        for i, it in enumerate(self.items):
            if it.thumb == thumb_url and it.kind == "image" and not it.res:
                it.res = dims
                rows = self.tree.get_children()
                if i < len(rows):
                    self.tree.set(rows[i], "res", dims)

    def clear_thumb(self, text=""):
        """No picture: a line of explanation where the picture would be."""
        self.thumb_ref = self.thumb_img = None
        self.thumb_box.config(image="", text=f"\n\n{text}", height=12, width=30)

    def show_thumb(self, img):
        """Draw a preview at whatever width the pane happens to have now.

        The full-size copy is kept so a resize can redraw from it - scaling the
        already-shrunk one back up would just look soft.
        """
        from PIL import Image, ImageTk
        self.thumb_img = img
        shown = img.copy()
        shown.thumbnail((self.preview_w, self.preview_w), Image.LANCZOS)
        self.thumb_ref = ImageTk.PhotoImage(shown)
        self.thumb_box.config(image=self.thumb_ref, text="", height=0, width=0)

    def on_wrap_resize(self, event):
        """Hand the preview a share of the window instead of a fixed 240px.

        Maximised on a wide screen the list had far more width than its columns
        could use while the preview stayed postage-stamp sized. The list still
        takes whatever is left over, and shrinking the window walks it back.
        """
        want = max(PREVIEW_W, min(PREVIEW_MAX, int(event.width * PREVIEW_SHARE)))
        if want == self.preview_w:
            return          # Configure fires per pixel of a drag; most are noise
        self.preview_w = want
        self.right.config(width=want + 20)
        self.meta_box.config(wraplength=want)
        if self.thumb_img is not None:
            self.show_thumb(self.thumb_img)

    def toggle_log(self):
        if self.log_frame.winfo_ismapped():
            self.log_frame.pack_forget()
        else:
            self.log_frame.pack(fill="both", expand=False, padx=16, pady=(10, 0))

    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.log_text.get("1.0", "end").strip())
        self.say(self.t("log_copied"), C["cyan"])

    def log(self, text, level="info"):
        self.q.put(("log", (level, text), None))

    def _write_log(self, level, text):
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"{time.strftime('%H:%M:%S')}  {text}\n", level)
        self.log_text.see("end")
        self.log_text.config(state="disabled")
        if level == "error" and not self.log_frame.winfo_ismapped():
            self.toggle_log()  # a failure should never be silent

    # -- settings ----------------------------------------------------------

    def refresh_hint(self):
        """One line in the main bar showing what settings are actually on."""
        bits = []
        if self.private_var.get():
            # Worth saying plainly: private mode keeps this machine clean, it
            # does not hide the download from the other end. Only a proxy does
            # anything about the address the site sees.
            bits.append(self.t("chip_private" if self.proxy()
                               else "chip_private_bare"))
        if self.tor_var.get():
            # Cookies say who you are, which is the one thing an anonymous
            # route cannot take back. Worth saying while both are on.
            bits.append(self.t("chip_tor_cookies" if self.cookies()
                               else "chip_tor"))
        elif normalise_proxy(self.proxy_var.get()):
            bits.append(self.t("chip_proxy"))
        if self.cookies():
            bits.append(self.t("chip_cookies", name=self.cookies()))
        if self.clean_var.get():
            bits.append(self.t("chip_strip"))
        if not ffmpeg_path():
            bits.append(self.t("chip_no_ffmpeg"))
        self.settings_hint.config(text="  ".join(bits))

    def open_settings(self):
        win = tk.Toplevel(self.root)
        win.title(self.t("dlg_title"))
        win.configure(bg=C["bg"])
        win.transient(self.root)
        win.resizable(False, True)

        # The dialog had grown past 860px, which puts save and cancel below the
        # bottom edge of a 768p laptop screen - a dialog you cannot agree to.
        # The buttons are pinned outside the scrolling area so they are always
        # reachable, and the settings themselves scroll when they have to.
        foot = tk.Frame(win, bg=C["bg"])
        foot.pack(side="bottom", fill="x", padx=20, pady=(10, 16))

        outer = tk.Frame(win, bg=C["bg"])
        outer.pack(side="top", fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=C["bg"], highlightthickness=0, bd=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview,
                               style="T.Vertical.TScrollbar")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        body = tk.Frame(canvas, bg=C["bg"])
        holder = canvas.create_window((0, 0), window=body, anchor="nw")

        def reflow(_e=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(holder, width=canvas.winfo_width())

        body.bind("<Configure>", reflow)
        canvas.bind("<Configure>", reflow)
        # Bound on the toplevel rather than the canvas: a wheel event over one
        # of the entries would otherwise never reach the thing that scrolls.
        win.bind("<MouseWheel>",
                 lambda e: canvas.yview_scroll(-e.delta // 120, "units"))

        def head(text):
            tk.Label(body, text=text, bg=C["bg"], fg=C["green"], font=self.fb,
                     anchor="w").pack(fill="x", padx=20, pady=(12, 3))

        def section(title):
            """A heading with a rule above it.

            Thirteen settings in one column read as a list to get through. They
            fall into three questions - where a download goes, who gets to know
            about it, and how the window behaves - and the ones that answer the
            same question now sit together.
            """
            tk.Frame(body, bg=C["line"], height=1).pack(
                fill="x", padx=20, pady=(18, 0))
            tk.Label(body, text=title.upper(), bg=C["bg"], fg=C["cyan"],
                     font=self.fb, anchor="w").pack(fill="x", padx=20,
                                                    pady=(8, 2))

        def hint(text):
            label = tk.Label(body, text=text, bg=C["bg"], fg=C["dim"],
                             font=self.f, anchor="w", justify="left")
            label.pack(fill="x", padx=20, pady=(2, 0))
            return label

        section(self.t("sec_download"))
        # download folder --------------------------------------------------
        head(self.t("save_to"))
        folder = tk.Frame(body, bg=C["bg"])
        folder.pack(fill="x", padx=20)
        self.entry(folder, width=40, textvariable=self.outdir_var).pack(
            side="left", fill="x", expand=True, ipady=3)
        self.button(folder, self.t("browse"), self.pick_dir,
                    "cyan").pack(side="left", padx=(6, 0))

        # quality ----------------------------------------------------------
        # Only reachable here because it only ever applies to playlists and to
        # pages that hand over no format list. Anywhere the scan could read the
        # formats, every resolution is its own row and this is ignored.
        head(self.t("quality"))
        ttk.Combobox(body, values=list(FORMATS), state="readonly", width=18,
                     style="T.TCombobox", font=self.f,
                     textvariable=self.quality_var).pack(anchor="w", padx=20)
        hint(self.t("dlg_quality_hint"))

        tk.Checkbutton(body, text=self.t("dlg_subs"), variable=self.subs_var,
                       bg=C["bg"], fg=C["fg"], font=self.fb, selectcolor=C["panel"],
                       activebackground=C["bg"], activeforeground=C["green"],
                       highlightthickness=0, borderwidth=0,
                       cursor="hand2", anchor="w").pack(fill="x", padx=20)
        hint(self.t("dlg_subs_hint"))

        head(self.t("dlg_parallel"))
        tk.Spinbox(body, from_=1, to=MAX_PARALLEL, width=5,
                   textvariable=self.parallel_var,
                   bg=C["panel"], fg=C["fg"], font=self.f, relief="flat",
                   buttonbackground=C["line"], insertbackground=C["green"],
                   highlightthickness=1,
                   highlightbackground=C["line"]).pack(anchor="w", padx=20)
        hint(self.t("dlg_parallel_hint"))

        head(self.t("dlg_attempts"))
        tk.Spinbox(body, from_=1, to=10, width=5, textvariable=self.attempts_var,
                   bg=C["panel"], fg=C["fg"], font=self.f, relief="flat",
                   buttonbackground=C["line"], insertbackground=C["green"],
                   highlightthickness=1,
                   highlightbackground=C["line"]).pack(anchor="w", padx=20)

        head(self.t("dlg_ffmpeg"))
        ff = ffmpeg_path()
        tk.Label(body, text=ff or self.t("dlg_ffmpeg_missing"), bg=C["bg"],
                 fg=C["fg"] if ff else C["amber"], font=self.f, anchor="w",
                 wraplength=420, justify="left").pack(fill="x", padx=20)

        section(self.t("sec_privacy"))
        tk.Checkbutton(body, text=self.t("dlg_tor"), variable=self.tor_var,
                       bg=C["bg"], fg=C["fg"], font=self.fb, selectcolor=C["panel"],
                       activebackground=C["bg"], activeforeground=C["green"],
                       highlightthickness=0, borderwidth=0,
                       cursor="hand2", anchor="w").pack(fill="x", padx=20)
        hint(self.t("dlg_tor_hint"))

        tk.Checkbutton(body, text=self.t("dlg_private"), variable=self.private_var,
                       bg=C["bg"], fg=C["fg"], font=self.fb, selectcolor=C["panel"],
                       activebackground=C["bg"], activeforeground=C["green"],
                       highlightthickness=0, borderwidth=0,
                       cursor="hand2", anchor="w").pack(fill="x", padx=20)
        hint(self.t("dlg_private_hint"))

        # proxy ------------------------------------------------------------
        head(self.t("dlg_proxy"))
        proxy_entry = self.entry(body, width=46, textvariable=self.proxy_var)
        proxy_entry.pack(fill="x", padx=20, ipady=3)
        proxy_note = hint(self.t("dlg_proxy_hint"))

        # Whether any of this is working is otherwise a matter of faith: the
        # box is ticked, the requests go somewhere, and nothing on screen says
        # where. One button, one answer, from Tor's own checking service.
        route_row = tk.Frame(body, bg=C["bg"])
        route_row.pack(fill="x", padx=20, pady=(6, 0))
        self.button(route_row, self.t("dlg_route"), self.check_route,
                    "cyan").pack(side="left")
        self.route_label = tk.Label(route_row, text="", bg=C["bg"],
                                    fg=C["dim"], font=self.f, anchor="w")
        self.route_label.pack(side="left", padx=(10, 0))

        # cookies ----------------------------------------------------------
        head(self.t("dlg_cookies"))
        cookie_box = ttk.Combobox(body, values=COOKIE_BROWSERS, state="readonly",
                                  width=18, style="T.TCombobox", font=self.f,
                                  textvariable=self.cookies_var)
        cookie_box.pack(anchor="w", padx=20)
        cookie_note = hint(self.t("dlg_cookies_hint"))

        def sync(*_a):
            """Grey out what is not in use, and say why.

            The cookie box went on showing "firefox" while the private session
            was quietly sending none, and the proxy box went on showing an
            address that tor was overriding. Both were the window saying one
            thing while the code did another.
            """
            private, tor = self.private_var.get(), self.tor_var.get()
            cookie_box.configure(state="disabled" if private else "readonly")
            cookie_note.configure(
                text=self.t("cookies_off_private") if private
                else self.t("dlg_cookies_hint"))
            proxy_entry.configure(state="disabled" if tor else "normal")
            proxy_note.configure(
                text=self.t("proxy_ignored_tor") if tor
                else self.t("dlg_proxy_hint"))

        watched = [(var, var.trace_add("write", sync))
                   for var in (self.private_var, self.tor_var)]
        # The traces outlive the dialog otherwise, and fire against destroyed
        # widgets the next time either box is ticked in the main bar.
        win.bind("<Destroy>", lambda e: (
            [var.trace_remove("write", name) for var, name in watched]
            if e.widget is win else None), add="+")
        sync()

        tk.Checkbutton(body, text=self.t("dlg_quiet"), variable=self.quiet_var,
                       bg=C["bg"], fg=C["fg"], font=self.fb, selectcolor=C["panel"],
                       activebackground=C["bg"], activeforeground=C["green"],
                       highlightthickness=0, borderwidth=0,
                       cursor="hand2", anchor="w").pack(fill="x", padx=20)
        hint(self.t("dlg_quiet_hint"))

        # metadata + attempts ----------------------------------------------
        tk.Checkbutton(body, text=self.t("dlg_strip"), variable=self.clean_var,
                       bg=C["bg"], fg=C["fg"], font=self.fb, selectcolor=C["panel"],
                       activebackground=C["bg"], activeforeground=C["green"],
                       highlightthickness=0, borderwidth=0,
                       cursor="hand2", anchor="w").pack(fill="x", padx=20)
        hint(self.t("dlg_strip_hint"))

        section(self.t("sec_window"))
        # language ---------------------------------------------------------
        head(self.t("dlg_language"))
        names = list(LANGUAGES.values())
        lang_box = ttk.Combobox(body, values=names, state="readonly", width=18,
                                style="T.TCombobox", font=self.f)
        lang_box.set(LANGUAGES[self.t.lang])
        lang_box.pack(anchor="w", padx=20)
        hint(self.t("dlg_lang_note"))

        tk.Checkbutton(body, text=self.t("dlg_dblclick"), variable=self.dblclick_var,
                       bg=C["bg"], fg=C["fg"], font=self.fb, selectcolor=C["panel"],
                       activebackground=C["bg"], activeforeground=C["green"],
                       highlightthickness=0, borderwidth=0,
                       cursor="hand2", anchor="w").pack(fill="x", padx=20)
        hint(self.t("dlg_dblclick_hint"))

        # buttons ----------------------------------------------------------
        # Every widget above writes straight into the shared variable, so
        # cancel has to put the old values back. Without this it only skipped
        # writing settings.json: a tick you took back stayed on for the rest of
        # the session, which is the one thing cancel promises not to do.
        touched = (self.outdir_var, self.proxy_var, self.quality_var,
                   self.cookies_var, self.clean_var, self.private_var,
                   self.tor_var, self.dblclick_var, self.quiet_var,
                   self.subs_var, self.parallel_var, self.attempts_var)
        before = [v.get() for v in touched]

        def cancel():
            for var, was in zip(touched, before):
                if var.get() != was:      # private_var traces on write
                    var.set(was)
            win.destroy()

        def apply_and_close():
            chosen = next((code for code, name in LANGUAGES.items()
                           if name == lang_box.get()), self.t.lang)
            changed = chosen != self.t.lang
            self.t.set(chosen)
            self.remember()
            self.refresh_hint()
            win.destroy()
            if changed:
                self.rebuild()

        self.button(foot, self.t("save"), apply_and_close,
                    "green").pack(side="right")
        self.button(foot, self.t("cancel"), cancel,
                    "dim").pack(side="right", padx=(0, 8))

        win.bind("<Escape>", lambda _e: cancel())
        # the window's own X is a cancel too, not a quiet save
        win.protocol("WM_DELETE_WINDOW", cancel)
        win.update_idletasks()
        reflow()
        wide = body.winfo_reqwidth() + scroll.winfo_reqwidth() + 8
        tall = body.winfo_reqheight() + foot.winfo_reqheight() + 26
        tall = min(tall, int(win.winfo_screenheight() * 0.82))
        x = self.root.winfo_rootx() + (self.root.winfo_width() - wide) // 2
        y = self.root.winfo_rooty() + 60
        # keep it on screen even when the main window sits low
        y = min(y, max(0, win.winfo_screenheight() - tall - 40))
        win.geometry(f"{wide}x{tall}+{max(x, 0)}+{max(y, 0)}")
        win.grab_set()

    def rebuild(self):
        """Redraw the whole window in the new language, keeping the results."""
        items, marked = self.items, {self.tree.index(r) for r in self.marked}
        for child in self.root.winfo_children():
            child.destroy()
        self.marked.clear()
        self.build()
        if items:
            self.q.put(("items", items, None))
            # pump() reschedules itself on the way out, so the tick that is
            # already pending has to go first - otherwise every language change
            # leaves another loop running, and close() only cancels the last.
            self.root.after_cancel(self.tick)
            self.pump()
            for i, row in enumerate(self.tree.get_children()):
                if i in marked:
                    self.toggle_mark(row, force=True)

    # -- actions -----------------------------------------------------------

    def pick_dir(self):
        d = filedialog.askdirectory(
            initialdir=self.outdir_var.get() or os.path.expanduser("~"))
        if d:
            self.outdir_var.set(d)

    def open_dir(self):
        d = self.outdir_var.get().strip() or os.getcwd()
        os.makedirs(d, exist_ok=True)
        # webbrowser hands file:// to the *browser*, and mangles a path with a
        # space or a '#' in it on the way. The shell opens the file manager.
        if hasattr(os, "startfile"):
            os.startfile(d)
        else:
            webbrowser.open("file://" + d)

    def fit_status(self, text: str) -> str:
        """Trim a status line to what the label can actually show.

        Measured against the font rather than counted in characters: the same
        message in Greek is a good deal longer than in English, so a character
        limit that suits one clips the other mid-word. The log keeps the whole
        line regardless.
        """
        if self.f.measure(text) <= self.status_px:
            return text
        while text and self.f.measure(text + "...") > self.status_px:
            text = text[:-1]
        return text.rstrip() + "..."

    def say(self, text, colour=None):
        self.q.put(("status", text, colour or C["dim"]))

    def do_scan(self):
        if self.busy:
            return
        url = self.url.get().strip()
        if not url:
            self.say(self.t("paste_first"), C["amber"])
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
            self.url.delete(0, "end")
            self.url.insert(0, url)
        self.set_busy(True)
        self.scanning = True
        self.new_circuit()
        self.scan_token += 1
        self.tree.delete(*self.tree.get_children())
        self.items = []
        self.marked.clear()
        self.sized.clear()
        self.stop_btn.pack(side="left", padx=(6, 0))
        threading.Thread(target=self._scan_worker, args=(url, self.scan_token),
                         daemon=True).start()

    def _scan_worker(self, url, token):
        self.log(f"scan {url}")
        if not self.ytdlp_checked:
            # Deliberately here rather than at launch: this way it goes out the
            # same way the scan does, and only once somebody is actually
            # scanning something.
            self.ytdlp_checked = True
            threading.Thread(target=update_ytdlp, args=(self.log, self.proxy()),
                             daemon=True).start()
        try:
            items = scan(url, self.proxy(), self.say,
                         self.cookies(),
                         self.t("no_video", site=urlparse(url).netloc),
                         self.t("try_cookies"), self.workers(),
                         bool(self.quiet_var.get()), self.t("scanning"))
            if token != self.scan_token:
                self.log(f"scan finished after being stopped, result dropped "
                         f":: {url}", "warn")
                return
            self.q.put(("items", items, None))
            if items:
                self.log(f"found {len(items)} items", "ok")
                self.say(self.t("found", n=len(items)), C["green"])
            else:
                self.log("nothing downloadable found at this link", "warn")
                self.say(self.t("nothing_found"), C["amber"])
        except Exception as exc:
            if token != self.scan_token:
                self.log(f"stopped scan failed on its way out :: {exc}", "warn")
                return
            self.say(self.t("scan_failed", err=exc), C["red"])
            self.log(f"scan failed :: {exc}", "error")
            self.log(traceback.format_exc().rstrip(), "error")
        finally:
            # A stopped scan already handed the window back; saying so again
            # here would undo whatever the user started in the meantime.
            if token == self.scan_token:
                self.scanning = False
                self.q.put(("busy", False, None))
                self.q.put(("hide_stop", None, None))

    def do_download(self):
        if self.busy:
            return
        rows = ([r for r in self.tree.get_children() if r in self.marked]
                or self.tree.get_children())
        picks = [(self.tree.index(r), self.items[self.tree.index(r)]) for r in rows]
        self.cancelled.clear()
        if not picks:
            self.say(self.t("nothing_to_dl"), C["amber"])
            return
        outdir = self.outdir_var.get().strip() or os.getcwd()
        os.makedirs(outdir, exist_ok=True)
        self.remember()
        self.set_busy(True)
        # A download on its own circuit is not the same client as the scan that
        # found it, as far as whoever is carrying the traffic can tell.
        self.new_circuit()
        self.stop_btn.pack(side="left", padx=(6, 0))
        threading.Thread(
            target=self._dl_worker,
            args=(picks, outdir, self.proxy(),
                  self.quality_var.get(), self.clean_var.get(),
                  self.cookies(), self.workers(), self.attempts(),
                  self.t.lang if self.subs_var.get() else ""),
            daemon=True).start()

    def _dl_worker(self, picks, outdir, proxy, quality, clean, cookies="",
                   workers=PARALLEL, tries=ATTEMPTS, subs=""):
        from concurrent.futures import ThreadPoolExecutor

        total_items = len(picks)
        self.log(f"downloading {total_items} item(s), {workers} at a time, to {outdir}")

        # Both dicts are keyed up front and never grow or shrink afterwards:
        # report() iterates them under the lock while workers write without it,
        # and a resize mid-iteration is a RuntimeError waiting to happen.
        frac: dict[int, float] = {i: 0.0 for i, _ in picks}   # index -> 0..1
        speed: dict[int, float | None] = {i: None for i, _ in picks}  # None = not running
        tally = {"ok": 0, "fail": 0, "dropped": 0}
        lock = threading.Lock()
        last_shown = [0.0]
        queued_bytes = sum(i.size for _, i in picks)

        def report(force=False):
            """One status line for the whole batch. Several workers call this,
            so it is rate-limited rather than repainted on every chunk."""
            now = time.monotonic()
            with lock:
                if not force and now - last_shown[0] < 0.25:
                    return
                last_shown[0] = now
                progressed = sum(frac.values())
                live = [v for v in speed.values() if v is not None]
                settled = tally["ok"] + tally["fail"] + tally["dropped"]
            self.q.put(("prog", progressed / total_items * 100, None))
            bits = [f"{settled}/{total_items}"]
            if live:
                bits.append(f"{len(live)} running")
            rate = sum(live)
            if rate:
                bits.append(f"{human(int(rate))}/s")
                left = queued_bytes * (1 - progressed / total_items)
                if left > 0:
                    eta = left / rate
                    bits.append(f"eta {int(eta // 60)}m{int(eta % 60):02d}s")
            self.say("  ".join(bits), C["fg"])

        def run_one(index, it):
            if index in self.cancelled:
                with lock:
                    tally["dropped"] += 1
                self.log(f"skipped (cancelled) :: {it.name}", "warn")
                return
            label = it.name if len(it.name) < 52 else it.name[:49] + "..."
            self.log(f"start :: {it.name} :: {human(it.size)} :: {it.url}")
            started = [time.monotonic()]
            speed[index] = 0.0

            def progress(done, total):
                if index in self.cancelled:
                    raise Cancelled
                frac[index] = (done / total) if total else 0.0
                elapsed = time.monotonic() - started[0]
                speed[index] = done / elapsed if elapsed > 0.5 else 0.0
                report()

            try:
                for attempt in range(1, tries + 1):
                    try:
                        if it.via == "ytdlp":
                            download_media(it, outdir, proxy, quality, clean,
                                           progress, cookies, subs)
                        else:
                            with host_slot(it.url):
                                download_file(it, outdir, proxy, clean, progress,
                                              attempt)
                        with lock:
                            tally["ok"] += 1
                        self.log(f"saved :: {it.name}", "ok")
                        return
                    except Cancelled:
                        with lock:
                            tally["dropped"] += 1
                        self.log(f"cancelled :: {it.name}", "warn")
                        return
                    except Permanent as exc:
                        drop_part(it, outdir)
                        with lock:
                            tally["fail"] += 1
                        self.log(f"FAILED :: {it.name} :: {exc}", "error")
                        return
                    except Exception as exc:
                        if attempt == tries:
                            drop_part(it, outdir)
                            with lock:
                                tally["fail"] += 1
                            self.log(f"FAILED after {tries} tries :: {it.name} "
                                     f":: {exc}", "error")
                            if not isinstance(exc, RateLimited):
                                self.log(traceback.format_exc().rstrip(), "error")
                            return
                        wait = (exc.wait if isinstance(exc, RateLimited)
                                else 2 ** (attempt - 1))  # 1s, 2s, 4s otherwise
                        self.log(f"attempt {attempt} failed ({exc}), "
                                 f"retrying in {wait}s :: {label}", "warn")
                        time.sleep(wait)
                        started[0] = time.monotonic()
            finally:
                frac[index] = 1.0
                speed[index] = None
                report(force=True)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda pair: run_one(*pair), picks))

        ok, fail, dropped = tally["ok"], tally["fail"], tally["dropped"]
        self.q.put(("prog", 100, None))
        tail = self.t("failed_tail", n=fail) if fail else ""
        if dropped:
            tail += self.t("cancelled_tail", n=dropped)
        self.say(self.t("done", ok=ok, tail=tail, dir=outdir),
                 C["red"] if fail and not ok else C["green"])
        self.log(f"done :: {ok} saved, {fail} failed, {dropped} cancelled",
                 "error" if fail else "ok")
        self.q.put(("hide_stop", None, None))
        self.q.put(("busy", False, None))

    def set_busy(self, busy):
        self.busy = busy
        # A disabled ttk.Button also drops out of the Tab order, which the old
        # greyed-out Label did not - the state is now real, not just painted.
        for b in (self.scan_btn, self.dl_btn, self.dl_btn_top, self.refresh_btn):
            b.state(["disabled"] if busy else ["!disabled"])
        if busy:
            self.prog.config(value=0)

    def pump(self):
        try:
            while True:
                kind, a, b = self.q.get_nowait()
                if kind == "status":
                    self.status.config(text=self.fit_status(a), fg=b)
                elif kind == "prog":
                    self.prog.config(value=a)
                elif kind == "busy":
                    self.set_busy(a)
                elif kind == "hide_stop":
                    self.stop_btn.pack_forget()
                elif kind == "log":
                    self._write_log(*a)
                elif kind == "thumb":
                    url, token, img = a
                    if img is None:
                        self.thumb_cache[url] = False
                        if token == self.preview_token:
                            self.clear_thumb(self.t("preview_failed"))
                        self.log(f"preview failed :: {b}", "warn")
                    else:
                        # ponytail: an image each, and a playlist can be 200
                        # rows. Dropping the lot is fine - worst case a
                        # revisited row re-fetches its preview.
                        if len(self.thumb_cache) > MAX_THUMB_CACHE:
                            self.thumb_cache.clear()
                        self.thumb_cache[url] = img
                        if token == self.preview_token:
                            self.show_thumb(img)
                        self.fill_dimensions(url, b)
                elif kind == "route":
                    if self.route_label and self.route_label.winfo_exists():
                        self.route_label.config(text=a)
                elif kind == "size":
                    index, size, token, offered = a
                    rows = self.tree.get_children()
                    if token == self.scan_token and index < len(rows):
                        if "html" in (b or ""):
                            # the discreet scan cannot drop these while it
                            # scans, so the row is called out here instead of
                            # downloading a web page as the file it looks like
                            self.log(f"serves a page, not a file :: "
                                     f"{self.items[index].url}", "warn")
                            size = 0
                        it = self.items[index]
                        it.size = size
                        named = better_name(it.name, offered)
                        if named != it.name:
                            # A row called index.php is the server keeping the
                            # name in a header; opening it is when we find out.
                            it.name = named
                            self.tree.set(rows[index], "name", named)
                        self.tree.set(rows[index], "size",
                                      size_cell(it, True))
                        # the panel was drawn before the size landed
                        if self.tree.selection() == (rows[index],):
                            self.show_preview()
                elif kind == "items":
                    self.items = a
                    outdir = self.outdir_var.get().strip()
                    try:
                        # one listing for the whole batch rather than a stat
                        # per row, and nothing asked of the network at all
                        here = set(os.listdir(outdir)) if outdir else set()
                    except OSError:
                        here = set()
                    for it in a:
                        # kind doubles as the resolution label ("2160p"), so fall
                        # back to the generic media tag for colouring those rows
                        tag = it.kind if it.kind in TAG_COLOURS else "file"
                        self.tree.insert("", "end", tags=(tag,),
                                         image=self.boxes["off"],
                                         values=(self.t("kind_" + it.kind),
                                                 self.quality_text(it.quality),
                                                 it.res, it.length,
                                                 size_cell(it, False),
                                                 self.info_cell(it, here),
                                                 it.name))
                    self.show_source_line(a)
        except queue.Empty:
            pass
        self.tick = self.root.after(80, self.pump)


# --------------------------------------------------------------------------

def selftest():
    import struct
    import tempfile
    import zlib

    exif = b"\xff\xe1" + (2 + 6).to_bytes(2, "big") + b"Exif\x00\x00"
    app0 = b"\xff\xe0" + (2 + 5).to_bytes(2, "big") + b"JFIF\x00"
    jpg = b"\xff\xd8" + exif + app0 + b"\xff\xda\x00\x03\x00" + b"payload" + b"\xff\xd9"
    out = _strip_jpeg(jpg)
    assert b"Exif" not in out, "exif survived"
    assert b"JFIF" in out, "jfif wrongly dropped"
    assert b"payload" in out and out.endswith(b"\xff\xd9"), "image data lost"
    assert _strip_jpeg(b"not a jpeg") is None

    def chunk(t, d=b""):
        return len(d).to_bytes(4, "big") + t + d + struct.pack(">I", zlib.crc32(t + d))

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", b"\x00" * 13)
           + chunk(b"tEXt", b"Comment\x00from-site")
           + chunk(b"IDAT", b"xx") + chunk(b"IEND"))
    out = _strip_png(png)
    assert b"from-site" not in out, "png text survived"
    assert b"IHDR" in out and b"IDAT" in out and b"IEND" in out, "png structure broken"

    assert "https://x.com/a.jpg" in upgrade_image("https://x.com/a-800x600.jpg")
    assert "https://x.com/a.jpg" in upgrade_image("https://x.com/a.jpg?w=300&h=200")
    assert upgrade_image("https://x.com/a.jpg") == []
    wiki = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Cat.jpg/500px-Cat.jpg"
    assert "https://upload.wikimedia.org/wikipedia/commons/a/ab/Cat.jpg" in upgrade_image(wiki)
    assert best_from_srcset("a.jpg 300w, b.jpg 900w", "https://x.com/") == "https://x.com/b.jpg"

    # the probe pool obeys the download setting instead of a hard-coded six, so
    # a site never sees more parallel HEADs than the user asked for
    live, peak, guard = [0], [0], threading.Lock()

    class _CountingSession:
        def head(self, url, **kw):
            with guard:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            time.sleep(0.02)
            with guard:
                live[0] -= 1
            return type("R", (), {"status_code": 200,
                                  "headers": {"content-length": "1",
                                              "content-type": "video/mp4"}})()

    probed = probe_all([Item(f"https://h/{n}.mp4", f"{n}.mp4", "video")
                        for n in range(8)], _CountingSession(), workers=2)
    assert len(probed) == 8 and peak[0] <= 2, f"{peak[0]} probes at once, asked for 2"

    # the discreet scan reads the page and touches nothing else; the full one
    # measures every candidate
    # every hiding place a page has: a tag, a script hiding JSON, a style
    # attribute, and an anchor that says outright that it is a download
    page_html = (
        '<html><body><a href=\"/a.mp4\">a</a><img src=\"/b.jpg\">'
        '<a href=\"/c.mp3\">c</a>'
        '<script>var p = {\"file\":\"https://cdn.test/lecture.mp4\",'
        '\"alt\":\"https:\\/\\/cdn.test\\/escaped.mp4\"};</script>'
        '<div style=\'background-image:url(/shot.png)\'></div>'
        '<a href=\"/get.php?id=7\" download=\"Notes.pdf\">notes</a>'
        '<a href=\"/about\">about</a></body></html>')
    page = page_html.encode()
    heads = []

    class _PageSession:
        def get(self, url, **kw):
            raw = type("Raw", (), {"read": lambda _s, n, decode_content=True: page})()
            return type("R", (), {"headers": {"content-type": "text/html"},
                                  "raw": raw, "status_code": 200,
                                  "raise_for_status": lambda _s: None})()

        def head(self, url, **kw):
            heads.append(url)
            return type("R", (), {"status_code": 200,
                                  "headers": {"content-length": "9",
                                              "content-type": "video/mp4"}})()

    keep_session_for = session_for
    globals()["session_for"] = lambda proxy=None: _PageSession()
    try:
        quiet = scrape_page("https://h/p", None, lambda *_a: None,
                            embeds=False, quiet=True)
        names = {i.name for i in quiet}
        assert len(quiet) == 7, f"discreet scan found {len(quiet)}: {names}"
        assert "lecture.mp4" in names, "a source hidden in a script was missed"
        assert "escaped.mp4" in names, "escaped slashes in JSON were missed"
        assert "shot.png" in names, "a css background was missed"
        assert "Notes.pdf" in names,             "download= names the file, and the page said so"
        # ...but that name is a label, not a path: joining it to the page would
        # invent http://host/Notes.pdf, which nothing ever linked to
        named = [i for i in quiet if i.name == "Notes.pdf"]
        assert len(named) == 1 and "get.php" in named[0].url, named[0].url
        assert not any("about" in n for n in names), "an ordinary page link"
        assert not heads, f"discreet scan probed {heads}"
        assert all(it.size == 0 for it in quiet), "sizes must wait to be asked for"
        full = scrape_page("https://h/p", None, lambda *_a: None, embeds=False)
        assert len(heads) == 7 and all(it.size == 9 for it in full)
    finally:
        globals()["session_for"] = keep_session_for


    assert kind_of("https://x.com/p/photo.WEBP") == "image"
    assert kind_of("https://x.com/page") is None
    # the ones that used to be invisible: an audiobook, a lecture recording
    # cut into transport streams, an old Word file, a subtitle-sized archive
    for _url, _kind in (("https://x/a.m4b", "audio"), ("https://x/a.aac", "audio"),
                        ("https://x/s.ts", "video"), ("https://x/v.flv", "video"),
                        ("https://x/d.doc", "doc"), ("https://x/d.odt", "doc"),
                        ("https://x/n.md", "doc"), ("https://x/i.svg", "image"),
                        ("https://x/p.heic", "image"), ("https://x/a.tgz", "archive"),
                        ("https://x/a.xz", "archive")):
        assert kind_of(_url) == _kind, f"{_url} read as {kind_of(_url)}"
    assert kind_of("https://x/notes.tar.gz") == "archive", "double extensions"
    assert name_from_url("https://x.com/a/b%20c.png?z=1") == "b c.png"
    assert safe_name('a:b/c?d*e"f<g>h|i') == "a_b_c_d_e_f_g_h_i"
    assert safe_name("  spaced  ") == "spaced"
    assert safe_name("trailing dots...") == "trailing dots", "NTFS drops those"
    assert safe_name("") == "file" and safe_name("   ") == "file"
    # reserved device names: opening one writes nowhere instead of failing loudly
    assert safe_name("NUL") == "_NUL" and safe_name("nul.jpg") == "_nul.jpg"
    assert safe_name("COM1.txt") == "_COM1.txt" and safe_name("LPT9") == "_LPT9"
    assert safe_name("console.log") == "console.log", "only the exact names"
    assert safe_name("NULL.txt") == "NULL.txt", "NULL is a file, NUL is a device"
    assert safe_name("///") == "___", "separators become a usable name"
    assert len(safe_name("x" * 500)) == 120
    assert human(0) == "-" and human(2048) == "2.0K"
    # the two unknowns in the SIZE column have to look different: not measured
    # yet is a dot you can click, measured and empty-handed is a dash
    unmeasured = Item("https://h/a.mp4", "a.mp4", "video")
    assert size_cell(unmeasured, False) == "·"
    assert size_cell(unmeasured, True) == "-", "asked and got nothing is a dash"
    assert size_cell(Item("https://h/b.mp4", "b", "video", 2048), False) == "2.0K"
    assert size_cell(Item("https://h/p", "p", "video", via="ytdlp"), False) == "-",         "a yt-dlp row is never measured with a HEAD, so it has nothing to wait for"
    assert clock(0) == "" and clock(161) == "2:41" and clock(3723) == "1:02:03"
    assert codec_name("av01.0.08M.08") == "av01" and codec_name("none") == ""
    assert codec_name(None) == "" and codec_name("vp9") == "vp9"
    assert counted(0) == "" and counted(56071) == "56.1K" and counted(4_200_000) == "4.2M"

    # a header-sized slice must still yield the true dimensions
    import io as _io
    from PIL import Image as _Image
    buf = _io.BytesIO()
    _Image.new("RGB", (640, 480), "red").save(buf, "JPEG", quality=95)
    whole = buf.getvalue()
    assert _Image.open(_io.BytesIO(whole)).size == (640, 480)
    clipped = whole[:len(whole) // 3]
    assert _Image.open(_io.BytesIO(clipped)).size == (640, 480),         "truncated reads must still report the real size"

    # a media host with no video must explain itself, not scrape avatars
    assert is_media_host("https://x.com/a/status/1")
    assert is_media_host("https://www.twitter.com/a")
    assert is_media_host("https://m.youtube.com/watch?v=x")
    assert not is_media_host("https://en.wikipedia.org/wiki/Cat")
    assert not is_media_host("https://notx.com/a"), "suffix match must not overreach"

    assert tweet_id("https://x.com/a/status/12345") == "12345"
    assert tweet_id("https://twitter.com/a/statuses/9?s=20") == "9"
    assert tweet_id("https://x.com/i/status/77") == "77"
    assert tweet_id("https://x.com/SpaceX") is None
    assert tweet_id("https://en.wikipedia.org/wiki/Cat") is None

    payload = {
        "text": "look at these\nsecond line",
        "duration_millis": 10000,
        "mediaDetails": [
            {"type": "photo", "media_url_https": "https://pbs.twimg.com/media/A.jpg"},
            {"type": "video", "media_url_https": "https://pbs.twimg.com/t.jpg",
             "video_info": {"variants": [
                 {"content_type": "application/x-mpegURL", "url": "x.m3u8"},
                 {"content_type": "video/mp4", "bitrate": 832000,
                  "url": "https://video.twimg.com/v/avc1/640x360/a.mp4"},
                 {"content_type": "video/mp4", "bitrate": 10368000,
                  "url": "https://video.twimg.com/v/avc1/1920x1080/b.mp4"}]}},
        ],
    }
    rows = tweet_items(payload, "1")
    # kind says what it is, quality says how good a copy - never both in one
    assert [r.kind for r in rows] == ["image", "video", "video"], [r.kind for r in rows]
    # the photo carries no dimensions in this payload, and "?name=orig" really
    # is the untouched upload, so that is what the quality cell says
    assert [r.quality for r in rows] == ["original", "1080p mp4", "360p mp4"],         [r.quality for r in rows]
    assert rows[0].url.endswith("?name=orig"), "photos must fetch the original"
    assert rows[0].thumb.endswith("?name=small"), "preview uses the small copy"
    assert rows[1].size == 12960000, rows[1].size   # 10368000/8 * 10s
    assert "second line" not in rows[0].name, "title is the first line only"
    nasty = tweet_items({"text": 'a/b:c?d', "mediaDetails": [
        {"type": "photo", "media_url_https": "https://p/x.jpg"}]}, "1")
    assert "/" not in nasty[0].name and "?" not in nasty[0].name, nasty[0].name
    assert tweet_items({}, "1") == []
    assert tweet_items({"__typename": "TweetTombstone"}, "1") == []
    assert tweet_items({"mediaDetails": [{"type": "photo"}]}, "1") == []

    # a body shorter than the length the server promised is a failed download,
    # not a finished one, and the bytes must stay resumable
    class _ShortSession:
        def get(self, url, **kw):
            return type("R", (), {
                "status_code": 200, "headers": {"content-length": "10"},
                "__enter__": lambda s: s, "__exit__": lambda *a: False,
                "raise_for_status": lambda s: None,
                "iter_content": lambda s, n: iter([b"1234"])})()

    # a link that serves a web page is not a download, and no retry changes that
    class _HtmlSession:
        def get(self, url, **kw):
            return type("R", (), {
                "status_code": 200,
                "headers": {"content-type": "text/html; charset=utf-8"},
                "__enter__": lambda s: s, "__exit__": lambda *a: False,
                "raise_for_status": lambda s: None,
                "iter_content": lambda s, n: iter([b"<html>"])})()

    keep_session_for = session_for
    globals()["session_for"] = lambda proxy=None: _HtmlSession()
    try:
        page_dir = tempfile.mkdtemp()
        page_link = Item("https://h/song.ogg", "song.ogg", "audio")
        try:
            download_file(page_link, page_dir, None, False, lambda *_a: None)
            raise AssertionError("a web page was saved as a file")
        except Permanent as exc:
            assert "web page" in str(exc), exc
        assert not os.listdir(page_dir), f"it wrote something anyway: {os.listdir(page_dir)}"
    finally:
        globals()["session_for"] = keep_session_for

    globals()["session_for"] = lambda proxy=None: _ShortSession()
    try:
        short_dir = tempfile.mkdtemp()
        cut = Item("https://h/x.bin", "x.bin", "file")
        try:
            download_file(cut, short_dir, None, False, lambda *_a: None)
            raise AssertionError("half a file passed as a finished one")
        except OSError as exc:
            assert "stopped short" in str(exc), exc
        assert not os.path.exists(os.path.join(short_dir, "x.bin")), "half a file was kept"
        assert os.path.getsize(part_path(short_dir, cut.name, cut.url)) == 4,             "the resumable bytes were thrown away"
    finally:
        globals()["session_for"] = keep_session_for

    # SOCKS support is imported by name the moment a socks5h:// proxy is
    # used, which nothing static can see: a build without PySocks answers
    # "Missing dependencies for SOCKS support" the first time the tor box is
    # ticked. A dead port is enough to tell the two apart - the wrong answer
    # arrives before any connection is attempted.
    try:
        session_for("socks5h://127.0.0.1:1").get("https://example.invalid",
                                                 timeout=2)
    except Exception as exc:
        assert "SOCKS" not in str(exc) or "Missing dependencies" not in str(exc),             f"this build cannot use tor at all :: {exc}"

    # over tor the app says it is a Tor Browser, because a Chrome arriving
    # from an exit node is a combination nobody else has
    global TOR_MODE
    assert "Chrome" in user_agent() and "Firefox" not in user_agent()
    assert session_for(None).headers["Accept-Language"] == "en-US,en;q=0.9"
    TOR_MODE = True
    try:
        assert user_agent() == TOR_UA and "Chrome" not in user_agent()
        assert f"rv:{TOR_FIREFOX}" in TOR_UA and f"Firefox/{TOR_FIREFOX}" in TOR_UA
        # the headers go out together or the disguise is a costume with a name
        # tag: Tor Browser sends q=0.5, so this has to as well
        sent = session_for(None).headers
        assert sent["User-Agent"] == TOR_UA
        assert sent["Accept-Language"] == "en-US,en;q=0.5"
    finally:
        TOR_MODE = False
    assert "Chrome" in user_agent(), "the switch did not switch back"

    # the name a server offers in a header beats the one in a php link
    assert offered_name({"content-disposition": 'attachment; filename="notes.pdf"'}) == "notes.pdf"
    assert offered_name({"content-disposition": "attachment; filename=notes.pdf"}) == "notes.pdf"
    assert offered_name({"content-disposition": "attachment; filename*=UTF-8''%CE%B1.pdf"}) == "α.pdf"
    assert offered_name({"content-disposition": "inline"}) == ""
    assert offered_name({}) == ""
    assert better_name("index.php", "notes.pdf") == "notes.pdf"
    assert better_name("view", "notes.pdf") == "notes.pdf", "no extension at all"
    assert better_name("clip.mp4", "tracking.mp4") == "clip.mp4",         "a real filename is not overruled by a header"
    assert better_name("index.php", "") == "index.php", "nothing offered"

    # a status code, said to somebody waiting for a file
    assert "login" in http_reason(403) and "403" in http_reason(403)
    assert "tor exit" in http_reason(403, over_tor=True),         "over tor a refusal is usually the exit node, not the account"
    assert http_reason(401), "a login wall is worth the same words"
    assert "not there" in http_reason(404) and "not there" in http_reason(410)
    assert http_reason(451), "the one status code with a novel behind it"
    assert http_reason(200) == "" and http_reason(500) == "",         "only the ones with something to do about them"

    # a stream is a playlist of segments, not a file: saving the manifest gets
    # a page of text listing the video. yt-dlp follows one, so they are its
    # rows rather than downloads.
    assert is_stream("https://h/live/master.m3u8") and is_stream("https://h/v.mpd")
    assert not is_stream("https://h/clip.mp4") and not is_stream("https://h/p")
    assert kind_of("https://h/master.m3u8") is None,         "a manifest must never look like a file to download directly"

    # a link with no extension can still be a file: eClass and Moodle serve
    # everything through a php page, and collecting by extension alone meant a
    # page of handouts came back empty rather than wrong
    assert looks_like_download("https://eclass.uoa.gr/modules/document/index.php?course=X&download=/1.pdf")
    assert looks_like_download("https://x.com/mod/resource/view.php?id=99")
    assert looks_like_download("https://drive.google.com/uc?export=download&id=9")
    assert not looks_like_download("https://x.com/clip.mp4"), "that has an extension"
    assert not looks_like_download("https://x.com/about"), "an ordinary page"
    assert not looks_like_download("https://x.com/downloads/"), "a directory"

    # subtitles: nothing at all unless asked for, and then the window's
    # language before English
    assert subtitle_opts("el", False) == {}
    subs = subtitle_opts("el", True)
    assert subs["subtitleslangs"] == ["el", "en"], subs
    assert subs["writesubtitles"] and subs["writeautomaticsub"],         "a lecture often has only the machine transcript"
    assert "srt" in subs["subtitlesformat"], "a subtitle you can open and read"

    # a file already in the download folder is worth saying so, since the
    # alternative is finding "clip (2).mp4" there afterwards
    folder = {"clip.mp4", "Lecture 3 [abc123].mp4"}
    assert already_here(folder, Item("https://h/clip.mp4", "clip.mp4", "video"))
    assert not already_here(folder, Item("https://h/other.mp4", "other.mp4", "video"))
    # a yt-dlp row is named by a template at download time, so the title is
    # matched as a prefix - the id and the extension are not known yet
    assert already_here(folder, Item("https://h/w", "Lecture 3", "video",
                                     via="ytdlp"))
    assert not already_here(folder, Item("https://h/w", "Lecture 4", "video",
                                         via="ytdlp"))
    assert not already_here(set(), Item("https://h/clip.mp4", "clip.mp4", "video"))

    # the proxy box: a bare host:port is a socks proxy, junk is nothing, and
    # socks5 becomes socks5h so the name is resolved at the far end
    assert normalise_proxy("127.0.0.1:9050") == "socks5h://127.0.0.1:9050"
    assert normalise_proxy("socks5://10.0.0.1:1080") == "socks5h://10.0.0.1:1080"
    assert normalise_proxy("socks5h://10.0.0.1:1080") == "socks5h://10.0.0.1:1080"
    assert normalise_proxy("http://proxy.corp:3128") == "http://proxy.corp:3128"
    assert normalise_proxy("  ") is None and normalise_proxy("") is None
    assert normalise_proxy("tor") is None, "a word is not an address"
    assert normalise_proxy("127.0.0.1") is None, "no port, no guessing one"
    assert normalise_proxy("http://") is None

    # ticking the tor box means nothing unless tor is actually there, and it
    # can be there on either of two ports depending on how it was installed
    import socket as _socket
    listener = _socket.socket()
    listener.bind(("127.0.0.1", 0))
    # nothing here accepts, so every probe stays in the queue: a backlog of one
    # would make the second probe look like a Tor that is not running
    listener.listen(16)
    live_port = listener.getsockname()[1]
    found = tor_proxy("127.0.0.1", (live_port,))
    assert found == f"socks5h://127.0.0.1:{live_port}", found
    assert found.startswith("socks5h://"),         "socks5 without the h resolves the hostname here, which tells the "         "provider which site is about to be visited"
    # the service port is dead and the browser's is up: the browser's answers
    assert tor_proxy("127.0.0.1", (1, live_port), timeout=0.5) == found,         "a Tor on the second port has to be found too"
    listener.close()
    assert tor_proxy("127.0.0.1", (live_port,), timeout=0.5) is None,         "a closed port must read as down, not hang"
    assert TOR_PORTS == (9050, 9150), "the tor service, then the Tor Browser"

    # nothing this app starts is allowed to outlive it
    sleeper = [None]

    def _run_sleeper():
        try:
            sleeper[0] = quiet_run([sys.executable, "-c",
                                    "import time; time.sleep(30)"], timeout=40)
        except Exception as exc:
            sleeper[0] = exc

    slow = threading.Thread(target=_run_sleeper, daemon=True)
    slow.start()
    for _ in range(50):                      # wait for it to actually be up
        if _CHILDREN:
            break
        time.sleep(0.05)
    assert _CHILDREN, "the child was never registered, so nothing can stop it"
    started = time.monotonic()
    assert stop_children() == 1, "the live child was not counted"
    slow.join(timeout=10)
    assert not slow.is_alive() and time.monotonic() - started < 10,         "closing the window left a process running"
    assert not [p for p in _CHILDREN if p.poll() is None]

    # the update says what it knows, and no more than that
    said = []
    keep_session = session_for
    real = installed_version("yt-dlp")

    class _Answer:
        def __init__(self, version):
            self.version = version

        def get(self, url, **kw):
            if self.version is None:
                import requests
                raise requests.ConnectionError("no route")
            return type("R", (), {
                "json": lambda _s, v=self.version: {"info": {"version": v}}})()

    # A frozen build carries its own yt-dlp and cannot pip into itself, so
    # update_ytdlp turns round at the door and this said nothing at all - which
    # failed the run inside the exe, where a selftest is worth the most.
    frozen = getattr(sys, "frozen", False)
    sys.frozen = False
    try:
        globals()["session_for"] = lambda proxy=None: _Answer(None)
        update_ytdlp(lambda m, *a, **k: said.append(str(m)))
        assert said and "not checked" in said[-1],             f"an unreachable index must not read as up to date: {said}"

        globals()["session_for"] = lambda proxy=None: _Answer(real)
        said.clear()
        update_ytdlp(lambda m, *a, **k: said.append(str(m)))
        assert said and said[-1] == f"yt-dlp up to date ({real})", said
    finally:
        globals()["session_for"] = keep_session
        if frozen:
            sys.frozen = frozen
        else:
            del sys.frozen

    from i18n import LANGUAGES as _langs, STRINGS as _strings, Tr as _Tr
    base = set(_strings["en"])
    for code in _langs:
        assert code in _strings, f"{code} listed but not translated"
        assert not base - set(_strings[code]), f"{code} missing {base - set(_strings[code])}"
    for _code in _langs:
        assert "{site}" in _strings[_code]["no_video"], f"{_code} lost the site slot"
        assert "cookies" in _strings[_code]["try_cookies"].lower() or _code != "en"
    # only the two languages that are actually offered, but every translation
    # still in STRINGS must stay complete - that is what makes putting one back
    # a one-line change
    assert set(_langs) == {"en", "el"}, _langs
    assert {"es", "de"} <= set(_strings), "shelved translations must survive"
    tr = _Tr("el")
    assert tr("found", n=3) != _strings["en"]["found"], "greek must differ"
    assert tr("unknown_key_xyz") == "unknown_key_xyz", "missing key must not crash"
    assert _Tr("klingon").lang == "en", "unknown language falls back"
    # A fresh install has no settings file, and the first window anyone sees
    # has to be readable by anyone: English until it is changed in settings.
    assert _Tr(load_settings().get("language", "en")).lang == "en" or                load_settings().get("language"),         "with no settings file the window must open in English"
    assert list(_langs)[0] == "en", "English leads the dropdown"
    # the window shows sentence case, whatever the dicts are written in
    assert _Tr("en")("scan") == "Scan" and _Tr("en")("col_size") == "SIZE"
    assert _Tr("el")("dlg_ffmpeg") == "ffmpeg", "a name keeps its own spelling"
    assert _Tr("el")("dlg_proxy_hint").startswith("socks5://"), "not a sentence"
    assert _Tr("en")("browse") == "...", "nothing to capitalise"
    # the status line above the results is UI, not a log line, so it follows
    # the window's language too
    for _key in ("chip_private", "chip_strip", "chip_no_ffmpeg"):
        assert _Tr("el")(_key) != _Tr("en")(_key), f"{_key} was left in English"

    info = {"formats": [
        {"format_id": "a", "vcodec": "none", "acodec": "mp4a", "abr": 128, "filesize": 1000},
        {"format_id": "v4k", "vcodec": "vp9", "acodec": "none", "height": 2160, "filesize": 90000},
        {"format_id": "v1080", "vcodec": "vp9", "acodec": "none", "height": 1080, "filesize": 40000},
        {"format_id": "v1080lo", "vcodec": "vp9", "acodec": "none", "height": 1080, "filesize": 9000},
        {"format_id": "p360", "vcodec": "h264", "acodec": "mp4a", "height": 360, "filesize": 5000},
        # X/Twitter shape: codecs unknown, but it is a complete progressive mp4
        {"format_id": "http-99", "vcodec": None, "acodec": None, "height": 270, "filesize": 3000},
        {"format_id": "img", "vcodec": "none", "acodec": "none"},
    ]}
    # "none" means the stream is absent; None means unknown, which for X/Twitter
    # http mp4s means a complete file that needs no merge
    assert has_audio({"acodec": "mp4a"}) and has_audio({"acodec": None})
    assert not has_audio({"acodec": "none"})

    rows = media_variants(info, "clip", "https://x.com/v")
    # four videos, then the source audio track, then the mp3 re-encode - all of
    # which are "video" or "audio", with the resolution in its own field
    assert [r.kind for r in rows] == ["video"] * 4 + ["audio"] * 2,         [r.kind for r in rows]
    assert [r.res for r in rows[:4]] == ["?x2160", "?x1080", "?x360", "?x270"],         [r.res for r in rows]
    assert [r.quality.split()[0] for r in rows[:4]] == ["2160p", "1080p", "360p", "270p"],         [r.quality for r in rows]
    assert all(r.length == "" for r in rows), "no duration in this fixture"

    # a vertical video is named by its short side; "1920p" for a 1080x1920
    # phone clip is a number nobody uses
    tall = media_variants({"duration": 15, "formats": [
        {"format_id": "a", "vcodec": "none", "acodec": "mp4a", "abr": 130,
         "ext": "m4a", "filesize": 1000},
        {"format_id": "v", "vcodec": "avc1", "acodec": "none",
         "height": 1920, "width": 1080, "ext": "mp4", "filesize": 5000},
        {"format_id": "w", "vcodec": "avc1", "acodec": "none",
         "height": 256, "width": 144, "ext": "mp4", "filesize": 500},
    ]}, "short", "u")
    assert [r.quality.split()[0] for r in tall[:2]] == ["1080p", "144p"],         [r.quality for r in tall]
    # dimensions are a column, not the front of the info line
    assert tall[0].res == "1080x1920", tall[0].res
    assert "1080x1920" not in tall[0].info, tall[0].info
    # duration has a column of its own now, so it is not also in the info line
    assert tall[0].length == "0:15", tall[0].length
    assert "0:15" not in tall[0].info, tall[0].info
    assert all(r.length == "0:15" for r in tall), [r.length for r in tall]
    assert rows[5].quality.startswith("mp3 "), rows[5].quality
    assert rows[0].name == "clip", "the title is the name, the rest is quality"
    assert all(r.kind in TAG_COLOURS for r in rows), "a row with no colour"
    assert rows[5].fmt == "mp3" and rows[5].size == 1000, "mp3 row rides the audio track"
    twitter = rows[3]
    assert twitter.fmt == "http-99" and twitter.size == 3000, "unknown codec = complete file"
    assert "*" not in twitter.quality, "must not demand ffmpeg it does not need"
    # video-only sizes include the audio track that gets merged in
    assert rows[0].size == 91000 and rows[1].size == 41000
    assert rows[1].fmt.startswith("v1080+"), "should keep the higher-bitrate 1080p"
    # progressive row carries no merge, so no ffmpeg needed and no star
    assert rows[2].fmt == "p360" and "+" not in rows[2].fmt
    assert "*" not in rows[2].quality, "a complete file is never flagged"
    assert "+" in rows[0].fmt, "2160p must merge a separate audio track"
    # the star tracks ffmpeg, so pin the rule itself rather than this machine
    assert merge_mark(False, False) == " *", "flag a merge row with no ffmpeg"
    assert merge_mark(False, True) == "", "no flag once ffmpeg is there"
    assert merge_mark(True, False) == "", "progressive never needs the flag"
    assert rows[4].size == 1000 and rows[4].fmt == "a"
    assert media_variants({"formats": []}, "x", "u") == []

    # every source audio track gets a row, best bitrate first, and the mp3
    # re-encode sits last - it is not a better copy of any of them, it is one
    # of them decoded and encoded again
    many = media_variants({"duration": 15, "formats": [
        {"format_id": "249", "vcodec": "none", "acodec": "opus", "abr": 50,
         "ext": "webm", "filesize": 95_000},
        {"format_id": "251", "vcodec": "none", "acodec": "opus", "abr": 130,
         "ext": "webm", "filesize": 244_000},
        {"format_id": "140", "vcodec": "none", "acodec": "mp4a", "abr": 128,
         "ext": "m4a", "filesize": 237_400},
        {"format_id": "dup", "vcodec": "none", "acodec": "opus", "abr": 130,
         "ext": "webm", "filesize": 244_000},
        {"format_id": "v", "vcodec": "avc1", "acodec": "none", "height": 720,
         "width": 1280, "ext": "mp4", "filesize": 900_000},
    ]}, "clip", "u")
    audio_rows = [r for r in many if r.kind == "audio"]
    sources = [r for r in audio_rows if not r.quality.startswith("mp3")]
    assert len(sources) == 3, [r.quality for r in sources]   # the duplicate folded in
    rates = [int(r.quality.split()[-1].rstrip("k")) for r in sources]
    assert rates == sorted(rates, reverse=True), rates
    assert audio_rows[-1].quality.startswith("mp3"), "the re-encode goes last"
    assert all(r.res == "" for r in audio_rows), "audio has no resolution"

    # Which iframes are worth following is yt-dlp's question to answer, so the
    # tracking pixels and the social buttons fall out for free. This only runs
    # as a fallback - yt-dlp's own generic extractor finds page embeds first,
    # and in testing it found every variant thrown at it.
    from bs4 import BeautifulSoup as _Soup
    page = _Soup("""
      <iframe src="https://www.googletagmanager.com/ns.html?id=GTM-X"></iframe>
      <iframe src="https://www.facebook.com/plugins/like.php?href=x"></iframe>
      <iframe src="https://www.youtube.com/embed/aaaaaaaaaaa"></iframe>
      <iframe data-src="//player.vimeo.com/video/76979871"></iframe>
      <iframe src="/local/page.html"></iframe>
      <iframe src="https://www.youtube.com/embed/aaaaaaaaaaa"></iframe>
      <iframe></iframe>
    """, "html.parser")
    embeds = embed_urls(page, "https://news.example.com/article")
    assert len(embeds) == 2, embeds
    assert any("youtube" in u for u in embeds) and any("vimeo" in u for u in embeds)
    assert not any("googletagmanager" in u or "plugins/like" in u for u in embeds), embeds
    assert all(u.startswith("https://") for u in embeds), "relative url got through"
    assert len(set(embeds)) == len(embeds), "the same embed twice"
    assert embed_urls(_Soup("<p>nothing here</p>", "html.parser"), "https://x/") == []
    # an id of the wrong shape is not a video, and yt-dlp knows that too
    short = _Soup('<iframe src="https://www.youtube.com/embed/abc"></iframe>', "html.parser")
    assert embed_urls(short, "https://x/") == [], "took a malformed id"

    # resume: 206 appends to what is on disk, anything else starts clean
    assert resume_plan(500, 206, 1500) == ("ab", 500, 2000)
    assert resume_plan(500, 200, 2000) == ("wb", 0, 2000)
    assert resume_plan(0, 200, 2000) == ("wb", 0, 2000)
    assert resume_plan(500, 206, 0) == ("ab", 500, 500)

    class _Resp:
        def __init__(self, after=None):
            self.headers = {"Retry-After": after} if after else {}

    # a longer request from the host is obeyed, a suspiciously short one is not
    assert retry_after(_Resp("30"), 1) == 30
    assert retry_after(_Resp("1"), 1) == RATE_LIMIT_BASE_WAIT, "too short to trust"
    assert retry_after(_Resp("9999"), 1) == RATE_LIMIT_MAX_WAIT
    assert retry_after(_Resp("soon"), 1) == RATE_LIMIT_BASE_WAIT, "junk header ignored"
    # with no header: 5s, 15s, 45s - not the 1s/2s/4s of an ordinary blip
    assert [retry_after(_Resp(), n) for n in (1, 2, 3)] == [5, 15, 45]
    assert retry_after(_Resp(), 9) == RATE_LIMIT_MAX_WAIT, "capped"
    assert RateLimited(30).wait == 30

    # one semaphore per host, shared by every url on it
    assert host_slot("https://a.com/1.jpg") is host_slot("https://a.com/2.jpg")
    assert host_slot("https://a.com/1.jpg") is not host_slot("https://b.com/1.jpg")

    # ffmpeg arrives as a wheel now; the downloader and its button are gone
    assert "fetch_ffmpeg" not in globals(), "the runtime downloader came back"
    assert ffmpeg_path(), "no ffmpeg anywhere - is imageio-ffmpeg installed?"

    # a .part nobody will finish is litter; one that can still resume is not
    tmpdir = tempfile.mkdtemp()
    dead = Item("https://h/x.bin", "x.bin", "file")
    open(part_path(tmpdir, dead.name, dead.url), "wb").write(b"half")
    drop_part(dead, tmpdir)
    assert not os.path.exists(part_path(tmpdir, dead.name, dead.url))
    drop_part(dead, tmpdir)  # already gone must not raise
    # same name, different url must not collide
    a, b = Item("https://h/1/f.bin", "f.bin", "file"), Item("https://h/2/f.bin", "f.bin", "file")
    assert part_path(tmpdir, a.name, a.url) != part_path(tmpdir, b.name, b.url)

    global SETTINGS_FILE
    keep = SETTINGS_FILE
    SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "settings.json")
    assert _writable(tempfile.gettempdir()), "temp must be writable"
    assert not _writable(os.path.join("Z:" if os.name == "nt" else "/proc/1",
                                      "no", "such", "place"))
    assert load_settings() == {}, "missing file must not raise"
    save_settings({"outdir": "D:/x", "quality": "1080p"})
    assert load_settings()["outdir"] == "D:/x"
    with open(SETTINGS_FILE, "w") as fh:
        fh.write("{ not json")
    assert load_settings() == {}, "corrupt file must not raise"

    # a hand-edited settings file, or anything typed into a Spinbox, reaches
    # these as text - none of it may reach tk as an int and blow up
    assert clamp_int("5", 3, 1, 10) == 5
    assert clamp_int("abc", 3, 1, 10) == 3 and clamp_int("", 3, 1, 10) == 3
    assert clamp_int(None, 3, 1, 10) == 3
    assert clamp_int("99", 3, 1, 10) == 10 and clamp_int("-4", 3, 1, 10) == 1
    assert clamp_int(7.9, 3, 1, 10) == 7, "floats truncate, they do not raise"
    SETTINGS_FILE = keep

    ui_selftest()
    print("selftest ok")


def ui_selftest():
    """The parts that only break once there is a real window.

    Builds the app against a temp settings file, drives the widgets the way a
    keyboard user would, and tears it down. Skipped where there is no display.
    """
    import tempfile

    global SETTINGS_FILE, ffmpeg_path
    keep_file, keep_ff = SETTINGS_FILE, ffmpeg_path
    SETTINGS_FILE = os.path.join(tempfile.mkdtemp(), "settings.json")
    ffmpeg_path = lambda: "/nonexistent/ffmpeg"   # never fetch during a test
    try:
        root = tk.Tk()
    except tk.TclError:
        print("ui selftest skipped - no display")
        SETTINGS_FILE, ffmpeg_path = keep_file, keep_ff
        return
    try:
        root.withdraw()
        app = App(root)

        # Buttons must be controls, not Labels wearing a click handler: only a
        # real one takes Tab focus and announces itself to a screen reader.
        def walk(w):
            for child in w.winfo_children():
                yield child
                yield from walk(child)

        gated = [app.scan_btn, app.dl_btn, app.refresh_btn]
        for b in gated + [app.stop_btn]:
            assert isinstance(b, ttk.Button), type(b)
            assert str(b.cget("takefocus")) in ("1", "True"), "not tab-reachable"
            assert b.cget("command"), "button with nothing wired to it"
        app.set_busy(True)
        assert all("disabled" in b.state() for b in gated), "busy must really disable"
        assert "disabled" not in app.stop_btn.state(), "stop must survive busy"
        app.set_busy(False)
        assert all("disabled" not in b.state() for b in gated)

        app.q.put(("items", [Item("https://h/a.jpg", "a.jpg", "image", 100),
                             Item("https://h/b.mp4", "b.mp4", "video", 200)], None))
        app.pump()
        rows = app.tree.get_children()
        assert len(rows) == 2, rows

        # ttk's stock TButton has an 11-character minimum width, which made
        # "scan" as wide as "download" and pushed the rows out of shape.
        root.deiconify()
        root.update_idletasks()
        widths = {b.cget("text"): b.winfo_width()
                  for b in (app.scan_btn, app.dl_btn) if b.winfo_ismapped()}
        assert len(set(widths.values())) == len(widths),             f"buttons all one width, style lost width=0: {widths}"
        for frame in root.winfo_children():
            for w in frame.winfo_children():
                if w.winfo_ismapped():
                    right = frame.winfo_x() + w.winfo_x() + w.winfo_width()
                    assert right <= root.winfo_width() + 1, f"{w} past the edge"
        root.withdraw()

        # marking used to need a mouse
        app.tree.focus(rows[0])
        app.on_row_key(None)
        assert rows[0] in app.marked, "space did not mark the row"
        app.on_row_key(None)
        assert rows[0] not in app.marked, "space did not unmark the row"

        # junk in a Spinbox must not be able to trap the user in the window
        app.attempts_var.set("abc")
        app.parallel_var.set("")
        assert app.attempts() == ATTEMPTS and app.workers() == PARALLEL
        app.parallel_var.set("999")
        assert app.workers() == MAX_PARALLEL
        app.attempts_var.set("3")
        app.parallel_var.set("4")

        # the cookie dropdown shows a word for "off"; everything downstream
        # still wants an empty string, and an old settings file holds ""
        assert app.cookies() == "", app.cookies()
        app.cookies_var.set("firefox")
        assert app.cookies() == "firefox"
        app.cookies_var.set(NO_COOKIES)
        assert app.cookies() == ""
        assert COOKIE_BROWSERS[0] == NO_COOKIES and NO_COOKIES

        # readonly is the only state these boxes are ever in, so clam's light
        # grey field would make every chosen value unreadable
        for state in (["readonly"], ["readonly", "focus"]):
            assert ttk.Style().lookup("T.TCombobox", "fieldbackground",
                                      state) == C["panel"], state

        # the settings dialog is where the unreadable dropdowns showed up, so
        # build it for real and check what a reader would actually see
        app.open_settings()
        dlg = [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]
        assert len(dlg) == 1, dlg
        boxes = [w for w in walk(dlg[0]) if isinstance(w, ttk.Combobox)]
        assert len(boxes) == 3, f"language, quality and cookies expected: {boxes}"
        for box in boxes:
            assert box.get(), f"dropdown shows nothing selected: {box['values']}"
            assert box.cget("style") == "T.TCombobox"

        # save and cancel are pinned outside the scrolling area, because at
        # 860px the dialog put them under the bottom of a 768p screen
        dlg[0].update_idletasks()
        buttons = [w for w in walk(dlg[0]) if isinstance(w, ttk.Button)]
        assert buttons, "no buttons in the settings dialog"
        assert dlg[0].winfo_height() <= int(dlg[0].winfo_screenheight() * 0.85),             f"dialog is {dlg[0].winfo_height()}px tall"
        for b in buttons:
            if b.cget("text") in (app.t("save"), app.t("cancel")):
                bottom = b.winfo_rooty() + b.winfo_height()
                assert bottom <= dlg[0].winfo_rooty() + dlg[0].winfo_height(),                     f"{b.cget('text')} sits below the dialog"
        # a file already in the folder is said so in the INFO column, since
        # the alternative is finding "clip (2).mp4" there afterwards
        have = {safe_name("clip.mp4")}
        marked = app.info_cell(Item("https://h/clip.mp4", "clip.mp4", "video"), have)
        assert app.t("have_already") in marked, marked
        assert app.info_cell(Item("https://h/new.mp4", "new.mp4", "video"),
                             have) == "", "a file not there must not be marked"

        # thirteen settings in one column read as a list to get through, so
        # they sit under the question they answer
        labels = {str(w.cget("text")) for w in walk(dlg[0])
                  if isinstance(w, tk.Label)}
        for _key in ("sec_download", "sec_privacy", "sec_window"):
            assert app.t(_key).upper() in labels, f"{_key} section missing"
        # and a checkbox says what it is once, not twice
        assert app.t("dlg_tor") not in labels,             "the checkbox label is doubled by a heading above it"

        # the dialog must not show a setting that is not in force: the cookie
        # box kept saying "firefox" while the private session sent none, and
        # the proxy box kept an address tor was overriding
        cookie_box = next(b for b in boxes
                          if list(b.cget("values")) == list(COOKIE_BROWSERS))
        proxy_entry = next(w for w in walk(dlg[0])
                           if isinstance(w, tk.Entry)
                           and str(w.cget("textvariable")) == str(app.proxy_var))
        assert str(cookie_box.cget("state")) == "readonly"
        app.private_var.set(True)
        assert str(cookie_box.cget("state")) == "disabled",             "private mode was sending no cookies while the box still offered them"
        app.private_var.set(False)
        assert str(cookie_box.cget("state")) == "readonly"

        keep_tor = tor_proxy
        globals()["tor_proxy"] = lambda *a, **k: "socks5h://127.0.0.1:9050"
        try:
            assert str(proxy_entry.cget("state")) == "normal"
            app.tor_var.set(True)
            assert str(proxy_entry.cget("state")) == "disabled",                 "tor overrides the proxy box, so the box must not look live"
            assert proxy_entry.cget("disabledbackground") == C["panel"],                 "a switched-off box must not go white in a dark window"
            app.tor_var.set(False)
            app.private_var.set(False)
            assert str(proxy_entry.cget("state")) == "normal"
        finally:
            globals()["tor_proxy"] = keep_tor

        # with no route at all the answer is known without asking anyone - and
        # asking would mean handing an address over to be told the address
        keep_proxy = app.proxy_var.get()
        app.proxy_var.set("")
        app.check_route()
        assert app.route_label.cget("text") == app.t("route_none"),             app.route_label.cget("text")
        app.proxy_var.set(keep_proxy)

        # cancel means cancel: every widget in there writes into the shared
        # variable, so what it has to undo is the values, not only the save
        was_quiet, was_proxy = app.quiet_var.get(), app.proxy_var.get()
        app.quiet_var.set(not was_quiet)
        app.proxy_var.set("socks5://nope")
        next(b for b in buttons if b.cget("text") == app.t("cancel")).invoke()
        assert app.quiet_var.get() == was_quiet, "cancel kept the tick"
        assert app.proxy_var.get() == was_proxy, "cancel kept the typed proxy"
        assert not [w for w in root.winfo_children()
                    if isinstance(w, tk.Toplevel)], "cancel left the dialog open"

        # tor: the box picks the route, and refuses to stay on when there is
        # nothing to route through
        assert not app.tor_var.get(), "tor must be opt-in"
        assert app.proxy() is None, "no proxy typed, no tor, nothing in the way"
        app.proxy_var.set("http://127.0.0.1:8080")
        assert app.proxy() == "http://127.0.0.1:8080"
        app.proxy_var.set("127.0.0.1:9050")
        assert app.proxy() == "socks5h://127.0.0.1:9050",             "a bare address must not be handed over as an http proxy"
        app.proxy_var.set("nonsense")
        assert app.proxy() is None, "junk in the box is not a route"
        app.proxy_var.set("http://127.0.0.1:8080")

        keep_ready = tor_proxy
        fake_tor = "socks5h://127.0.0.1:9150"
        globals()["tor_proxy"] = lambda *a, **k: fake_tor
        try:
            assert not app.private_var.get()
            app.tor_var.set(True)
            assert app.tor_var.get(), "tor was on and available, so it stays on"
            assert app.proxy() == fake_tor,                 "with no circuit asked for yet, the address is used as it is"
            # one circuit per action: the tag Tor isolates on has to change
            app.new_circuit()
            first = app.proxy()
            app.new_circuit()
            second = app.proxy()
            assert first != second, "every scan left by the same circuit"
            assert first.startswith("socks5h://") and "@127.0.0.1:9150" in first, first
            assert with_circuit("http://vpn.example:8080", "abc") ==                 "http://vpn.example:8080", "only tor knows what to do with these"
            assert with_circuit(fake_tor, "") == fake_tor, "no tag, no change"
            # an anonymous route with the session written to disk is half a job
            assert app.private_var.get(), "tor did not bring the private session"
            assert TOR_MODE and user_agent() == TOR_UA,                 "the switch did not reach the headers the threads send"
            # brought on, not held on
            app.private_var.set(False)
            assert not app.private_var.get(), "private mode could not be turned off"
            assert app.tor_var.get(), "turning private off must not turn tor off"
            app.cookies_var.set("firefox")
            app.refresh_hint()
            assert "cookies name you" in app.settings_hint.cget("text"),                 "a login over tor is worth a word"
            app.cookies_var.set(NO_COOKIES)
            app.tor_var.set(False)
            assert not TOR_MODE and user_agent() == UA,                 "tor off and the app still claims to be a Tor Browser"
        finally:
            globals()["tor_proxy"] = keep_ready

        globals()["tor_proxy"] = lambda *a, **k: None
        try:
            app.tor_var.set(True)
            assert not app.tor_var.get(),                 "tor is not running, so the box must not pretend it is on"
            assert not app.private_var.get(),                 "tor never came on, so nothing should have come on with it"
            assert app.proxy() == "http://127.0.0.1:8080",                 "with tor off the typed proxy is the route again"
        finally:
            globals()["tor_proxy"] = keep_ready
        app.proxy_var.set("")
        assert str(app.tor_box.cget("variable")) == str(app.tor_var),             "the main bar has its own tor flag, so the dialog cannot see it"

        # private mode is a per-run decision, so it is offered in the main bar
        # as well as the dialog - and both have to drive the one variable
        assert app.private_box.pack_info()["side"] == "right",             "the private box left the end of the row under the scan buttons"
        assert str(app.private_box.cget("variable")) == str(app.private_var),             "the main bar has its own private flag, so the dialog cannot see it"

        # a pressed button changes colour as a whole - the dashed rectangle
        # clam drew inside it read as a broken border, not as a state
        for accent in ("green", "amber"):
            for name in (f"{accent}.T.TButton", f"big{accent}.T.TButton"):
                layout = str(ttk.Style().layout(name))
                assert "focus" not in layout,                     f"{name} still has the element that draws the dashed ring"
                assert "Button.label" in layout, f"{name} lost its text: {layout}"
                assert ttk.Style().lookup(name, "background", ["pressed"]) == C[accent]
                assert ttk.Style().lookup(name, "foreground", ["pressed"]) == C["bg"]
                assert ttk.Style().lookup(name, "background", ["focus"]) == C["line"],                     "a keyboard user needs to see which button has focus"
                # the word has to stay legible while the button is off
                assert ttk.Style().lookup(name, "foreground", ["disabled"]) == C["dim"]

        # download is the primary action and reads as one: bigger than the
        # buttons around it, and present both above the list and below it
        for dl in (app.dl_btn_top, app.dl_btn):
            assert dl.winfo_reqwidth() > app.scan_btn.winfo_reqwidth(), "download shrank"
            assert dl.winfo_reqheight() > app.scan_btn.winfo_reqheight()
            assert dl.cget("style").startswith("big"), dl.cget("style")

        # the path box is a folder, not a URL - it used to expand like one and
        # swallow the whole row. expand is the property that decides that, and
        # reqwidth is not: the URL box gets its size from expand, not from a
        # width it asked for.
        assert not int(app.outdir.pack_info()["expand"]),             "the download path is taking the whole row again"
        assert int(app.url.pack_info()["expand"]), "the URL box should still grow"

        # heading and cell are centred together, so a column reads as one block
        for col in app.tree.cget("columns"):
            assert str(app.tree.column(col)["anchor"]) == "center", col
            assert str(app.tree.heading(col)["anchor"]) == "center", col

        # Private mode: nothing about the session reaches the disk, and no
        # site is told which account is asking.
        # SETTINGS_FILE already points at a temp copy for this whole function
        probe = SETTINGS_FILE
        if os.path.exists(probe):
            os.remove(probe)
        app.cookies_var.set("firefox")
        assert app.cookies() == "firefox", "cookies should work normally"
        app.remember()
        assert os.path.exists(probe), "settings should normally be written"
        os.remove(probe)

        app.private_var.set(True)
        assert PRIVATE, "the module flag the crash handler reads did not follow"
        assert app.cookies() == "", "private mode still handed over cookies"
        app.remember()
        assert not os.path.exists(probe), "private mode wrote a settings file"
        hint_now = app.settings_hint.cget("text")
        # the line is written in the window's language like everything else,
        # so it is compared against the translation rather than an English word
        assert app.t("chip_private_bare") in hint_now, hint_now
        # it says so when there is no proxy, because that is the half private
        # mode cannot do anything about
        app.proxy_var.set("socks5://127.0.0.1:9050")
        app.refresh_hint()
        hint_now = app.settings_hint.cget("text")
        assert app.t("chip_private") in hint_now, hint_now
        assert app.t("chip_private_bare") not in hint_now, hint_now

        app.private_var.set(False)
        app.proxy_var.set("")
        app.cookies_var.set(NO_COOKIES)
        assert not PRIVATE

        # Clicking a row shows it; only the checkbox queues it. The two used
        # to be the same action, so you could not look without queueing.
        # Real coordinates rather than a stubbed identify(): the whole point is
        # which x lands in which column, and only Tk knows that.
        root.deiconify()
        root.update_idletasks()
        root.update()

        class _Click:
            def __init__(self, x, y):
                self.x, self.y = x, y

        first = app.tree.get_children()[0]
        app.tree.see(first)
        root.update_idletasks()
        root.update()
        box = app.tree.bbox(first)
        assert box, "no visible row to click"
        mid_y = box[1] + box[3] // 2
        box_x = 15                                   # inside the #0 column
        cell_x = app.tree.column("#0")["width"] + 40  # well past it
        assert app.tree.identify("region", box_x, mid_y) == "tree", "not the checkbox"
        assert app.tree.identify("region", cell_x, mid_y) == "cell", "not a cell"

        before = set(app.marked)
        app.on_row_click(_Click(cell_x, mid_y))
        assert set(app.marked) == before, "clicking the row marked it"
        app.on_row_click(_Click(box_x, mid_y))
        assert set(app.marked) != before, "clicking the box did not mark it"
        app.on_row_click(_Click(box_x, mid_y))
        assert set(app.marked) == before, "clicking the box again did not clear it"
        root.withdraw()

        # double click only downloads when asked; the first click of the pair
        # has already marked the row, so the default is off
        assert not app.dblclick_var.get(), "double click must be opt-in"
        started = []
        real_download, app.do_download = app.do_download, lambda: started.append(1)
        app.on_double_click(None)
        assert not started, "double click downloaded with the setting off"
        app.dblclick_var.set(True)
        app.on_double_click(None)
        assert len(started) == 1, "double click did nothing with the setting on"
        app.dblclick_var.set(False)
        app.do_download = real_download

        # the discreet scan is opt-in, and the on-demand measuring it relies on
        # asks once per row: not twice, not for a row that already has a size,
        # and never for a yt-dlp row whose url is a page rather than a file
        assert app.quiet_var.get(),             "the discreet scan is the default: 1 request a page, not 31"
        app._size_worker = lambda *a: None
        app.items = [Item("https://h/a.mp4", "a.mp4", "video"),
                     Item("https://h/b.mp4", "b.mp4", "video", 12),
                     Item("https://h/page", "page", "video", via="ytdlp")]
        for i, it in enumerate(app.items):
            app.measure(i, it)
            app.measure(i, it)
        assert app.sized == {0}, f"measured the wrong rows: {app.sized}"
        app.items = []
        app.sized.clear()

        # the header is the app name and nothing else now
        head_text = " ".join(
            w.cget("text") for w in walk(root)
            if isinstance(w, tk.Label) and w.winfo_manager() == "pack"
            and VERSION in str(w.cget("text")))
        assert not head_text, f"version still on show: {head_text!r}"
        assert any(w.cget("text") == app.t("source") for w in walk(root)
                   if isinstance(w, tk.Label)), "no word beside the link box"

        # the columns have to reach the right-hand edge whether NAME is showing
        # or folded away - only NAME used to stretch, so hiding it left the
        # table stopping short with dead space beside it
        # one video means one title on every row, so it is said once above the
        # list and the NAME column folds away
        same = [Item("u", "one title", "video", 1, quality="1080p mp4",
                     length="0:15") for _ in range(4)]
        app.q.put(("items", same, None))
        app.pump()
        root.update()
        # winfo_manager rather than winfo_ismapped: the window is withdrawn
        # here, so nothing in it counts as mapped whether it is packed or not
        assert app.source_line.winfo_manager() == "pack", "no source line for a shared title"
        assert app.source_line.cget("text") == "one title"
        assert "name" not in app.tree.cget("displaycolumns")
        app.q.put(("items", [Item("u", "a.jpg", "image", 1),
                             Item("u", "b.pdf", "doc", 2)], None))
        app.pump()
        root.update()
        assert app.source_line.winfo_manager() == "", "source line outstayed its rows"
        assert "name" in app.tree.cget("displaycolumns"), "NAME must return"

        # Shown first, then measured: a withdrawn window has no width for ttk
        # to spread the stretching columns across, so laying the rows out while
        # hidden and only then revealing gives a stale, too-narrow table.
        # Wide enough that seven columns genuinely fit, because the thing being
        # checked is that the stretching ones take up the slack - at a width
        # where they do not fit there is no slack to take and the table scrolls
        # instead, which is a different question.
        # The preview keeps its width whatever the list is doing. Pack squeezes
        # whatever was packed last, and the list used to win that fight: with a
        # NAME column in play its columns wanted more than the window had, and
        # the preview was left as a 144px strip.
        #
        # There is no assertion here about the columns reaching the right-hand
        # edge. That is ttk redistributing stretch on a resize, it behaves in a
        # live window, and pinning it through this window's withdraw/deiconify
        # churn produced three false alarms and no real finding.
        root.deiconify()
        root.geometry("1700x800")
        root.update()
        assert app.right.winfo_width() >= PREVIEW_W,             f"preview squeezed to {app.right.winfo_width()}px"
        root.geometry("1140x700")
        root.update_idletasks()
        root.withdraw()

        # categories are words in the user's language; format names are not
        for code in LANGUAGES:
            app.t.set(code)
            for kind in TAG_COLOURS:
                shown = app.t("kind_" + kind)
                assert shown and shown != "kind_" + kind, f"{code}/{kind} untranslated"
            assert app.quality_text("1080p mp4") == "1080p mp4", "format names stay"
            assert app.quality_text("as set") != "as set" or code == "en"
        app.t.set("en")

        app.q.put(("items", [Item("https://h/a.jpg", "a.jpg", "image", 100),
                             Item("https://h/b.mp4", "b.mp4", "video", 200)], None))
        app.pump()
        rows = app.tree.get_children()

        # the mark column is three drawn images now, not the text "[x]"
        assert set(app.boxes) == {"off", "on", "cut"}, app.boxes
        assert "mark" not in app.tree.cget("columns"), "text mark column returned"
        assert all(b.width() == CHECKBOX for b in app.boxes.values())
        off = app.tree.item(rows[0], "image")
        assert off, "row inserted without a checkbox"
        app.toggle_mark(rows[0])
        assert app.tree.item(rows[0], "image") != off, "ticking changed nothing"
        app.toggle_mark(rows[0])
        assert app.tree.item(rows[0], "image") == off, "unticking changed nothing"

        # the preview takes a share of the window rather than a fixed 240px,
        # clamped so it neither vanishes nor eats the list
        from PIL import Image as _Im
        wide = _Im.new("RGB", (1200, 800))
        seen = []
        root.deiconify()          # a withdrawn window reports no real geometry
        for w, h in ((940, 540), (1920, 1080), (2560, 1440), (940, 540)):
            root.geometry(f"{w}x{h}")
            root.update_idletasks()
            root.update()
            app.show_thumb(wide)
            seen.append(app.preview_w)
            assert PREVIEW_W <= app.preview_w <= PREVIEW_MAX, app.preview_w
            assert app.thumb_ref.width() <= app.preview_w
        assert seen[1] > seen[0], f"maximising did not widen the preview: {seen}"
        assert seen[3] == seen[0], f"shrinking did not walk it back: {seen}"
        root.geometry("1140x700")
        root.update_idletasks()
        root.withdraw()

        # a status line is clipped against the font, not counted in characters:
        # the Greek wording of a message runs longer than the English, and 54
        # characters used to cut the Greek version of lines the English fit
        for code in LANGUAGES:
            app.t.set(code)
            for key in ("ready", "nothing_marked", "try_cookies"):
                line = app.t(key)
                assert app.fit_status(line) == line, f"{code}/{key} clipped: {line}"
        app.t.set("en")
        long_line = "x" * 400
        assert app.f.measure(app.fit_status(long_line)) <= app.status_px
        assert app.fit_status(long_line).endswith("...")

        # a scan can be walked away from: the request cannot be killed, but the
        # window comes back and the late answer is thrown away
        assert not app.scanning
        app.scanning, app.busy = True, True
        stale = app.scan_token
        app.stop_all()
        assert not app.scanning and app.scan_token != stale, "stop did not abandon"
        while not app.q.empty():
            app.pump()
        assert not app.busy, "stop did not hand the window back"

        # every language change used to leave another pump loop running
        pending = len(root.tk.call("after", "info"))
        for code in LANGUAGES:
            app.t.set(code)
            app.rebuild()
            assert len(root.tk.call("after", "info")) == pending, "rebuild leaked a timer"
        assert len(app.tree.get_children()) == 2, "results lost on language change"

        # closing the window ends the session, background and all: a pip or an
        # ffmpeg still running would carry on with nothing on screen to stop it
        parked = subprocess.Popen([sys.executable, "-c",
                                   "import time; time.sleep(30)"])
        with _CHILDREN_LOCK:
            _CHILDREN.add(parked)

        app.close()   # remember() must not raise on the way out
        assert parked.wait(timeout=10) is not None, "close() left a child running"
        try:
            root.winfo_exists()
            raise AssertionError("close() left the window standing")
        except tk.TclError:
            pass          # destroyed, which is the point
    finally:
        SETTINGS_FILE, ffmpeg_path = keep_file, keep_ff
        try:
            root.destroy()
        except tk.TclError:
            pass


def main():
    if "--selftest" in sys.argv:
        return selftest()
    try:
        root = tk.Tk()
        App(root)
        root.mainloop()
    except Exception:
        # Launched with pythonw there is no console, so a crash before the
        # window appears would otherwise be nothing at all: no error, no
        # window, no clue. Leave a file and say so on screen.
        report = traceback.format_exc()
        try:
            if PRIVATE:
                raise OSError("private mode: no crash file")
            with open(os.path.join(DATA_DIR, "crash.log"), "a",
                      encoding="utf-8") as fh:
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                print("", stamp, report, sep="\n", file=fh)
        except OSError:
            pass
        try:
            messagebox.showerror(APP, report[-1500:])
        except Exception:
            pass
        raise
    finally:
        # Even on the way out of a crash: whatever was running stops here.
        stop_children()


if __name__ == "__main__":
    main()
