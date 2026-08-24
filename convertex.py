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
import sys
import threading
import time
import traceback
import tkinter as tk
import webbrowser
from tkinter import filedialog, font as tkfont, messagebox, ttk
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup
from PIL import ImageFile

# Pillow is only ever handed partial data here - previews are capped and the
# dimension probe reads a header-sized slice on purpose - so refusing truncated
# input would reject exactly the cases this app creates deliberately.
ImageFile.LOAD_TRUNCATED_IMAGES = True

from i18n import COOKIE_BROWSERS, LANGUAGES, Tr

APP = "convertex"
VERSION = "0.1.0"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

FILE_EXT = {
    "image": ".jpg .jpeg .png .gif .webp .bmp .avif .tiff",
    "video": ".mp4 .webm .mkv .mov .avi .m4v",
    "audio": ".mp3 .m4a .opus .ogg .wav .flac",
    "doc": ".pdf .epub .docx .xlsx .pptx .txt .csv",
    "archive": ".zip .rar .7z .tar .gz .iso",
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

# Status text is clipped to this many characters so the progress bar and the
# download button beside it never jump around. The log keeps the full line.
STATUS_CHARS = 54

PREVIEW_W = 240            # preview pane width in pixels
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


TAG_COLOURS = {"image": C["cyan"], "media": C["green"],
               "video": C["green"], "audio": C["amber"]}

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
BIN_DIR = os.path.join(DATA_DIR, "bin")

# Official static Windows build, fetched once when ffmpeg is nowhere to be
# found: on first launch in the background, or on demand from the "get ffmpeg"
# button. Both paths say so in the log; only the button asks first, because by
# the time you are clicking it you already know what you want.
FFMPEG_ZIP = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


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
    """Baked into the exe first, then beside the app, then downloaded, then PATH."""
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    roots = []
    bundled = getattr(sys, "_MEIPASS", None)  # PyInstaller unpack dir
    if bundled:
        roots.append(os.path.join(bundled, "bin"))
    roots += [os.path.join(APP_DIR, "bin"), BIN_DIR]
    for root in roots:
        candidate = os.path.join(root, name)
        if os.path.exists(candidate):
            return candidate
    return shutil.which("ffmpeg")


def fetch_ffmpeg(progress) -> str:
    """Download the static ffmpeg build into ./bin. Returns the ffmpeg path."""
    import io
    import zipfile

    os.makedirs(BIN_DIR, exist_ok=True)
    buf = io.BytesIO()
    with requests.get(FFMPEG_ZIP, stream=True, timeout=60,
                      headers={"User-Agent": UA}) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        for chunk in r.iter_content(262144):
            buf.write(chunk)
            progress(buf.tell(), total)

    wanted = ("ffmpeg.exe", "ffprobe.exe") if os.name == "nt" else ("ffmpeg", "ffprobe")
    with zipfile.ZipFile(buf) as z:
        for member in z.namelist():
            base = os.path.basename(member)
            if base in wanted:
                with z.open(member) as src, open(os.path.join(BIN_DIR, base), "wb") as dst:
                    shutil.copyfileobj(src, dst)
    path = ffmpeg_path()
    if not path:
        raise RuntimeError("archive did not contain ffmpeg")
    os.chmod(path, 0o755)
    return path


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
            done = subprocess.run(
                cmd, capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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
    __slots__ = ("url", "name", "kind", "size", "via", "fmt", "thumb",
                 "info", "details")

    def __init__(self, url, name, kind, size=0, via="file", fmt=None, thumb=None,
                 info="", details=""):
        self.url, self.name, self.kind = url, name, kind
        self.size, self.via = size, via
        self.fmt = fmt  # explicit yt-dlp format selector; None = use the dropdown
        self.thumb = thumb      # url to show in the preview pane
        self.info = info        # one-line technical summary for the list
        self.details = details  # multi-line block for the preview pane


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


def human(n: int) -> str:
    if not n:
        return "-"
    size = float(n)
    for unit in ("B", "K", "M", "G"):
        if size < 1024 or unit == "G":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return "?"


def session_for(proxy: str | None) -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
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


def head(s: requests.Session, url: str) -> tuple[int, str]:
    """(content-length, content-type). (0, "") when the URL is not reachable."""
    try:
        r = s.head(url, timeout=12, allow_redirects=True)
        if r.status_code >= 400:  # plenty of CDNs refuse HEAD
            r = s.get(url, timeout=12, stream=True)
            r.close()
        if r.status_code >= 400:
            return 0, ""
        return int(r.headers.get("content-length") or 0), r.headers.get("content-type", "")
    except (requests.RequestException, ValueError):
        return 0, ""


def probe_all(items: list[Item], s: requests.Session) -> list[Item]:
    """HEAD every item. For images also try higher-res variants and keep the
    biggest one that actually exists. Drops anything that answers with HTML -
    a link ending in .ogg can still be a wiki page about an .ogg."""
    from concurrent.futures import ThreadPoolExecutor

    def probe(it: Item):
        it.size, ctype = head(s, it.url)
        if "html" in ctype:
            return None
        if it.kind == "image":
            for cand in upgrade_image(it.url):
                size, ctype = head(s, cand)
                if size > it.size and "html" not in ctype:
                    it.url, it.size = cand, size
        return it

    # Most scrapes are one host, so the worker count is the per-host cap in
    # practice. Twelve HEADs at once is what trips the rate limiter HOST_LIMIT
    # exists to stay under; six probes fast enough.
    with ThreadPoolExecutor(max_workers=6) as pool:
        probed = [it for it in pool.map(probe, items) if it]
    # two thumbnails can resolve to the same original, so dedupe after upgrading
    return list({it.url: it for it in probed}.values())


def scrape_page(url: str, proxy: str | None, log) -> list[Item]:
    s = session_for(proxy)
    # streamed so the body can be read in a bounded slice below
    r = s.get(url, timeout=25, stream=True)
    r.raise_for_status()
    if "html" not in r.headers.get("content-type", ""):
        size = int(r.headers.get("content-length") or 0)
        return [Item(url, name_from_url(url), kind_of(url) or "file", size)]

    # Bounded read: BeautifulSoup sniffs the encoding out of the bytes itself,
    # and r.text would happily pull a runaway response into memory first.
    soup = BeautifulSoup(r.raw.read(MAX_HTML_BYTES, decode_content=True),
                         "html.parser")
    found: dict[str, str] = {}

    def add(raw):
        if not raw or raw.startswith(("data:", "javascript:", "#")):
            return
        full = urljoin(url, raw.strip()).split("#")[0]
        kind = kind_of(full)
        if kind:
            found.setdefault(full, kind)

    for tag in soup.find_all(["a", "img", "source", "video", "audio", "embed"]):
        for attr in ("href", "src", "data-src", "data-original", "data-full", "poster"):
            add(tag.get(attr))
        if tag.get("srcset"):
            add(best_from_srcset(tag["srcset"], url))
    for meta in soup.find_all("meta"):
        if meta.get("property") in ("og:image", "og:video") or meta.get("name") == "twitter:image":
            add(meta.get("content"))

    log(f"{len(found)} candidates, probing sizes and full-res variants...")
    items = probe_all([Item(u, name_from_url(u), k, thumb=u if k == "image" else None)
                       for u, k in found.items()], s)
    items.sort(key=lambda i: (i.kind, -i.size))
    return items


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
    best_audio = max(audio_only, key=lambda f: (f.get("abr") or 0, _fsize(f)), default=None)
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
        progressive = has_audio(f)
        # Anything above ~360p on YouTube ships video and audio separately, so
        # the row is flagged and download_media refuses it without ffmpeg
        # rather than silently handing back a silent video.
        fmt = f["format_id"] if progressive else f"{f['format_id']}+ba/b[height<={height}]"
        mark = merge_mark(progressive, have_ffmpeg)
        bits = [duration, f"{f.get('width') or '?'}x{height}"]
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
        items.append(Item(url, f"{title}  [{height}p {f.get('ext') or ''}{mark}]",
                          f"{height}p", total, via="ytdlp", fmt=fmt, thumb=thumb,
                          info="  ".join(b for b in bits if b),
                          details=head + "\n\n" + "\n".join(detail)))

    if best_audio:
        acodec = codec_name(best_audio.get("acodec"))
        abits = [duration, acodec]
        if best_audio.get("abr"):
            abits.append(f"{round(best_audio['abr'])}k")
        if best_audio.get("asr"):
            abits.append(f"{round(best_audio['asr'] / 1000)}kHz")
        if best_audio.get("audio_channels") == 2:
            abits.append("stereo")
        adetail = [f"audio  {acodec}  source track, not re-encoded",
                   f"container  {best_audio.get('ext') or '?'}"]
        items.append(Item(url, f"{title}  [audio {best_audio.get('ext', '')}]", "audio",
                          audio_bytes, via="ytdlp", fmt=best_audio["format_id"],
                          thumb=thumb, info="  ".join(b for b in abits if b),
                          details=head + "\n\n" + "\n".join(adetail)))
        # Re-encoded to mp3 at 320k. Size is the source track's - the mp3 lands
        # near it, and guessing precisely would mean decoding first.
        star = merge_mark(False, have_ffmpeg)
        items.append(Item(url, f"{title}  [mp3 {MP3_BITRATE}k{star}]", "mp3",
                          audio_bytes, via="ytdlp", fmt="mp3", thumb=thumb,
                          info=f"{duration}  mp3  {MP3_BITRATE}k".strip(),
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
                                  "image", thumb=f"{base}?name=small", info=dims,
                                  details=f"photo  original upload\n{dims}"))
            continue
        variants = [v for v in (m.get("video_info") or {}).get("variants") or []
                    if v.get("content_type") == "video/mp4" and v.get("url")]
        for v in sorted(variants, key=lambda x: x.get("bitrate") or 0, reverse=True):
            wh = re.search(r"/(\d+)x(\d+)/", v["url"])
            label = f"{wh.group(2)}p" if wh else "video"
            dims = f"{wh.group(1)}x{wh.group(2)}" if wh else ""
            secs = (data.get("duration_millis") or 0) / 1000
            items.append(Item(v["url"], f"{title} [{n}] [{label}]", label,
                              size=int((v.get("bitrate") or 0) / 8 * secs),
                              thumb=base,
                              info="  ".join(b for b in (clock(secs), dims,
                                                         "mp4") if b),
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
        "http_headers": {"User-Agent": UA}, "logger": _Hush(), "no_color": True,
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
        # A generic-extractor miss just means "not a media site"; a named
        # extractor failing is a real error the user should see.
        known = not reason.lower().startswith("[generic]")
        return [], reason if known else ""
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
        return [Item(url, title, "media", _fsize(info), via="ytdlp",
                     thumb=info.get("thumbnail"),
                     info=clock(info.get("duration")))], ""

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
        items.append(Item(link, title, "media", size, via="ytdlp",
                          thumb=e.get("thumbnail"),
                          info=clock(e.get("duration"))))
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
         no_video_msg: str = "", cookies_msg: str = "") -> list[Item]:
    log("asking yt-dlp...")
    items, err = scan_media(url, proxy, log, cookies)
    if items:
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
    return scrape_page(url, proxy, log)


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


def unique_path(path: str) -> str:
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{stem} ({n}){ext}"):
        n += 1
    return f"{stem} ({n}){ext}"


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
    have = os.path.getsize(part) if os.path.exists(part) else 0
    headers = {"Range": f"bytes={have}-"} if have else {}

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
            r.raise_for_status()
            length = int(r.headers.get("content-length") or 0)
            mode, done, total = resume_plan(have, r.status_code, length)
            total = total or it.size
            with open(part, mode) as fh:
                for chunk in r.iter_content(262144):
                    fh.write(chunk)
                    done += len(chunk)
                    progress(done, total)  # raises Cancelled if pulled from the pool

    with NAME_LOCK:
        dest = unique_path(os.path.join(outdir, it.name))
        os.replace(part, dest)
    if clean:
        strip_metadata(dest)
    return dest


def download_media(it: Item, outdir: str, proxy: str | None, quality: str,
                   clean: bool, progress, cookies: str = "") -> str:
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
        "writeinfojson": False, "writethumbnail": False, "writesubtitles": False,
        "http_headers": {"User-Agent": UA},
        "progress_hooks": [hook],
    }
    if proxy:
        opts["proxy"] = proxy
    if cookies:
        opts["cookiesfrombrowser"] = (cookies,)
    if ff:
        opts["ffmpeg_location"] = ff
        if want_mp3:
            opts["postprocessors"] = [{"key": "FFmpegExtractAudio",
                                       "preferredcodec": "mp3",
                                       "preferredquality": MP3_BITRATE}]
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
        self.cookies_var = tk.StringVar(value=self.prefs.get("cookies", ""))
        self.quality_var = tk.StringVar(value=self.prefs.get("quality", "best"))
        # StringVar, not IntVar: an IntVar raises TclError the moment it holds
        # anything non-numeric, and both a hand-edited settings file and the
        # Spinbox itself can put junk in there. Coerced on read instead.
        self.attempts_var = tk.StringVar(
            value=str(clamp_int(self.prefs.get("attempts"), ATTEMPTS, 1, 10)))
        self.parallel_var = tk.StringVar(
            value=str(clamp_int(self.prefs.get("parallel"), PARALLEL, 1, MAX_PARALLEL)))
        self.lang_var = tk.StringVar(value=self.t.lang)

        self.mono = self.pick_font()
        self.f = tkfont.Font(family=self.mono, size=10)
        self.fb = tkfont.Font(family=self.mono, size=10, weight="bold")
        self.fh = tkfont.Font(family=self.mono, size=15, weight="bold")

        self.style()
        self.build()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.tick = root.after(80, self.pump)
        if not ffmpeg_path():
            # Fetch it once, quietly, in the background. Every resolution above
            # 360p and the whole mp3 path depend on it, so waiting for the user
            # to discover a button just means broken-looking downloads.
            threading.Thread(target=self._ffmpeg_worker, args=(True,),
                             daemon=True).start()

    def close(self):
        self.remember()
        self.root.after_cancel(self.tick)  # otherwise pump fires post-destroy
        self.root.destroy()

    def remember(self):
        save_settings({
            "language": self.t.lang,
            "outdir": self.outdir_var.get().strip(),
            "proxy": self.proxy_var.get().strip(),
            "quality": self.quality_var.get(),
            "strip_metadata": bool(self.clean_var.get()),
            "cookies": self.cookies_var.get(),
            "attempts": self.attempts(),
            "parallel": self.workers(),
        })

    def attempts(self) -> int:
        return clamp_int(self.attempts_var.get(), ATTEMPTS, 1, 10)

    def workers(self) -> int:
        return clamp_int(self.parallel_var.get(), PARALLEL, 1, MAX_PARALLEL)

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
                     foreground=C["fg"], borderwidth=0, rowheight=22,
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
            st.configure(f"{accent}.T.TButton", background=C["panel"],
                         foreground=C[accent], font=(self.mono, 10, "bold"),
                         borderwidth=0, relief="flat", padding=(14, 5),
                         focuscolor=C[accent], anchor="center", width=0)
            st.map(f"{accent}.T.TButton",
                   background=[("pressed", C["line"]), ("active", C["line"])],
                   foreground=[("disabled", C["line"])])
        st.configure("T.TCombobox", fieldbackground=C["panel"], background=C["panel"],
                     foreground=C["fg"], arrowcolor=C["dim"], bordercolor=C["line"],
                     selectbackground=C["panel"], selectforeground=C["fg"])
        self.root.option_add("*TCombobox*Listbox.background", C["panel"])
        self.root.option_add("*TCombobox*Listbox.foreground", C["fg"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", C["line"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", C["green"])
        self.root.option_add("*TCombobox*Listbox.font", (self.mono, 10))

    # -- widget helpers ----------------------------------------------------

    def entry(self, parent, width=20, textvariable=None):
        e = tk.Entry(parent, bg=C["panel"], fg=C["fg"], font=self.f, width=width,
                     relief="flat", insertbackground=C["green"],
                     textvariable=textvariable,
                     highlightthickness=1, highlightbackground=C["line"],
                     highlightcolor=C["green"], selectbackground=C["line"])
        return self.wire_entry(e)

    def button(self, parent, text, cmd, accent="green"):
        """A real button, not a Label that happens to react to clicks.

        ttk.Button is what gives Tab focus, Space and Return activation, and
        the control an accessibility tool needs to announce as a button. The
        Label version looked identical and was reachable by mouse only.
        """
        return ttk.Button(parent, text=text, command=cmd, takefocus=True,
                          cursor="hand2", style=f"{accent}.T.TButton")

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
        tk.Label(head, text=f"  v{VERSION}  ::  {self.t('tagline')}",
                 bg=C["bg"], fg=C["dim"], font=self.f).pack(side="left", pady=(5, 0))

        tk.Frame(self.root, bg=C["line"], height=1).pack(fill="x", pady=(8, 12), **pad)

        row = tk.Frame(self.root, bg=C["bg"])
        row.pack(fill="x", **pad)
        tk.Label(row, text=">", bg=C["bg"], fg=C["green"],
                 font=self.fb).pack(side="left", padx=(0, 8))
        self.url = self.entry(row, textvariable=self.url_var)
        self.url.pack(side="left", fill="x", expand=True, ipady=5)
        self.url.bind("<Return>", lambda _e: self.do_scan())
        self.scan_btn = self.button(row, self.t("scan"), self.do_scan)
        self.scan_btn.pack(side="left", padx=(8, 0))
        self.button(row, self.t("clear"), self.do_clear,
                    "dim").pack(side="left", padx=(6, 0))
        self.refresh_btn = self.button(row, self.t("refresh"), self.do_refresh, "cyan")
        self.refresh_btn.pack(side="left", padx=(6, 0))


        opt = tk.Frame(self.root, bg=C["bg"])
        opt.pack(fill="x", pady=(10, 0), **pad)
        self.label(opt, self.t("quality")).pack(side="left")
        self.quality = ttk.Combobox(opt, values=list(FORMATS), state="readonly",
                                    width=11, style="T.TCombobox", font=self.f,
                                    textvariable=self.quality_var)
        self.quality.pack(side="left", padx=(6, 16))
        self.button(opt, self.t("settings"), self.open_settings,
                    "cyan").pack(side="left")
        self.settings_hint = tk.Label(opt, bg=C["bg"], fg=C["line"], font=self.f)
        self.settings_hint.pack(side="left", padx=(12, 0))
        self.refresh_hint()

        out = tk.Frame(self.root, bg=C["bg"])
        out.pack(fill="x", pady=(8, 0), **pad)
        self.label(out, self.t("save_to")).pack(side="left")
        self.outdir = self.entry(out, textvariable=self.outdir_var)
        self.outdir.pack(side="left", fill="x", expand=True, padx=(6, 6), ipady=3)
        self.button(out, self.t("browse"), self.pick_dir, "cyan").pack(side="left")
        self.button(out, self.t("open"), self.open_dir,
                    "cyan").pack(side="left", padx=(6, 0))
        self.ff_btn = self.button(out, self.t("get_ffmpeg"), self.get_ffmpeg, "amber")
        if not ffmpeg_path():
            self.ff_btn.pack(side="left", padx=(6, 0))

        # --- results: list on the left, preview on the right ---------------
        wrap = tk.Frame(self.root, bg=C["bg"])
        wrap.pack(fill="both", expand=True, pady=(14, 0), **pad)

        left = tk.Frame(wrap, bg=C["bg"])
        left.pack(side="left", fill="both", expand=True)
        self.tree = ttk.Treeview(left,
                                 columns=("mark", "kind", "size", "info", "name"),
                                 show="headings", style="T.Treeview",
                                 selectmode="extended")
        for col, txt, w, anchor in (("mark", "", 34, "center"),
                                    ("kind", self.t("col_type"), 66, "w"),
                                    ("size", self.t("col_size"), 66, "e"),
                                    ("info", self.t("col_info"), 220, "w"),
                                    ("name", self.t("col_name"), 340, "w")):
            self.tree.heading(col, text=txt)
            self.tree.column(col, width=w, anchor=anchor, stretch=(col == "name"))
        sb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview,
                           style="T.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        for kind, colour in TAG_COLOURS.items():
            self.tree.tag_configure(kind, foreground=colour)
        self.tree.tag_configure("marked", background=C["line"])
        self.tree.bind("<Button-1>", self.on_row_click)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.show_preview())
        self.tree.bind("<Double-1>", lambda _e: self.do_download())
        # Marking was mouse-only: arrow keys moved the selection but there was
        # no way to actually mark a row without clicking it.
        self.tree.bind("<space>", self.on_row_key)
        self.tree.bind("<Return>", self.on_row_key)
        self.root.bind_all("<Control-KeyPress>", self.on_ctrl)

        right = tk.Frame(wrap, bg=C["panel"], width=PREVIEW_W + 20)
        right.pack(side="right", fill="y", padx=(12, 0))
        right.pack_propagate(False)
        self.thumb_box = tk.Label(right, bg=C["panel"], fg=C["dim"], font=self.f,
                                  text="\n\n" + self.t("preview_hint"), justify="center")
        self.thumb_box.pack(pady=(10, 6), padx=10)
        self.meta_box = tk.Label(right, bg=C["panel"], fg=C["dim"], font=self.f,
                                 justify="left", anchor="nw",
                                 wraplength=PREVIEW_W, text="")
        self.meta_box.pack(fill="x", padx=10)
        self.thumb_ref = None   # PhotoImage must outlive this call
        self.thumb_cache: dict[str, object] = {}
        self.preview_token = 0  # ignore thumbnails that arrive after a new pick

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
        self.status.pack(side="left")
        self.prog = ttk.Progressbar(bar, style="T.Horizontal.TProgressbar",
                                    length=200, maximum=100)
        self.prog.pack(side="left", padx=(10, 10))
        self.dl_btn = self.button(bar, self.t("download"), self.do_download, "amber")
        self.dl_btn.pack(side="left")
        self.stop_btn = self.button(bar, self.t("stop"), self.stop_all, "red")

    # -- marking, preview, log --------------------------------------------

    def on_row_click(self, event):
        """A plain click marks the row - that is how you queue several at once."""
        if self.tree.identify("region", event.x, event.y) != "cell":
            return None
        row = self.tree.identify_row(event.y)
        if not row:
            return None
        if self.busy:
            self.pull_from_queue(row)
        else:
            self.toggle_mark(row)
        self.tree.selection_set(row)  # keep the preview in step
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
        self.tree.set(row, "mark", "[-]")
        self.log(f"pulled from queue :: {self.items[index].name}", "warn")
        self.say(self.t("pulled", n=len(self.cancelled)), C["amber"])

    def stop_all(self):
        if not self.busy:
            return
        self.cancelled.update(range(len(self.items)))
        for row in self.tree.get_children():
            self.tree.set(row, "mark", "[-]")
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
        self.set_thumb(None, self.t("preview_hint"))
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
        self.tree.set(row, "mark", "[x]" if on else "[ ]")
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

    def show_preview(self):
        rows = self.tree.selection()
        if not rows:
            return
        it = self.items[self.tree.index(rows[0])]
        self.preview_token += 1
        token = self.preview_token
        block = [f"{it.kind}  ::  {human(it.size)}", "", it.name]
        if it.details:
            block += ["", it.details]
        block += ["", it.url[:200]]
        self.meta_box.config(text="\n".join(block))
        if not it.thumb:
            self.set_thumb(None, self.t("no_preview"))
            return
        cached = self.thumb_cache.get(it.thumb)
        if cached is not None:
            self.set_thumb(cached or None, self.t("preview_failed"))
            return
        self.set_thumb(None, self.t("loading"))
        threading.Thread(
            target=self._thumb_worker,
            args=(it.thumb, it.url if it.kind == "image" else "", token,
                  self.proxy_var.get().strip() or None),
            daemon=True).start()

    def _thumb_worker(self, url, real_url, token, proxy):
        try:
            from PIL import Image, ImageTk  # noqa: F401  (imported for the main thread)
            import io
            session = session_for(proxy)
            r = session.get(url, timeout=20, stream=True)
            r.raise_for_status()
            # ponytail: cap the fetch - a preview never needs a 40 MB original
            data = r.raw.read(PREVIEW_MAX_BYTES + 1, decode_content=True)
            img = Image.open(io.BytesIO(data))
            dims = f"{img.width}x{img.height}"
            img.thumbnail((PREVIEW_W, PREVIEW_W), Image.LANCZOS)
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
            if it.thumb == thumb_url and it.kind == "image" and not it.info:
                it.info = dims
                rows = self.tree.get_children()
                if i < len(rows):
                    self.tree.set(rows[i], "info", dims)

    def set_thumb(self, photo, text=""):
        self.thumb_ref = photo
        if photo is None:
            self.thumb_box.config(image="", text=f"\n\n{text}", height=12, width=30)
        else:
            self.thumb_box.config(image=photo, text="", height=0, width=0)

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
        if self.proxy_var.get().strip():
            bits.append("proxy")
        if self.cookies_var.get():
            bits.append(f"cookies:{self.cookies_var.get()}")
        if self.clean_var.get():
            bits.append("strip")
        if not ffmpeg_path():
            bits.append("no ffmpeg")
        self.settings_hint.config(text="  ".join(bits))

    def open_settings(self):
        win = tk.Toplevel(self.root)
        win.title(self.t("dlg_title"))
        win.configure(bg=C["bg"])
        win.transient(self.root)
        win.resizable(False, False)

        body = tk.Frame(win, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=20, pady=18)

        def head(text):
            tk.Label(body, text=text, bg=C["bg"], fg=C["green"], font=self.fb,
                     anchor="w").pack(fill="x", pady=(12, 3))

        def hint(text):
            tk.Label(body, text=text, bg=C["bg"], fg=C["dim"], font=self.f,
                     anchor="w", justify="left").pack(fill="x", pady=(2, 0))

        # language ---------------------------------------------------------
        head(self.t("dlg_language"))
        names = list(LANGUAGES.values())
        lang_box = ttk.Combobox(body, values=names, state="readonly", width=18,
                                style="T.TCombobox", font=self.f)
        lang_box.set(LANGUAGES[self.t.lang])
        lang_box.pack(anchor="w")
        hint(self.t("dlg_lang_note"))

        # download folder --------------------------------------------------
        head(self.t("save_to"))
        folder = tk.Frame(body, bg=C["bg"])
        folder.pack(fill="x")
        self.entry(folder, width=40, textvariable=self.outdir_var).pack(
            side="left", fill="x", expand=True, ipady=3)
        self.button(folder, self.t("browse"), self.pick_dir,
                    "cyan").pack(side="left", padx=(6, 0))

        # proxy ------------------------------------------------------------
        head(self.t("dlg_proxy"))
        self.entry(body, width=46, textvariable=self.proxy_var).pack(
            fill="x", ipady=3)
        hint(self.t("dlg_proxy_hint"))

        # cookies ----------------------------------------------------------
        head(self.t("dlg_cookies"))
        cookie_box = ttk.Combobox(body, values=COOKIE_BROWSERS, state="readonly",
                                  width=18, style="T.TCombobox", font=self.f,
                                  textvariable=self.cookies_var)
        cookie_box.pack(anchor="w")
        hint(self.t("dlg_cookies_hint"))

        # metadata + attempts ----------------------------------------------
        head(self.t("dlg_strip"))
        tk.Checkbutton(body, text=self.t("dlg_strip"), variable=self.clean_var,
                       bg=C["bg"], fg=C["fg"], font=self.f, selectcolor=C["panel"],
                       activebackground=C["bg"], activeforeground=C["green"],
                       highlightthickness=0, borderwidth=0,
                       cursor="hand2", anchor="w").pack(fill="x")
        hint(self.t("dlg_strip_hint"))

        head(self.t("dlg_parallel"))
        tk.Spinbox(body, from_=1, to=MAX_PARALLEL, width=5,
                   textvariable=self.parallel_var,
                   bg=C["panel"], fg=C["fg"], font=self.f, relief="flat",
                   buttonbackground=C["line"], insertbackground=C["green"],
                   highlightthickness=1, highlightbackground=C["line"]).pack(anchor="w")
        hint(self.t("dlg_parallel_hint"))

        head(self.t("dlg_attempts"))
        tk.Spinbox(body, from_=1, to=10, width=5, textvariable=self.attempts_var,
                   bg=C["panel"], fg=C["fg"], font=self.f, relief="flat",
                   buttonbackground=C["line"], insertbackground=C["green"],
                   highlightthickness=1, highlightbackground=C["line"]).pack(anchor="w")

        head(self.t("dlg_ffmpeg"))
        ff = ffmpeg_path()
        tk.Label(body, text=ff or self.t("dlg_ffmpeg_missing"), bg=C["bg"],
                 fg=C["fg"] if ff else C["amber"], font=self.f, anchor="w",
                 wraplength=420, justify="left").pack(fill="x")

        # buttons ----------------------------------------------------------
        foot = tk.Frame(body, bg=C["bg"])
        foot.pack(fill="x", pady=(20, 0))

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
        self.button(foot, self.t("cancel"), win.destroy,
                    "dim").pack(side="right", padx=(0, 8))

        win.bind("<Escape>", lambda _e: win.destroy())
        win.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
        y = self.root.winfo_rooty() + 60
        win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
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

    def say(self, text, colour=None):
        self.q.put(("status", text, colour or C["dim"]))

    def get_ffmpeg(self):
        if self.busy:
            return
        if not messagebox.askyesno(
                "get ffmpeg",
                f"Download the official static ffmpeg build (~40 MB) from\n\n"
                f"{urlparse(FFMPEG_ZIP).netloc}\n\ninto:\n{BIN_DIR}\n\n"
                "It is needed for 1080p and above, since those ship video and "
                "audio as separate streams. Proceed?"):
            return
        self.set_busy(True)
        threading.Thread(target=self._ffmpeg_worker, daemon=True).start()

    def _ffmpeg_worker(self, auto=False):
        try:
            if auto:
                self.log("ffmpeg missing - fetching it in the background", "warn")
            self.say(self.t("ffmpeg_dl"), C["fg"])
            path = fetch_ffmpeg(
                lambda done, total: None if auto else self.q.put(
                    ("prog", (done / total * 100) if total else 0, None)))
            self.q.put(("prog", 100, None))
            self.say(self.t("ffmpeg_ready"), C["green"])
            self.log(f"ffmpeg installed at {path}", "ok")
            self.q.put(("hide_ff", None, None))
        except Exception as exc:
            self.say(self.t("ffmpeg_failed", err=exc), C["red"])
            self.log(f"ffmpeg download failed :: {exc}. Use the 'get ffmpeg' "
                     f"button to retry, or install it on your PATH.", "error")
        finally:
            if not auto:
                self.q.put(("busy", False, None))

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
        self.tree.delete(*self.tree.get_children())
        self.items = []
        self.marked.clear()
        threading.Thread(target=self._scan_worker, args=(url,), daemon=True).start()

    def _scan_worker(self, url):
        self.log(f"scan {url}")
        try:
            items = scan(url, self.proxy_var.get().strip() or None, self.say,
                         self.cookies_var.get(),
                         self.t("no_video", site=urlparse(url).netloc),
                         self.t("try_cookies"))
            self.q.put(("items", items, None))
            if items:
                self.log(f"found {len(items)} items", "ok")
                self.say(self.t("found", n=len(items)), C["green"])
            else:
                self.log("nothing downloadable found at this link", "warn")
                self.say(self.t("nothing_found"), C["amber"])
        except Exception as exc:
            self.say(self.t("scan_failed", err=exc), C["red"])
            self.log(f"scan failed :: {exc}", "error")
            self.log(traceback.format_exc().rstrip(), "error")
        finally:
            self.q.put(("busy", False, None))

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
        self.stop_btn.pack(side="left", padx=(6, 0))
        threading.Thread(
            target=self._dl_worker,
            args=(picks, outdir, self.proxy_var.get().strip() or None,
                  self.quality_var.get(), self.clean_var.get(),
                  self.cookies_var.get(), self.workers(), self.attempts()),
            daemon=True).start()

    def _dl_worker(self, picks, outdir, proxy, quality, clean, cookies="",
                   workers=PARALLEL, tries=ATTEMPTS):
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
                                           progress, cookies)
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
        for b in (self.scan_btn, self.dl_btn, self.ff_btn, self.refresh_btn):
            b.state(["disabled"] if busy else ["!disabled"])
        if busy:
            self.prog.config(value=0)

    def pump(self):
        try:
            while True:
                kind, a, b = self.q.get_nowait()
                if kind == "status":
                    if len(a) > STATUS_CHARS:
                        a = a[:STATUS_CHARS - 3] + "..."
                    self.status.config(text=a, fg=b)
                elif kind == "prog":
                    self.prog.config(value=a)
                elif kind == "busy":
                    self.set_busy(a)
                elif kind == "hide_ff":
                    self.ff_btn.pack_forget()
                elif kind == "hide_stop":
                    self.stop_btn.pack_forget()
                elif kind == "log":
                    self._write_log(*a)
                elif kind == "thumb":
                    url, token, img = a
                    if img is None:
                        self.thumb_cache[url] = False
                        if token == self.preview_token:
                            self.set_thumb(None, self.t("preview_failed"))
                        self.log(f"preview failed :: {b}", "warn")
                    else:
                        from PIL import ImageTk
                        photo = ImageTk.PhotoImage(img)
                        # ponytail: a decoded bitmap each, and a playlist can be
                        # 200 rows. Dropping the lot is fine - worst case a
                        # revisited row re-fetches its preview.
                        if len(self.thumb_cache) > MAX_THUMB_CACHE:
                            self.thumb_cache.clear()
                        self.thumb_cache[url] = photo
                        if token == self.preview_token:
                            self.set_thumb(photo)
                        self.fill_dimensions(url, b)
                elif kind == "items":
                    self.items = a
                    for it in a:
                        # kind doubles as the resolution label ("2160p"), so fall
                        # back to the generic media tag for colouring those rows
                        tag = it.kind if it.kind in TAG_COLOURS else "media"
                        self.tree.insert("", "end", tags=(tag,),
                                         values=("[ ]", it.kind, human(it.size),
                                                 it.info, it.name))
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
    assert kind_of("https://x.com/p/photo.WEBP") == "image"
    assert kind_of("https://x.com/page") is None
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
    assert [r.kind for r in rows] == ["image", "1080p", "360p"], [r.kind for r in rows]
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

    from i18n import LANGUAGES as _langs, STRINGS as _strings, Tr as _Tr
    base = set(_strings["en"])
    for code in _langs:
        assert code in _strings, f"{code} listed but not translated"
        assert not base - set(_strings[code]), f"{code} missing {base - set(_strings[code])}"
    for _code in _langs:
        assert "{site}" in _strings[_code]["no_video"], f"{_code} lost the site slot"
        assert "cookies" in _strings[_code]["try_cookies"].lower() or _code != "en"
    tr = _Tr("el")
    assert tr("found", n=3) != _strings["en"]["found"], "greek must differ"
    assert tr("unknown_key_xyz") == "unknown_key_xyz", "missing key must not crash"
    assert _Tr("klingon").lang == "en", "unknown language falls back"

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
    assert [r.kind for r in rows] == ["2160p", "1080p", "360p", "270p", "audio", "mp3"],         [r.kind for r in rows]
    assert rows[5].fmt == "mp3" and rows[5].size == 1000, "mp3 row rides the audio track"
    twitter = rows[3]
    assert twitter.fmt == "http-99" and twitter.size == 3000, "unknown codec = complete file"
    assert "*" not in twitter.name, "must not demand ffmpeg it does not need"
    # video-only sizes include the audio track that gets merged in
    assert rows[0].size == 91000 and rows[1].size == 41000
    assert rows[1].fmt.startswith("v1080+"), "should keep the higher-bitrate 1080p"
    # progressive row carries no merge, so no ffmpeg needed and no star
    assert rows[2].fmt == "p360" and "+" not in rows[2].fmt
    assert "*" not in rows[2].name, "a complete file is never flagged"
    assert "+" in rows[0].fmt, "2160p must merge a separate audio track"
    # the star tracks ffmpeg, so pin the rule itself rather than this machine
    assert merge_mark(False, False) == " *", "flag a merge row with no ffmpeg"
    assert merge_mark(False, True) == "", "no flag once ffmpeg is there"
    assert merge_mark(True, False) == "", "progressive never needs the flag"
    assert rows[4].size == 1000 and rows[4].fmt == "a"
    assert media_variants({"formats": []}, "x", "u") == []

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
        gated = [app.scan_btn, app.dl_btn, app.ff_btn, app.refresh_btn]
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

        # every language change used to leave another pump loop running
        pending = len(root.tk.call("after", "info"))
        for code in LANGUAGES:
            app.t.set(code)
            app.rebuild()
            assert len(root.tk.call("after", "info")) == pending, "rebuild leaked a timer"
        assert len(app.tree.get_children()) == 2, "results lost on language change"

        app.close()   # remember() must not raise on the way out
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
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
