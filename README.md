# convertex

Paste a link, see what is downloadable, take it clean.

## Run

Double-click **`run.bat`**. It installs anything missing and opens the app.
Nothing else to set up.

**No console window sticks around.** The app is launched with `pythonw`, the
console-less python, and `run.bat` closes as soon as it has done so. A terminal
only appears if a dependency is actually missing, and only for as long as the
install takes.

yt-dlp refreshes itself from inside the app, on a background thread, with no
window of its own - it breaks whenever a site changes its markup, so a copy that
worked last week may not work today. The new version applies at the next launch.
Failure there is a line in the log, not an interruption: being offline is the
usual reason and the installed copy still works for every site that has not
changed.

Because `pythonw` has no console to print to, a crash before the window appears
writes `crash.log` next to the app and shows the error in a dialog.

### Standalone exe

`build.bat` produces `dist\convertex.exe`. That one file is the whole program:
Python, yt-dlp, requests, Pillow and **ffmpeg** are all inside it. The machine
that runs it needs nothing installed and downloads nothing on first launch.

Three flags matter and are easy to lose:

- `--collect-all yt_dlp` - the site extractors are imported lazily by name, so
  without this the exe silently supports only a handful of sites.
- `--collect-all certifi` - the CA bundle, or every HTTPS request fails once frozen.
- `--add-binary binfmpeg.exe;bin` - without it the exe falls back to
  downloading ffmpeg on first run, which defeats the point.

The build refuses to continue if ffmpeg is missing rather than quietly shipping
a crippled exe.

**Where settings go.** Beside the exe when that folder is writable, so a copy on
a USB stick stays self-contained. In `%APPDATA%\convertex` when it is not - an exe
in Program Files cannot write next to itself, and silently losing every setting
is a miserable way to discover that.

## What it does

- **Media sites** (YouTube, X/Twitter, Instagram, TikTok, Reddit, ~1800 more) go
  through `yt-dlp`. A single video is expanded into **one row per resolution with
  its real byte size** - 2160p / 1440p / 1080p / 720p / down to audio-only - so you
  pick by what it actually costs, not by guessing.
- **Any other page** is scraped for images, video, audio, pdf, archives.
- **Images auto-upgrade**: thumbnails are resolved to their full-resolution
  original (WordPress `-800x600`, MediaWiki `/thumb/.../500px-`, `?w=` resizers,
  `:small` on X). Measured: an 89 KB thumbnail became the 4.4 MB original.
- **Metadata is stripped** before the file lands: EXIF/XMP/IPTC out of JPEG, text
  chunks out of PNG (both lossless - no re-encoding), container tags out of video
  via ffmpeg, and the Windows `Zone.Identifier` stream that records the source URL
  of every download.

## ffmpeg

It arrives with the dependencies. `requirements.txt` asks for `imageio-ffmpeg`,
which is the same gyan.dev static build the app used to download for itself,
packaged as a wheel - so **pip checks its hash on the way in** and there is
nothing here to verify by hand or keep pinned. There is no button and no
first-run download.

