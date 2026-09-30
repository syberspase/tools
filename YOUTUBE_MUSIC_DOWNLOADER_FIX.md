# YouTube Music Downloader — 403 Fix, Quality Investigation & Premium Unlock

This document explains three separate problems that were found and fixed in
`youtube_music_downloader.py`, in the order they came up: a hard download
failure, a "why is the quality capped" investigation, and a "how do I get
Premium-only quality" feature addition.

---

## TL;DR

| Problem | Root Cause | Fix |
|---|---|---|
| `HTTP Error 403: Forbidden` on every download | `yt-dlp` was 90+ days out of date; YouTube changed its delivery mechanism | Auto-update `yt-dlp` on every run + retry with an alternate player client on failure |
| Audio capped at ~149kbps (displayed as "177kbps") | That's the real ceiling for an **anonymous** (not logged in) download; the "177kbps" was container overhead (embedded cover art) inflating the size÷duration estimate | N/A — confirmed as expected, not a bug |
| `.opus` files don't preview in WeChat | Opus containers aren't well supported by chat-app media previews | Added an `m4a` output mode |
| Wanted Premium-tier 256–290kbps audio | YouTube gates formats `141`/`774` behind a logged-in Premium account **and** a JS runtime new enough to solve YouTube's signature challenge | Read Firefox's login cookies + install Node 22 as the JS runtime |

---

## Problem 1 — `HTTP Error 403: Forbidden`

### Symptom

```
[info] Downloading 1 format(s): 251
[info] Writing video thumbnail 45 to: ... .webp
ERROR: unable to download video data: HTTP Error 403: Forbidden
```

The `-F` format listing worked fine; only the actual media download failed.

### Root cause

```mermaid
flowchart TD
    a["yt-dlp 2025.12.08 installed<br/>(90+ days old)"] --> b["YouTube periodically changes<br/>its client/URL delivery scheme"]
    b --> c["Old yt-dlp requests a URL<br/>YouTube no longer honors<br/>for that client"]
    c --> d["403 Forbidden on the<br/>media download step"]

    style d fill:#ffcdd2
```

### Fix

```mermaid
flowchart LR
    start(["main()"]) --> upd["update_yt_dlp_if_stale()<br/>pip install -U yt-dlp<br/>(best-effort, non-fatal)"]
    upd --> run["run_yt_dlp(cmd)"]
    run --> a1["Attempt 1:<br/>with Premium auth args"]
    a1 -- fail --> a2["Attempt 2:<br/>anonymous, no auth"]
    a2 -- fail --> a3["Attempt 3:<br/>--extractor-args<br/>player_client=android"]
    a1 -- ok --> done(["done"])
    a2 -- ok --> done
    a3 -- ok --> done
    a3 -- fail --> err(["raise CalledProcessError"])

    style done fill:#c8e6c9
    style err fill:#ffcdd2
```

