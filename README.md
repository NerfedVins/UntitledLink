# UntitledLink

[![selftest](https://github.com/NerfedVins/UntitledLink/actions/workflows/selftest.yml/badge.svg)](https://github.com/NerfedVins/UntitledLink/actions/workflows/selftest.yml)

Paste a link, see what is downloadable, take it clean.

## Get it

Download **`UntitledLink.exe`** from
[Releases](https://github.com/NerfedVins/UntitledLink/releases) and double-click
it. Nothing to install: Python, yt-dlp and ffmpeg are all inside.

Windows shows a SmartScreen warning the first time, because the exe is not
signed with a paid certificate: **More info → Run anyway**. Every release lists
a SHA-256 if you would rather check what you downloaded first.

## Run

Double-click **`UntitledLink.vbs`**. It installs anything missing and opens the
app. Nothing else to set up.

**It starts in about half the time it used to.** requests, bs4 and Pillow cost
roughly half a second to import between them and none of them is needed to put
a window on screen, so they are imported where they are used and warmed on a
thread once the window is drawn - after the first paint rather than during it,
which was measured making things worse. The launcher does its own stamp check
in VBScript rather than starting a python to compare two dates. Time from
double-click to a window on screen: about 850ms, against 1.6s at its best
before.

**Nothing but the app appears.** `UntitledLink.vbs` runs the launcher with no
console at all, and the app itself is started with `pythonw`, the console-less
python. `run.bat` does the same work and still works, but Windows insists on
showing a console for the second it takes to start any batch file, which is the
one thing a .bat cannot be trimmed out of.

A terminal appears on purpose in one case: something needs installing. That is
worth watching, so the quiet launcher re-runs the batch in a real console where
pip can say what it is doing.

### macOS and Linux

There is no bundle for either, but the app itself runs on both: the suite,
including the one that builds a real window, passes on macOS in CI on every
push.

```bash
pip install -r requirements.txt
python3 untitledlink.py
```

tkinter is the one thing to watch on macOS - Apple's own Python ships a version
too old to use. A python.org build, or `brew install python-tk`, sorts it. The
`.bat` and `.vbs` launchers are Windows-only; everywhere else, run the file.

yt-dlp refreshes itself from inside the app, on the first scan rather than at
launch - it breaks whenever a site changes its markup, so a copy that worked
last week may not work today. Doing it on the first scan means it goes out by
whatever route that scan uses, rather than being the one connection that
ignored the proxy.

PyPI is asked directly instead of leaving the question to pip, because pip
cannot be made to answer it honestly: with the package already present and the
index unreachable it prints "Requirement already satisfied" and exits 0, with
no hint that it never got to look. So the log says `yt-dlp up to date (2026.8.19)`
only when that was checked, and `yt-dlp not checked` when it could not be.

**Nothing is left in the background.** Every process the app starts - pip,
ffmpeg - is tracked and killed when the window closes, whether it closes
normally or on the way out of a crash. Closing the window ends the session:
one process while it runs, none after.

Because `pythonw` has no console to print to, **nothing that goes wrong is
allowed to go nowhere.** A crash before the window appears writes `crash.log`
into that same settings folder and shows the error in a dialog. Anything that raises after
that - a button, a key, the queue the background threads talk through - says so
on the status line, writes its traceback to the log panel, which opens itself
on an error, and leaves the same `crash.log`. Not a dialog for that half: most
of them are one row failing to draw, and a modal for that is worse than the
fault. A private session writes no file either way.

### Standalone exe

`build.bat` produces `dist\UntitledLink.exe`. That one file is the whole program:
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

**Where settings go.** `%APPDATA%\UntitledLink\`, not beside the exe - so
wherever you keep the exe stays as tidy as you left it. Beside the exe only if
there is no profile to write to at all. See
[What is remembered](#what-is-remembered).

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
  via ffmpeg, and the address out of the Windows `Zone.Identifier` stream.

  That last one keeps what it should: the stream holds `ZoneId=3`, which is
  what makes Word and Excel open a downloaded file in Protected View, and
  `HostUrl`, which writes down exactly where you got it. Deleting the stream
  outright took the warning away with the address - on a `.docx` that warning
  is the whole defence. The address goes, the zone stays.

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

**Click the box on a row to mark it**, or move to it with the arrow keys and
press Space. Everything outside the box just shows the row - looking is the
more common thing to want, and marking wherever you clicked meant there was no
way to look at a row without queueing it.

Marked rows carry a ticked box and the status line keeps a running total -
`3 marked :: 412.6M total` - so you can queue two videos and ten photos in one
go and see what it costs before starting. Download takes the marked rows; with
nothing marked it takes everything **you can see**, which is what makes
narrowing the list to the mp4s and pressing download work. A row you marked
before narrowing is still marked and still downloads, whether it is on screen
or not. Ctrl+A marks all, Ctrl+A again clears.

The **preview pane** on the right shows the selected item: the image itself for
scraped pictures, the site's own thumbnail for videos, plus type, size and source
URL. Thumbnails load in the background and are cached, and the fetch is capped so
previewing never pulls a 40 MB original.

It waits 150ms for the selection to settle first. Every row an arrow key passes
over is a selection, and each one used to start a size request and a thumbnail
fetch that the next row immediately made pointless - two hundred of each for one
held-down key, and over tor slow and loud as well as wasted.

The **log panel** records every scan and download - what was tried, what was
saved, and why anything failed, with a full traceback for unexpected errors. It
**opens by itself on any failure**, so a summary line like `0 saved, 1 failed`
never leaves you guessing. `log` toggles it, `copy log` puts the whole thing on
the clipboard. It lives in memory only and is not written to disk.

## Search and filters

A lecture page comes back with two hundred rows and four pdfs in it. Two ways
of getting to them, because they answer different questions.

**The bar above the list is a search.** Type and it hides what does not match,
against everything a row says - name, kind, format, the address itself. This is
for a name you half remember.

**The `filters` button opens a card** with a box per thing the scan actually
found, in two groups:

```
KIND      video 8   audio 10
FORMAT    webm 10   mp4 5   m4a 2   mp3 1
```

Built from the results, not fixed: six kinds and forty extensions would be
mostly dead entries on any one page. The count sits beside each, which answers
"how many pdfs are in here" before you tick anything. The kinds keep the colour
of the rows they govern.

**Ticking is choosing what to see, not what to hide.** Nothing ticked shows
everything - the list is not narrowed until you say so - and ticking `mp4` is
one click rather than unticking the other seven. The button carries the number
of ticks while the card is shut, since that is the only thing on screen saying
a filter is on.

The three stack: text, kind, format, and a row has to pass all three. A new
scan clears them, because the boxes name what the last page had in it.

A format box is possible at all because of where the container is written. A
scraped row wears it on the end of its name; a yt-dlp row has no filename yet -
its name is the video's title - so it comes off the quality cell: `2160p mp4`,
`m4a 129k`, `mp3 320k`. Two rows genuinely do not know one, and neither becomes
a box: `as set`, where the resolution and the container are both decided at
download time, and a bare `audio` for a site that named no container.

**Hiding is not forgetting.** Rows are detached, not deleted, so a row keeps
its identity, its mark, and its place in the list while it is out of sight.

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

## How much a scan asks for

**The discreet scan is the default.** Measured on a 20-link page:

| | requests the site sees |
|---|---|
| full scan | **31** - one GET, then a HEAD per link, plus one per image while hunting a full-resolution copy |
| discreet scan | **1** - the page, and nothing else |
| discreet scan, three rows opened | **4** |

Rows arrive without a size and the SIZE column shows a dot; opening one measures
that one, and only that one. A dash means the question was asked and came back
empty, which is a different thing.

Untick it in settings for the full scan: sizes for everything up front to sort
by, and links that turn out to be web pages dropped before they reach the list.
That costs a request per link, which a small server reads as a scraper, and over
Tor it costs seconds per request.

## Keeping it working

yt-dlp is the part that rots: sites change their markup, yt-dlp ships a fix
within days, and a frozen exe cannot pip into itself. Run from source it
updates itself on the first scan of each session; the exe cannot, so fresh
builds come from CI instead.

**Automatically, on the first of each month.** The patch number moves, a tag
goes up, and both binaries are rebuilt with whatever yt-dlp is current that
day. The app tells you a newer version exists the next time you scan
something.

**By hand, when something breaks on the 5th.** Actions → *fresh build* → *Run
workflow*, type `go` in the confirm field. The `bump` field decides whether the
version moves: `patch` publishes 0.1.2 as 0.1.3 and everyone is told, `none`
replaces the binaries of the current version quietly - which also means nobody
hears about it, since the app compares version numbers.

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
because UntitledLink upgrades the URL. Reporting the preview's dimensions would
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

## What is remembered

`settings.json` holds your **download folder**, proxy, quality, language, how
many downloads run at once, how many tries each gets, and the strip-metadata,
discreet-scan, subtitles and double-click toggles. Written when a download
starts and when you close the window. Preferences only - **no link history**.

It lives in your profile - `%APPDATA%\UntitledLink\` on Windows,
`~/.config/UntitledLink/` elsewhere - along with the downloads list, if you turn
that on, and any crash file. A few KB of text, all of it.

It used to sit in the app's own folder, so that a copy on a USB stick was
self-contained. The price was paid by everyone who did not have one: an exe on
the desktop wrote `settings.json` onto the desktop beside itself, and an exe in
Program Files could not write at all. A file still at that old address is read
when there is none at the new one, so moving house does not reset what you had
set. The next save goes to the new place.

Two are deliberately not remembered: the private session and tor. A privacy
mode you get by accident, because it was on last week, is not one you can
reason about - and tor has to be running for it to mean anything, so a box that
was ticked a week ago is a scan that fails for a reason nobody remembers.

Delete the file to reset. If the folder is read-only, the app runs fine and
just does not remember.

## The settings

The `settings` button opens a card **over the window**, not a window of its
own. It used to be a Toplevel, and Windows places one of those wherever it
likes - with thirteen settings in it, tall enough that "wherever it likes"
meant off the edge of the app. A card cannot land anywhere else and cannot be
lost behind anything. It is a card rather than a full-window panel because
filling the window is a Toplevel again in everything but name: nothing left on
screen to say what you were in the middle of. Escape closes it, the body
scrolls when it has to, and save and cancel are pinned outside the scrolling
area so they are reachable on a 768p screen.

Thirteen settings in one column read as a list to get through, so they sit in
three groups, by the question they answer:

- **downloading** - download folder, quality, subtitles, a folder per page,
  parallel downloads, tries per file, and where ffmpeg was found
- **privacy** - tor, private session, proxy, browser cookies, keeping a
  downloads list, the discreet scan, and stripping metadata
- **the window** - language, and whether a double click downloads

Cancel puts back everything you touched, not just the file: every control
writes straight into the value the app is using, so a tick you took back would
otherwise stay on for the rest of the session.

Everything is written to `settings.json` in your profile and reloaded on start,
so your download folder is the one you picked last time. See
[What is remembered](#what-is-remembered) for where exactly, and what is
deliberately left out.

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

UntitledLink now falls back to X's public embed API, the one that powers embedded
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

**"All through tor"** is a checkbox, beside the private session in the main bar
and in settings. It finds Tor on 9050 (the tor service) or 9150 (the copy inside
the Tor Browser) and sends every request through it: page scans, size checks,
previews, downloads, and yt-dlp, which has its own network stack and is handed
the same address. Tor has to be running - the box refuses to stay ticked when
nothing answers on either port, because the alternative is one failed request
per row.

The address used is `socks5h://`, and the `h` is the part that matters: without
it the hostname is resolved here first, so the traffic leaves through Tor while
your provider has already been told which site you are about to visit.

**A circuit per action.** Tor gives a separate circuit to each SOCKS
username/password it is handed, so a random tag is generated when a scan starts
and again when a download starts. Without it every scan and every download in a
session leaves by the same exit node, which then knows one client looked at
this, then that, then fetched the other. Measured over the real network: three
tags, three different exit addresses.

**The yt-dlp update goes out the same way.** It used to run at launch, which
made it the one connection that ignored the proxy - a session meant to go
entirely through Tor began by telling PyPI in the clear that this machine had
opened the app. It now runs on the first scan, through that scan's route.

Ticking tor turns the private session on with it, and leaves it switchable:
hiding the address while the settings file is being written is half a job.

The **proxy box** still takes anything else - a VPN endpoint, a company proxy.
Tor wins over it while the box is ticked, and the circuit tag is only added for
Tor, since nothing else knows what to do with credentials it never asked for.

Measured over the real network, against archive.org: a page scan in 12s, a
3 MB download at 557 KB/s. Wikimedia answered a Tor exit with `403 Too many
requests. Please respect our robot policy`, which is the shape of the day you
should expect - YouTube and Cloudflare do the same, harder.

**It says it is a Tor Browser while tor is on.** A Chrome-on-Windows user
agent arriving from an exit node is a combination nobody else has - it
announces a scraper using Tor, and it is what Wikimedia answered with its
robot policy. Every Tor Browser on the same platform sends the same string,
which is the point: the crowd is the cover. The Accept-Language header goes
with it, since sending Tor Browser's identity and Chrome's language settings
would be a costume with a name tag on it.

The version comes off the installed bundle rather than being invented, and
`TOR_FIREFOX` in the source needs bumping when Tor Browser moves to the next
Firefox ESR - a stale version there is its own small fingerprint.

Off tor the browser string stays, because plenty of sites refuse anything that
does not look like a browser.

**Cookies are the hole none of this closes.** A login says who you are whatever
address it arrives from, so the hint line says `tor (cookies name you)` while
both are on. The private session turns cookies off, and the two belong together.

The app keeps no history, no cache and sends no telemetry. With nothing ticked
the site sees your real IP - no application can change that.

## Testing it

```
python untitledlink.py --selftest
```

Checks the metadata strippers, the thumbnail-upgrade rules, the resolution table
logic, the resume arithmetic, the scan's rules for what counts as the same row,
and the settings round-trip - then builds the real window and drives it: the
filters, the marks, the queue pump, the settings card. Offline, under a second.

By hand, one link per path:

| Paste this | Expect |
|---|---|
| `https://www.youtube.com/watch?v=aqz-KE-bpKQ` | 16 rows, 2160p at ~1.3G down to audio at ~3.7M |
| `https://en.wikipedia.org/wiki/Cat` | ~199 rows, 137 images, top one ~4.4M (the upgraded original, not the 89K thumb) |
| any YouTube playlist | one row per video, capped at 200, each `as set` - the formats are not known without a request per video, so the quality **setting** decides at download time |
| `https://x.com/SpaceX/status/1732824684683784516` | 6 rows, 1080p at ~141M, none needing ffmpeg |
| a tweet with no video | the reason plus a pointer to cookies, not a list of scraped avatars |
| a private or geoblocked video | the real reason on the status line, e.g. `Video unavailable` |

To see resume work: start a large download, kill the app mid-transfer, reopen and
download the same row. It continues from the `.part` file instead of starting over.

Ctrl+A marks everything. Nothing marked means everything **on screen** gets
downloaded. Double-click a row downloads it, if that is switched on.

To see the filters earn themselves: scan the Cat article, open `filters`, tick
`jpg`. To see that hiding is not forgetting: mark a row, then narrow the list
until it is out of sight, and download - the row you marked is the one that
arrives.

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

`build.bat` produces a single ~87MB `UntitledLink.exe` with Python, yt-dlp, ffmpeg
and the certificates inside it. Verified by copying it to an empty folder with
no ffmpeg on PATH and running its self-test: it passes, which includes finding
its own ffmpeg. Nothing needs installing on the machine that runs it.

ffprobe is not bundled. Nothing here calls it, and it is another 100MB.