A copy in `bin\` next to the app still wins, so dropping a newer or
differently-built ffmpeg there overrides the packaged one. After that comes the
wheel, then whatever is on your PATH.

It matters because above roughly 360p YouTube ships video and audio as **separate
streams** that have to be merged, and mp3 needs re-encoding. Rows that cannot run
without it are marked `*`; the mark disappears once it is installed.

## Audio and mp3

The resolution list ends with two audio rows: the **source track** as the site
serves it (m4a/opus, no re-encoding, best fidelity) and **mp3 at 320 kbps**
re-encoded for players that demand mp3. The quality dropdown has `mp3` too, for
playlists.

Verified on a real download: `bit_rate=320027`, and `format_tags` comes back
empty - no encoder signature, no source URL.

## Marking, preview, log

**Click a row to mark it**, or move to it with the arrow keys and press Space.
Marked rows show `[x]` and the status line keeps a running total - `3 marked :: 412.6M total` - so you can queue two videos and ten
photos in one go and see what it costs before starting. Download takes the marked
rows; with nothing marked it takes everything. Ctrl+A marks all, Ctrl+A again
clears.

The **preview pane** on the right shows the selected item: the image itself for
scraped pictures, the site's own thumbnail for videos, plus type, size and source
URL. Thumbnails load in the background and are cached, and the fetch is capped so
previewing never pulls a 40 MB original.

The **log panel** records every scan and download - what was tried, what was
saved, and why anything failed, with a full traceback for unexpected errors. It
**opens by itself on any failure**, so a summary line like `0 saved, 1 failed`
never leaves you guessing. `log` toggles it, `copy log` puts the whole thing on
the clipboard. It lives in memory only and is not written to disk.

## Keyboard

**Tab moves between the buttons**, Space or Return presses the focused one, and
Space on a row in the list marks it. Nothing needs a mouse. The buttons are real
controls rather than styled labels, so a screen reader announces them as buttons
and a disabled one drops out of the tab order instead of merely going grey.

Ctrl+V / Ctrl+C / Ctrl+X / Ctrl+A are wired to **physical key codes**, not to the
letters Tk sees. Tk's built-in bindings match the keysym, so on a Greek (or any
non-Latin) layout the V key reports a Greek letter and pasting silently does
nothing. Every field also has a **right-click menu** with cut / copy / paste /
select all. Pasted links get surrounding whitespace and newlines trimmed.

## Cancelling a stuck download

**Click a row while a download is running and it leaves the queue.** The one in
flight aborts at its next chunk; anything still queued is skipped. That is the way
out when a server stops responding mid-transfer. The row shows `[-]` and the
partial bytes stay in the `.part` file, so restarting it later resumes rather than
starting over.

**`stop`** appears next to `download` while it runs and cancels everything at once.
Sockets also give up after 60 seconds of silence, so a dead connection now fails
and retries instead of hanging forever.

**`refresh`** re-scans the link already in the box. **`clear`** empties the box
and the results with it.

## Rate limits

Parallelism aimed at one host is what trips rate limiters, so at most **2
connections per host** run at once no matter how high the worker count goes. A
batch spread over several sites still runs at full width.

A `429` is treated as an instruction, not a blip: 5s, 15s, 45s between tries
rather than 1s, 2s, 4s. A `Retry-After` header is obeyed when it asks for longer
and ignored when it asks for less than that floor - hosts that say "1 second"
while still refusing just burn the retry budget.

## Parallel downloads

Four files at once by default, 1-8 in settings. The status line, the progress bar
and the `download` button sit together at the bottom, with the log controls hard
right:

```
3/10  4 running  5.2M/s  eta 1m20s        [====----]  download
```

The bar tracks the **whole batch**, not one file. The log keeps the per-file
detail - what started, what saved, what failed and why.

Two races only parallel work exposes, both closed:

- **Filename claim.** Two workers could pick the same free name in the gap
  between checking and writing. Claiming the name and moving the file into it is
  now one locked step.
- **`.part` collision.** Partials were keyed by filename, so two different files
  called `photo.jpg` appended into each other. They are keyed by URL now, which
  also keeps resume working - the same link maps to the same partial.

## What each row tells you

The **INFO** column carries the technical summary:

```
1080p   8.1M   2:41  1080x1080  25fps  avc1
audio   2.6M   2:41  opus  134k  48kHz  stereo
mp3     2.6M   2:41  mp3  320k
image   4.4M   3640x2226
```

Image dimensions are read from the file's **header only** - a 64 KB ranged
request, not the whole download. They fill in when you select the row.

The preview pane carries what does not fit in a column: uploader, upload date,
duration, views, likes, codec, bitrate, container, and the source URL.

### One thing worth knowing about image sizes

A scraped thumbnail is previewed at thumbnail size but downloaded at full size,
because convertex upgrades the URL. Reporting the preview's dimensions would
describe the wrong file, so the real ones are fetched separately. When they
cannot be read the cell stays **empty** rather than showing a number that is not
what you will get.

## Resume and retry

Interrupted downloads pick up where they stopped. Bytes land in a `.part` file
next to the target and the next attempt sends an HTTP `Range` header, so a
connection drop at 90% costs you the last 10%, not the whole file. The `.part`
only becomes the real file once it is complete.

Each item gets **3 tries** with 1s / 2s backoff, and every retry resumes rather
than restarting. yt-dlp resumes its own fragments the same way. Failures that
retrying cannot fix - a resolution needing ffmpeg you do not have - are reported
immediately instead of burning attempts.

Once an item has run out of tries its `.part` is deleted: nothing is ever going to
finish it, and a download folder slowly filling with dead partials is its own
problem. A `.part` left by **cancelling** is kept, because that one still resumes.

## Settings

`settings.json` sits next to the app and remembers your **download folder**,
proxy, quality, and the strip-metadata toggle. Written when a download starts and
when you close the window. It holds preferences only - **no link history**.

Delete the file to reset. If the folder is read-only, the app runs fine and just
does not remember.

## Settings

The `settings` button opens the dialog: **language**, **quality**,
**download folder**, proxy, browser cookies, strip-metadata, and tries per file.
It also shows where ffmpeg was found. A short line beside the button says what is
currently on - `proxy  cookies:firefox  strip` - so nothing is silently active.

Everything is written to `settings.json` next to the app and reloaded on start,
so your download folder is the one you picked last time.

### Language

English and Ελληνικά. The window redraws in place when you change it - your scan
results and marks survive. Missing keys fall back to English rather than crashing,
so a partial translation is usable.

Spanish and German are translated and still sit in `i18n.py`, just not offered:
putting either back in front of the user is adding its code to the `LANGUAGES`
dict, nothing else. A new language is one more dict of strings.

Log lines stay English on purpose. They are diagnostics, and an English log is
the one you can paste into a bug report or search for.

### X / Twitter

yt-dlp's Twitter extractor only handles **video**. A tweet full of photos comes
back as "No video could be found", which used to fall through to scraping - and
scraping x.com logged-out returns avatars and interface icons, so it looked like
the app simply did not work.

convertex now falls back to X's public embed API, the one that powers embedded
tweets. It returns the real media as JSON, including photos, which are fetched at
`?name=orig` - the untouched upload, not the display-sized copy.

| What you paste | What happens |
|---|---|
| tweet with photos | one row per photo, at original resolution |
| tweet with video | one row per resolution, up to 1080p |
| text-only tweet | says so, no junk rows |
| login-walled tweet | `this post is not publicly viewable - it needs a login` |
| profile page | says the URL is unsupported |

Each failure gives **one** reason - the most specific one available - plus the
cookies pointer when cookies could plausibly help.

A **login-walled tweet cannot be reached logged out by any method** - not the
embed API, not scraping. Browser cookies are the only way in.

### Browser cookies

X, Instagram and private playlists increasingly refuse logged-out access. Setting
`use cookies from` to your browser lets yt-dlp reuse that session, which is the
only thing that gets past a login wall.

**This works against anonymity.** Cookies identify you to the site as your own
account - far more precisely than an IP. Leave it empty unless a link actually
needs it, and do not combine it with Tor expecting to stay unidentified.

## Anonymity

The **proxy box is the switch**. `socks5://127.0.0.1:9050` for Tor, or any
VPN/proxy endpoint. It applies to scanning and downloading alike.