Updating to `2026.07.04` alone fixed the 403 (newer `yt-dlp` picked an
`android vr` client YouTube wasn't blocking). The retry ladder was added as
a safety net for the next time YouTube changes something.

---

## Problem 2 — "Why is it capped at 177kbps?"

### The reported number was misleading

```mermaid
flowchart TD
    real["Real audio stream<br/>Opus, VBR, ~149kbps<br/>(format 251)"] --> mux["Muxed into .opus container<br/>together with embedded<br/>cover-art PNG"]
    mux --> tool["Media tool computes bitrate as<br/>file_size × 8 ÷ duration"]
    tool --> shown["Reported: 177kbps<br/>(149kbps audio + cover-art bytes<br/>amortized over the song length)"]

    style real fill:#c8e6c9
    style shown fill:#fff9c4
```

Verified with `ffprobe`:

```
[STREAM] codec_name=opus   (no per-stream bitrate; Opus is VBR)
[FORMAT] duration=196.74s  size=4365572  bit_rate=177516   ← includes cover art
```

### Why 149kbps was the real ceiling (at the time)

YouTube and YouTube Music share the same underlying audio encodes. Formats
`141` (256kbps AAC) and `774` (290kbps Opus) exist, but are only served to
**authenticated Premium accounts**. Everyone else — logged out, or logged in
without Premium — is capped at format `251` (149kbps Opus) / `140`
(130kbps AAC).

```mermaid
flowchart LR
    req["yt-dlp request<br/>(no cookies)"] --> yt["YouTube player API"]
    yt --> anon["Anonymous format ladder<br/>139 → 249 → 140 → 251<br/>(max 149kbps)"]

    req2["yt-dlp request<br/>(Premium cookies)"] --> yt2["YouTube player API"]
    yt2 --> prem["Premium format ladder<br/>… → 141 (256k AAC) → 774 (290k Opus)"]

    style anon fill:#fff9c4
    style prem fill:#c8e6c9
```

This wasn't a bug — it was confirmed as the actual product limitation, which
led directly into Problem 4.

---

## Problem 3 — `.opus` doesn't preview in WeChat

Opus-in-.opus isn't reliably playable/previewable inside chat apps. Added a
dedicated `m4a` output mode that prefers a **native AAC source** so the file
is remuxed, not re-encoded:

```mermaid
flowchart TD
    pick["-f 'bestaudio(acodec^=mp4a)/bestaudio'"] --> has_aac{"Is the best-available<br/>source already AAC?<br/>(e.g. itag 141)"}
    has_aac -- yes --> remux["Remux straight into .m4a<br/>(zero quality loss, no re-encode)"]
    has_aac -- no --> transcode["Decode Opus → encode AAC 256k<br/>(one lossy transcode, unavoidable)"]

    style remux fill:#c8e6c9
    style transcode fill:#fff9c4
```

Confirmed via yt-dlp's own log: *"Not converting audio ...; file is already
in target format m4a"* — i.e. it picked format `141` directly and just
remuxed it.

---

## Problem 4 — Unlocking Premium-tier audio (256–290kbps)

This was the deepest rabbit hole. Two independent requirements had to be met
simultaneously:

```mermaid
flowchart TD
    goal(["Goal: formats 141 / 774<br/>visible in yt-dlp"])

    goal --> req1["Requirement A:<br/>Prove the account is Premium"]
    goal --> req2["Requirement B:<br/>Solve YouTube's JS signature<br/>+ n-parameter challenge"]

    req1 --> cookies["--cookies-from-browser firefox<br/>reads ~/.mozilla/firefox/.../cookies.sqlite<br/>directly (no manual export)"]
    cookies --> detect["yt-dlp: 'Detected YouTube<br/>Premium subscription'"]

    req2 --> runtime["Need a JS runtime yt-dlp supports:<br/>Deno (not installed) or Node ≥ 22<br/>(system had only Node 20 — unsupported)"]
    runtime --> node22["Installed Node 22.14.0<br/>into ~/.nvm/versions/node/v22.14.0/"]
    node22 --> ejs["--js-runtimes node:PATH<br/>--remote-components ejs:github<br/>downloads yt-dlp's official<br/>challenge-solver script on demand"]

    detect --> unlocked
    ejs --> unlocked(["Formats 141 (258k AAC) &<br/>774 (290k Opus) appear"])

    style unlocked fill:#c8e6c9
```

### Where the "token" actually came from (no PO Token was used)

A common point of confusion: YouTube also has a separate anti-abuse
mechanism called a **PO Token**. It was *not* needed here — verbose logs
confirm it was skipped entirely because Premium accounts are exempted from
the PO Token requirement for media (GVS) requests:

```
[debug] [youtube] Found YouTube account cookies
[debug] [youtube] [pot] PO Token Providers: none
[debug] [youtube] Detected YouTube Premium subscription
```

```mermaid
sequenceDiagram
    participant FF as Firefox cookies.sqlite<br/>(on disk)
    participant YTDLP as yt-dlp
    participant YT as YouTube player API

    YTDLP->>FF: read cookies (SID/APISID/SAPISID/...)
    FF-->>YTDLP: 1220 cookies
    YTDLP->>YT: player request + account cookies
    YT-->>YTDLP: "account is Premium" → PO Token requirement waived
    YT-->>YTDLP: player response includes formats 141 / 774<br/>(URLs still signature-obfuscated)
    YTDLP->>YTDLP: solve signature/n challenge<br/>via Node 22 + yt-dlp-ejs script
    YTDLP->>YT: GET deobfuscated media URL
    YT-->>YTDLP: 200 OK, audio bytes
```

### Installation snags along the way

Two network-dependent installs stalled in this environment (outbound
bandwidth to `deno.land` / `nodejs.org` was ~100KB/s) and had to be worked
around:

```mermaid
flowchart LR
    d1["curl deno.land/install.sh<br/>(piped install)"] -->|hung, no progress output| killed1["killed after ~4 min"]
    d2["nvm install 22<br/>(nvm's own downloader)"] -->|hung similarly| killed2["killed after ~8 min"]
    d3["curl -C - nodejs.org tarball<br/>directly, with resume support"] -->|completed in ~10 min<br/>at ~100KB/s| ok["node-v22.14.0-linux-x64.tar.xz"]
    ok --> install["Manually extracted into<br/>~/.nvm/versions/node/v22.14.0/<br/>+ nvm alias default 22.14.0"]

    style killed1 fill:#ffcdd2
    style killed2 fill:#ffcdd2
    style ok fill:#c8e6c9
```

---

## Final Architecture

```mermaid
flowchart TD
    main(["main(url, format, output_dir)"]) --> upd["update_yt_dlp_if_stale()"]
    upd --> disp{"format arg"}

    disp -->|best, default| best["download_music()<br/>-f bestaudio (implicit)<br/>--audio-format best"]
    disp -->|m4a| m4a["download_music_as_m4a()<br/>-f 'bestaudio(acodec^=mp4a)/bestaudio'<br/>--audio-format m4a"]
    disp -->|mp3| mp3["download_music_as_mp3()<br/>--audio-format mp3 --audio-quality 320K"]
    disp -->|flac| flac["download_music_as_flac()<br/>--audio-format flac"]

    best --> ryd["run_yt_dlp(cmd)"]
    m4a --> ryd
    mp3 --> ryd
    flac --> ryd

    ryd --> auth["get_auth_args()"]
    auth --> chk{"Node 22 found at<br/>~/.nvm/versions/node/v22.14.0?"}
    chk -- yes --> withauth["cmd + --cookies-from-browser firefox<br/>+ --js-runtimes node:PATH<br/>+ --remote-components ejs:github"]
    chk -- no --> noauth["cmd unchanged<br/>(anonymous, ~149kbps ceiling)"]

    withauth --> attempt1["Attempt 1"]
    noauth --> attempt1
    attempt1 -- fail --> attempt2["Attempt 2: no auth"]
    attempt2 -- fail --> attempt3["Attempt 3: android client"]

    attempt1 -- ok --> out(["Audio file in output_dir<br/>with embedded cover + metadata"])
    attempt2 -- ok --> out
    attempt3 -- ok --> out

    style out fill:#c8e6c9
```

---

## Verified Results

| Mode | Command | Format picked | Real bitrate | Notes |
|---|---|---|---|---|
| `best` (default), no auth | *(before fix)* | 251 | 149kbps Opus | Anonymous ceiling |
| `best` (default), with Premium auth | `python3 youtube_music_downloader.py <url>` | 774 | **290kbps Opus** | Premium-only |
| `m4a`, with Premium auth | `python3 youtube_music_downloader.py <url> m4a` | 141 | **256kbps AAC** | Native remux, no re-encode |

---

## Security Considerations — "Isn't reading my browser cookies unsafe?"

Fair question, worth being precise about. Short version: **nothing left this
machine**, but the mechanism deserves scrutiny.

### What `--cookies-from-browser firefox` actually does — and doesn't do

```mermaid
flowchart TD
    ytdlp["yt-dlp process<br/>(runs locally, as your OS user)"] -->|reads| db["~/.mozilla/firefox/*/cookies.sqlite"]
    db -->|cookie values stay in process memory| ytdlp
    ytdlp -->|builds HTTP request with cookies| yt["youtube.com"]

    note1["Never printed: cookie values<br/>(only counts, e.g. '1220 cookies extracted')"]
    note2["Never sent to: Cursor, this agent,<br/>or any third-party server"]

    style yt fill:#c8e6c9
    style note1 fill:#fff9c4
    style note2 fill:#fff9c4
```

This is a standard, documented yt-dlp feature — the same mechanism any
"login with browser session" tool uses. It's equivalent to opening YouTube
in that same browser: your existing session authenticates the request.

### The real (pre-existing) exposure

The underlying fact that makes this feel exposed isn't something this setup
introduced — it's how Firefox stores cookies on Linux:

```mermaid
flowchart LR
    fact["Firefox on Linux stores cookies.sqlite<br/>as a plain, unencrypted SQLite file"] --> access["Any process running as your<br/>Linux user (lius) can already<br/>open and read it directly"]
    access --> implication["True regardless of yt-dlp —<br/>a rogue npm package, browser<br/>extension, or malware has the<br/>same access today"]

    style fact fill:#fff9c4
    style implication fill:#ffcdd2
```

Chrome's OS-keyring encryption looks safer, but the decryption key is
itself readable by the same-user processes that could decrypt it — so it's
not a materially higher bar in practice.

### What's actually at stake

The cookie is a **full Google-account session** (`SID`/`APISID`/`SAPISID`
etc.), not a YouTube-scoped credential. If this machine or one of its
dependencies (`yt-dlp`, any pip/npm package) were ever compromised, whoever
reads that file could impersonate you across Google services (Gmail,
Drive, etc.), not just YouTube.

### Mitigation options considered

| Option | Mechanism | Reduces | Doesn't reduce | Cost |
|---|---|---|---|---|
| **A — Scoped `cookies.txt`** | Export once via `--cookies-from-browser firefox --cookies cookies.txt`, filtered to `youtube.com`/`google` domains; script reads that static file instead of the live browser DB | Blast radius per run (script no longer touches the *entire* cookie jar, just a YouTube/Google-scoped snapshot); no dependency on Firefox being closed/unlocked | Still a full Google-account session inside that file; expires with the cookie's normal lifetime, requiring re-export | Low — one-time export, occasional re-export |
| **B — Dedicated Firefox profile** | Create a separate Firefox profile that *only* logs into the Premium account; script points at that profile's cookie DB instead of the main one | Keeps the script from ever touching cookies for your primary browsing (banking, email, social, etc.) | If it's the *same* Google account as your main profile, the account-level blast radius is unchanged — only the browsing-profile isolation improves | Medium — profile setup + occasional re-login |
| **C — Status quo** | Keep reading the live main-profile cookie DB on every run | — | Full-profile exposure on every script run | None |

No change has been made yet — this section documents the discussion and
options for future reference. See chat history for the decision once made.

---

## Usage

```bash
# Highest quality available (Opus, .opus) — default
python3 youtube_music_downloader.py "<youtube/music.youtube URL>"

# WeChat/mobile-friendly AAC container
python3 youtube_music_downloader.py "<url>" m4a

# MP3 @ 320kbps
python3 youtube_music_downloader.py "<url>" mp3

# Optional third arg: output directory
python3 youtube_music_downloader.py "<url>" m4a /path/to/music
```

### Requirements for Premium-tier quality

1. Stay logged into the Premium account in **Firefox** (cookies are read
   live from `~/.mozilla/firefox/*/cookies.sqlite` on every run — no manual
   export needed).
2. Node 22 must remain installed at
   `~/.nvm/versions/node/v22.14.0/bin/node` (the path
   `get_auth_args()` checks for). If it's ever removed, the script silently
   falls back to anonymous 149kbps downloads rather than failing.