The app keeps no history, no cache, no cookies, and sends no telemetry. But with
the box empty the site sees your real IP - no application can change that. Tor is
frequently blocked by YouTube and Cloudflare, so expect it to be unreliable there.

## Testing it

```
python convertex.py --selftest
```

Checks the metadata strippers, the thumbnail-upgrade rules, the resolution table
logic, the resume arithmetic, and the settings round-trip. Offline, under a second.

By hand, one link per path:

| Paste this | Expect |
|---|---|
| `https://www.youtube.com/watch?v=aqz-KE-bpKQ` | 9 rows, 2160p at ~1.3G down to audio at ~9.8M |
| `https://en.wikipedia.org/wiki/Cat` | ~199 rows, 137 images, top one ~4.4M (the upgraded original, not the 89K thumb) |
| any YouTube playlist | one row per video, capped at 200; the quality dropdown applies here |
| `https://x.com/SpaceX/status/1732824684683784516` | 6 rows, 1080p at ~141M, none needing ffmpeg |
| a tweet with no video | the reason plus a pointer to cookies, not a list of scraped avatars |
| a private or geoblocked video | the real reason on the status line, e.g. `Video unavailable` |

To see resume work: start a large download, kill the app mid-transfer, reopen and
download the same row. It continues from the `.part` file instead of starting over.

Ctrl+A selects everything. Nothing selected means everything gets downloaded.
Double-click a row downloads it.

Downloading from sites that forbid it in their terms is on you, and the material
is often copyrighted. yt-dlp itself is legal open source.

## Stopping a scan

A scan that is still waiting can be stopped with the same **stop** button the
downloads use. The request itself cannot be killed - it is parked in a socket
read, which is the one thing a thread cannot be talked out of - so what stopping
does is hand the window back immediately and throw the answer away when it
finally arrives. yt-dlp's side of a scan is bounded by the same 60s socket
timeout the downloader uses, so nothing waits forever either way.

## Type and quality are two different questions

The TYPE column says what a row **is** - video, audio, image, doc, archive,
file - and nothing else. How good a copy it is lives in QUALITY: `1080p webm`,
`mp3 320k`, `2048x1365`. These used to share one column, which is how a list
could show `1080p`, `image` and `media` side by side as if they were the same
kind of answer.

The quality dropdown moved into settings, because it only ever applied to
**playlists** and to pages that hand over no format list. Anywhere the scan can
read the formats - which is nearly everywhere - each resolution is already its
own row and the dropdown was ignored. Rows it does apply to say `as set` in the
quality column rather than promising a resolution nothing has checked yet.

`download` appears twice, once above the list and once in the status bar. On a
tall window the bottom one is a long way from where you finish picking rows.

## The columns

`TYPE` is what a row is - and it is translated, because those are words.
`QUALITY`, `LENGTH`, `SIZE` and `INFO` carry format names - `mp4`, `vp9`,
`avc1`, `fps`, `kHz` - which are not translated in any language, because they
are what the format is called rather than something to say in Greek.

**A resolution label names the short side.** A 1080x1920 phone clip is a 1080p
video; calling it `1920p`, which is what using the height gives you, is a
number nobody uses. Landscape is unaffected - there the short side is the
height anyway.

**Duration has its own column.** It used to sit unlabelled at the front of the
INFO line, next to the dimensions and the codec, with nothing saying what it
was.

Everything in the table is centred, heading and cell alike, and INFO stretches
alongside NAME so the columns reach the right-hand edge whichever of them is
showing.

**NAME folds away when every row has the same one.** One video hands back a row
per resolution, all sharing a title, and on a maximised window that repeated
title had more space than anything else on screen. The title is shown once
above the list instead. A scraped page, where the names are what tell the rows
apart, keeps the column.

## Double click

Off by default. Turn it on in settings and a double click downloads the row
under the pointer. The reason it is not on to begin with: the first click of
the pair has already marked or unmarked that row, so a double click landing by
accident would queue something you never asked for.

## Embedded video, and the pictures around it

A page that embeds a video used to hand back one or the other. yt-dlp reads an
ordinary web page through its generic extractor, which follows the embed and
returns **that** - so the article's own photographs never appeared. Asking for
a link's media should not mean picking one.

Now a page that is not a known media host gets both: whatever yt-dlp resolved
out of the embed, listed first, followed by the images and files on the page
itself. Media hosts are still exempt - scraping one of those returns avatars
and interface icons rather than anything you asked for.

If yt-dlp finds nothing at all, the page scraper looks at the `<iframe>` tags
itself and passes anything yt-dlp has a real extractor for back through it.
That is a fallback: in testing, yt-dlp's own embed detection caught every
variant tried, including lazy-loaded `data-src` and protocol-relative ones.
Choosing which iframes are worth following is left to yt-dlp rather than to a
list of video hosts kept here, which drops the tracking pixels and the social
buttons for free - nothing has an extractor for those.

## Private session

A switch in settings. What it does:

- **No settings file.** Nothing about the session is written while it is on.
- **No crash file.** A crash still shows its dialog, it just leaves no file.
- **Cookies stay untouched**, whatever the cookie dropdown says. That is the
  one that matters: handing over your browser cookies tells the site which
  account is asking, by name.
- Deliberately **not remembered**. A privacy mode you get by accident because
  it was on last week is not one you can reason about - and remembering it
  would mean writing the very file it exists to suppress.

What it does **not** do, and the hint line says so when no proxy is set: it
does not hide the download from the site. Your address is in their logs either
way. Only a proxy changes that, and the two are separate switches on purpose.

## The exe

`build.bat` produces a single ~87MB `convertex.exe` with Python, yt-dlp, ffmpeg
and the certificates inside it. Verified by copying it to an empty folder with
no ffmpeg on PATH and running its self-test: it passes, which includes finding
its own ffmpeg. Nothing needs installing on the machine that runs it.

ffprobe is not bundled. Nothing here calls it, and it is another 100MB.
