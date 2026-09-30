"""
Video streaming server for Firefox/Chrome with Chromecast support.
"""
import os, json, queue, socket, threading, magic, subprocess, struct
from datetime import datetime
from flask import Flask, render_template_string, abort, Response, request, jsonify
from urllib.parse import quote
import re as _re
import time as _time

app = Flask(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
VIDEO_ROOT = '/media/lius/shep-protected/Videos/movies'
HTTP_PORT  = 8080
mime       = magic.Magic(mime=True)

# ── Jinja2 filter ─────────────────────────────────────────────────────────────
@app.template_filter('format_date')
def format_date(timestamp):
    """Convert Unix timestamp to readable date string."""
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M')

# ── LAN IP helper ─────────────────────────────────────────────────────────────
def get_lan_ip(target_host=None):
    """Return the local LAN IP that can reach target_host (e.g. the Chromecast).
    Falls back to the machine's primary LAN IP if target is not given."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((target_host or '8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return socket.gethostbyname(socket.gethostname())

# ── Cast devices cache ────────────────────────────────────────────────────────
# _cast_devices: name -> (host, port)
_cast_devices = {}
_cast_lock    = threading.Lock()

# ── Persistent asyncio event loop (needed by zeroconf / pychromecast) ─────────
import asyncio
_bg_loop        = asyncio.new_event_loop()
_bg_loop_thread = threading.Thread(target=_bg_loop.run_forever, daemon=True, name='asyncio-bg')
_bg_loop_thread.start()

from zeroconf import Zeroconf as _Zeroconf
async def _make_zconf():
    return _Zeroconf()
_zconf = asyncio.run_coroutine_threadsafe(_make_zconf(), _bg_loop).result(timeout=10)

# ── Active Chromecast connections ─────────────────────────────────────────────
_active_cast      = {}   # device_name -> Chromecast object
_active_cast_lock = threading.Lock()

# ── Cast playback state (shared across all connected browsers via SSE) ─────────
_cast_state = {
    'active':       False,
    'device':       '',
    'player_state': 'IDLE',
    'current_time': 0.0,
    'duration':     0.0,
    'url':          '',
    'filename':     '',
    'start_time':   0.0,
    'ever_played':  False,
}
_cast_state_lock = threading.Lock()

# ── SSE broadcast infrastructure ──────────────────────────────────────────────
_sse_queues: list[queue.Queue] = []
_sse_queues_lock = threading.Lock()

SUPPORTED_PATTERN = _re.compile(r'video/mp4')

# ── File utilities ────────────────────────────────────────────────────────────
def is_browser_playable(filepath):
    try:
        m = mime.from_file(filepath)
        if m != 'video/mp4':
            return False
        return True
    except Exception:
        return False

def list_videos_recursive():
    videos = []
    if not os.path.isdir(VIDEO_ROOT):
        return videos
    for root, dirs, files in os.walk(VIDEO_ROOT):
        dirs.sort(key=str.lower)
        for file in sorted(files, key=str.lower):
            if file.lower().endswith('.mp4'):
                fullpath = os.path.join(root, file)
                rel_path = os.path.relpath(fullpath, VIDEO_ROOT)
                if is_browser_playable(fullpath):
                    mtime = os.path.getmtime(fullpath)
                    videos.append({'path': rel_path, 'mtime': mtime})
                else:
                    print(f'Skipping (not browser-playable): {rel_path}')
    return videos

def get_top_level_folders():
    """Return sorted list of first-level subfolder names under VIDEO_ROOT."""
    if not os.path.isdir(VIDEO_ROOT):
        return []
    return sorted(
        [d for d in os.listdir(VIDEO_ROOT)
         if os.path.isdir(os.path.join(VIDEO_ROOT, d))],
        key=str.lower
    )

def build_tree():
    tree = {}
    videos = list_videos_recursive()
    for video in videos:
        parts   = video['path'].split(os.sep)
        current = tree
        for part in parts[:-1]:
            if part not in current:
                current[part] = {'_type': 'folder', '_children': {}}
            current = current[part]['_children']
        current[parts[-1]] = {'_type': 'file', 'path': video['path'], 'mtime': video['mtime']}
    return tree

# ── Faststart / Chromecast-compat cache ───────────────────────────────────────
# Three MP4 quirks break Chromecast playback. We transparently fix all of
# them by producing a remuxed copy on first request and serving the cache
# thereafter.
#
#   1. moov atom after mdat → slow startup, range-request thrash on Chromecast.
#
#   2. Non-trivial edit list (elst) on the video track — typically an empty
#      edit (media_time=-1) used to delay video so it lines up with audio.
#      Standards-compliant players honor the edit list; the Chromecast MP4
#      demuxer ignores edit lists entirely, so the video's natural B-frame
#      priming offset (typically 80–125 ms) shifts and audio leads video.
#
#   3. Variable audio packet durations in stts. Many sources encode "audio
#      gaps" by giving certain AAC frames very long stts durations (e.g.
#      4500 ticks instead of the usual 1024) instead of writing actual silent
#      AAC frames. Spec-compliant players honor stts and pad/hold to fill
#      the gap; Chromecast does *not* — it just plays the next 1024 decoded
#      samples immediately, so the audio runs ~0.6 % too fast and *drifts*
#      ahead of video over time (≈ 80 ms drift per "fat" packet, ≈ 700 ms
#      after 2 minutes, ≈ 15 s by the end of a typical 44-minute episode).
#
# Pipeline (stream-copy throughout — no re-encode of any original sample):
#   • Probe the source for video first-PTS-in-track-time (= the B-frame
#     priming gap Chromecast sees), audio sample rate / channel count, and
#     the full list of audio packet stts durations.
#   • Compute a "silence injection plan":
#       – `prefix_frames` AAC frames at the very start, sized to cover the
#         video CTS lead so the first real audio sample lines up with the
#         first decoded video frame.
#       – For each original audio packet, run a cumulative-deficit counter
#         (`target += stts_duration; actual += 1024`) and inject
#         `floor(deficit/1024)` silence frames whenever the deficit reaches
#         a full frame. This guarantees audio total duration matches the
#         stts schedule within a single AAC frame (≤ 23 ms) over the whole
#         stream — and crucially, the injected silence is *real* AAC data
#         that Chromecast cannot skip.
#   • Extract the original audio to a raw ADTS stream with `-c copy` (no
#     decoder/encoder anywhere — every original sample stays bit-identical).
#     Generate one canonical AAC-LC silence frame in matching format, then
#     splice the silence into the ADTS stream at the planned positions.
#     Convert the resulting ADTS back to M4A with `-c copy`, then mux video
#     + new audio with `+faststart`, `-use_editlist 0`, and
#     `-avoid_negative_ts make_zero`.
#   • If the file has no audio, non-AAC audio, or no drift to fix, fall back
#     to a plain stream-copy remux (still fixes #1 and #2).
#
# Earlier attempts that we no longer use — for posterity:
#   • `qt-faststart` only rewrote the moov position; the elst was preserved,
#     so Chromecast continued to ignore it and audio led video.
#   • A `setts=pts=PTS-STARTPTS:dts=DTS-STARTDTS` BSF forced video to PTS=0
#     but shifted PTS and DTS by different amounts, dropping every frame's
#     CTS by the I-frame's CTS. The MP4 muxer (even with
#     `+negative_cts_offsets`) clamped resulting negative CTS values to 0,
#     scrambling B-frame display order → continuous stutter.
#   • `-af adelay=<N>:all=1` with `-c:a aac` re-encode prepended silence but
#     ffmpeg's native AAC encoder dropped trailing samples when the source's
#     declared duration exceeded its actual sample data, losing ~15 s of
#     audio at the end and corrupting mid-file seek targets.
#   • Plain concat-demuxer silence prefix (without drift compensation)
#     fixed only the initial offset — drift via fat stts packets caused the
#     audio to creep ahead of video over a couple of minutes.
_FASTSTART_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.faststart')
os.makedirs(_FASTSTART_DIR, exist_ok=True)
_faststart_lock = threading.Lock()

# Bumped whenever the remux pipeline changes. Old caches are wiped on startup
# so they get regenerated by the new logic. v6: ADTS bitstream surgery with
# cumulative-deficit silence injection (fixes the "audio drifts ahead after
# a couple of minutes" drift that v5's silence prefix couldn't address).
_CACHE_VERSION       = '6'
_CACHE_VERSION_FILE  = os.path.join(_FASTSTART_DIR, '.cache_version')

def _migrate_faststart_cache():
    """Wipe cached files produced by an older remux pipeline."""
    try:
        with open(_CACHE_VERSION_FILE) as f:
            if f.read().strip() == _CACHE_VERSION:
                return
    except Exception:
        pass
    import shutil
    for name in os.listdir(_FASTSTART_DIR):
        if name == os.path.basename(_CACHE_VERSION_FILE):
            continue
        full = os.path.join(_FASTSTART_DIR, name)
        try:
            shutil.rmtree(full) if os.path.isdir(full) else os.remove(full)
        except Exception:
            pass
    try:
        with open(_CACHE_VERSION_FILE, 'w') as f:
            f.write(_CACHE_VERSION)
        print(f'[Faststart] Cache migrated to v{_CACHE_VERSION} '
              f'(Chromecast A/V sync fix)')
    except Exception:
        pass

_migrate_faststart_cache()

# In-memory memo so we only scan each source file once.
# filepath -> (source_mtime, needs_remux: bool)
_remux_decision: dict[str, tuple[float, bool]] = {}
_remux_decision_lock = threading.Lock()

def _scan_mp4_for_remux_need(filepath):
    """Single-pass scan of an MP4 file. Returns True if the file needs remux:
       • moov atom comes after mdat, OR
       • any track has an edit list with an empty edit (media_time == -1) or a
         non-zero positive media_time (both cause Chromecast A/V desync since
         it ignores edit lists)."""
    try:
        with open(filepath, 'rb') as f:
            file_size = os.fstat(f.fileno()).st_size
            pos        = 0
            found_mdat = False
            while pos < file_size:
                f.seek(pos)
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                sz = struct.unpack('>I', hdr[:4])[0]
                nm = hdr[4:8]
                hdr_size = 8
                if sz == 1:
                    ext = f.read(8)
                    sz  = struct.unpack('>Q', ext)[0]
                    hdr_size = 16
                if sz < hdr_size:
                    break
                if nm == b'mdat':
                    found_mdat = True
                elif nm == b'moov':
                    if found_mdat:
                        return True  # moov-at-end
                    payload = f.read(sz - hdr_size)
                    return _moov_payload_has_problem_elst(payload)
                pos += sz
    except Exception:
        pass
    return False

def _moov_payload_has_problem_elst(payload):
    """Scan a moov payload for an elst atom whose entries would cause
    Chromecast A/V desync. The elst FourCC inside a valid moov only ever
    appears as an atom header, so a literal byte search is reliable enough
    and avoids the cost of fully walking the atom hierarchy."""
    n   = len(payload)
    i   = 0
    while i + 16 <= n:
        if payload[i:i+4] == b'elst':
            try:
                version = payload[i+4]
                count   = struct.unpack('>I', payload[i+8:i+12])[0]
                if 0 < count <= 1024:
                    p = i + 12
                    for _ in range(count):
                        if version == 1:
                            if p + 20 > n: break
                            media_time = struct.unpack('>q', payload[p+8:p+16])[0]
                            p += 20
                        else:
                            if p + 12 > n: break
                            media_time = struct.unpack('>i', payload[p+4:p+8])[0]
                            p += 12
                        if media_time == -1 or media_time > 0:
                            return True
            except Exception:
                pass
        i += 1
    return False

def _needs_remux(filepath):
    """Memoized wrapper around _scan_mp4_for_remux_need keyed on (path, mtime)."""
    try:
        mtime = os.path.getmtime(filepath)
    except OSError:
        return False
    with _remux_decision_lock:
        cached = _remux_decision.get(filepath)
        if cached and cached[0] == mtime:
            return cached[1]
    decision = _scan_mp4_for_remux_need(filepath)
    with _remux_decision_lock:
        _remux_decision[filepath] = (mtime, decision)
    return decision

def _run_ffmpeg(cmd, *, timeout):
    """Run ffmpeg/ffprobe and raise CalledProcessError with captured stderr on failure."""
    return subprocess.run(cmd, check=True, timeout=timeout, capture_output=True)


def _adts_frame_length(buf, off):
    """Return ADTS frame length at `off`, or -1 if header invalid."""
    if off + 7 > len(buf):
        return -1
    if buf[off] != 0xFF or (buf[off + 1] & 0xF0) != 0xF0:
        return -1
    return ((buf[off + 3] & 0x03) << 11) | (buf[off + 4] << 3) | (buf[off + 5] >> 5)


def _probe_audio_drift_plan(filepath):
    """Return a dict with the silence-injection plan for `filepath`, or
    None if no correction is needed (no audio, no video, non-AAC audio,
    or all timings already aligned).

    Plan keys:
        sample_rate     int
        channels        int
        prefix_frames   int                       — silence frames to prepend
        inject_after    list[(frame_idx, count)]  — silence to inject after
                                                    given original-audio
                                                    frame index (sorted)
        n_orig_frames   int
    """
    try:
        v = _run_ffmpeg(
            ['ffprobe', '-v', 'error', '-ignore_editlist', '1',
             '-select_streams', 'v:0',
             '-show_entries', 'stream=start_time',
             '-of', 'default=nw=1:nk=1', filepath],
            timeout=30,
        )
        v_start = float((v.stdout or b'').decode().strip() or 0.0)
    except (subprocess.CalledProcessError, ValueError, subprocess.TimeoutExpired):
        return None

    try:
        a = _run_ffmpeg(
            ['ffprobe', '-v', 'error',
             '-select_streams', 'a:0',
             '-show_entries', 'stream=codec_name,sample_rate,channels',
             '-of', 'default=nw=1:nk=1', filepath],
            timeout=30,
        )
        lines = (a.stdout or b'').decode().strip().splitlines()
        if len(lines) < 3 or lines[0].strip().lower() != 'aac':
            return None      # only AAC is safe for ADTS bitstream surgery
        sample_rate = int(lines[1])
        channels    = int(lines[2])
    except (subprocess.CalledProcessError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None

    try:
        d = _run_ffmpeg(
            ['ffprobe', '-v', 'error', '-ignore_editlist', '1',
             '-select_streams', 'a:0',
             '-show_entries', 'packet=duration',
             '-of', 'csv=p=0', filepath],
            timeout=120,
        )
        durations = [int(x) for x in (d.stdout or b'').decode().split() if x.strip()]
    except (subprocess.CalledProcessError, ValueError, subprocess.TimeoutExpired):
        return None
    if not durations:
        return None

    prefix_frames = max(0, round(v_start * sample_rate / 1024)) if v_start > 0.005 else 0

    # Cumulative-deficit injection: target advances by stts duration, actual
    # advances by 1024 (one decoded AAC frame). Inject silence whenever the
    # deficit reaches a full frame so audio total duration matches the
    # source's stts schedule within ≤ 1 frame (≈ 23 ms) over the whole stream.
    target, actual = 0, 0
    inject_after = []
    for idx, dur in enumerate(durations):
        target += dur
        actual += 1024
        deficit = target - actual
        n = deficit // 1024
        if n > 0:
            inject_after.append((idx, n))
            actual += n * 1024

    if prefix_frames == 0 and not inject_after:
        return None         # nothing to fix

    return {
        'sample_rate'  : sample_rate,
        'channels'     : channels,
        'prefix_frames': prefix_frames,
        'inject_after' : inject_after,
        'n_orig_frames': len(durations),
    }


def _build_drift_corrected_audio_m4a(filepath, plan, work_dir):
    """Build a drift-corrected audio M4A from `filepath` according to
    `plan`, write it inside `work_dir`, and return the path.

    The original AAC stream is stream-copied throughout; only the silence
    frames spliced in (start prefix + per-stts-gap injections) are encoded
    fresh, and they are tiny (~13 bytes each) and identical to one another."""
    sample_rate    = plan['sample_rate']
    channels       = plan['channels']
    prefix_frames  = plan['prefix_frames']
    inject_after   = dict(plan['inject_after'])
    ch_layout      = ('mono'   if channels == 1 else
                      'stereo' if channels == 2 else
                      f'{channels}c')

    orig_adts   = os.path.join(work_dir, 'orig.aac')
    silence_src = os.path.join(work_dir, 'silence.aac')
    out_adts    = os.path.join(work_dir, 'fixed.aac')
    out_m4a     = os.path.join(work_dir, 'fixed_audio.m4a')

    # 1. Original audio → ADTS (stream copy; no decode, no encode).
    _run_ffmpeg(
        ['ffmpeg', '-y', '-v', 'error',
         '-i', filepath, '-map', '0:a:0', '-c', 'copy',
         '-f', 'adts', orig_adts],
        timeout=300,
    )

    # 2. Generate ~20 silence frames; we'll pick a middle one as the canonical
    #    silence ADTS frame to skip past encoder priming/padding artifacts.
    _run_ffmpeg(
        ['ffmpeg', '-y', '-v', 'error',
         '-f', 'lavfi', '-i', f'anullsrc=cl={ch_layout}:r={sample_rate}',
         '-c:a', 'aac', '-profile:a', 'aac_low',
         '-ar', str(sample_rate), '-ac', str(channels),
         '-frames:a', '20', '-f', 'adts', silence_src],
        timeout=60,
    )
    with open(silence_src, 'rb') as f:
        sbuf = f.read()
    silence_frame = None
    off, idx = 0, 0
    while off < len(sbuf):
        flen = _adts_frame_length(sbuf, off)
        if flen <= 0:
            break
        if idx == 10:
            silence_frame = sbuf[off:off + flen]
            break
        off += flen
        idx += 1
    if not silence_frame:
        raise RuntimeError('failed to extract canonical silence ADTS frame')

    # 3. Build output ADTS: prefix silence, then each original frame followed
    #    by any per-frame injection silence.
    with open(orig_adts, 'rb') as f:
        obuf = f.read()
    chunks = [silence_frame * prefix_frames] if prefix_frames else []
    off, idx = 0, 0
    while off < len(obuf):
        flen = _adts_frame_length(obuf, off)
        if flen <= 0:
            break
        chunks.append(obuf[off:off + flen])
        n = inject_after.get(idx, 0)
        if n > 0:
            chunks.append(silence_frame * n)
        off += flen
        idx += 1
    with open(out_adts, 'wb') as f:
        f.write(b''.join(chunks))

    # 4. ADTS → M4A (stream copy).
    _run_ffmpeg(
        ['ffmpeg', '-y', '-v', 'error',
         '-i', out_adts, '-c', 'copy',
         '-movflags', '+faststart', out_m4a],
        timeout=300,
    )
    return out_m4a


def _get_faststart_path(filepath):
    """Return a Chromecast-friendly version of `filepath`: moov atom at the
    front, no edit list, audio rebuilt from the original AAC frames with
    silence frames spliced in (a) at the start to compensate for the
    video's B-frame priming gap and (b) at every stts-gap point so the
    audio plays at the correct pace without drifting on Chromecast.
    Stream-copy only — no original A/V sample is ever re-encoded — and
    cached after the first build."""
    if not _needs_remux(filepath):
        return filepath

    rel    = os.path.relpath(filepath, VIDEO_ROOT)
    cached = os.path.join(_FASTSTART_DIR, rel)

    if os.path.isfile(cached) and os.path.getmtime(cached) >= os.path.getmtime(filepath):
        return cached

    os.makedirs(os.path.dirname(cached), exist_ok=True)
    plan = _probe_audio_drift_plan(filepath)

    try:
        if plan is None:
            # No audio, non-AAC audio, or no audio rework needed — just
            # do a plain stream-copy remux to fix faststart / edit-list.
            _run_ffmpeg(
                ['ffmpeg', '-y', '-v', 'error',
                 '-i', filepath,
                 '-map', '0:v', '-map', '0:a?',
                 '-c', 'copy',
                 '-movflags', '+faststart',
                 '-use_editlist', '0',
                 '-muxdelay', '0', '-muxpreload', '0',
                 '-avoid_negative_ts', 'make_zero',
                 cached],
                timeout=600,
            )
            print(f'[Faststart] Remuxed {rel} (stream-copy, no audio rework needed)')
            return cached

        import tempfile
        with tempfile.TemporaryDirectory(prefix='cccast-', dir=_FASTSTART_DIR) as tmp:
            new_audio = _build_drift_corrected_audio_m4a(filepath, plan, tmp)
            _run_ffmpeg(
                ['ffmpeg', '-y', '-v', 'error',
                 '-i', filepath, '-i', new_audio,
                 '-map', '0:v:0', '-map', '1:a:0',
                 '-c', 'copy',
                 '-movflags', '+faststart',
                 '-use_editlist', '0',
                 '-muxdelay', '0', '-muxpreload', '0',
                 '-avoid_negative_ts', 'make_zero',
                 cached],
                timeout=600,
            )

        n_inject  = sum(n for _, n in plan['inject_after'])
        prefix_ms = plan['prefix_frames'] * 1024 * 1000.0 / plan['sample_rate']
        inject_ms = n_inject               * 1024 * 1000.0 / plan['sample_rate']
        print(f'[Faststart] Remuxed {rel} '
              f'(prefix {plan["prefix_frames"]} frames ≈ {prefix_ms:.1f} ms, '
              f'drift-fix {n_inject} frames at {len(plan["inject_after"])} positions ≈ {inject_ms:.1f} ms)')
        return cached

    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b'').decode(errors='replace').strip()
        print(f'[Faststart] ffmpeg failed for {rel}: {stderr[-500:]}')
        try:
            if os.path.isfile(cached):
                os.remove(cached)
        except Exception:
            pass
        return filepath
    except Exception as e:
        print(f'[Faststart] Failed {rel}: {e}')
        try:
            if os.path.isfile(cached):
                os.remove(cached)
        except Exception:
            pass
        return filepath

# ── HTML template ─────────────────────────────────────────────────────────────
INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Video Library</title>
  <style>
    body {font-family: Arial, sans-serif; margin: 2rem; margin-top: 4.5rem; background:#f9f9f9; color:#333;}
    h1 {color:#222;}
    /* ── Language nav bar ── */
    .lang-bar {
      position: fixed; top: 0; left: 0; right: 0; z-index: 9000;
      background: #1a1a2e; color: #eee;
      display: flex; align-items: center; flex-wrap: wrap; gap: 0.3rem;
      padding: 0.5rem 1rem; box-shadow: 0 2px 8px rgba(0,0,0,0.4);
    }
    .lang-bar .lang-home {
      font-size: 1.2rem; color: #fff; text-decoration: none; margin-right: 0.5rem; flex-shrink: 0;
    }
    .lang-bar .lang-home:hover {color: #4fc3f7;}
    .lang-bar .lang-divider {color: #555; margin-right: 0.5rem; flex-shrink: 0;}
    .lang-bar a.lang-tab {
      padding: 5px 14px; border-radius: 20px;
      background: #2e2e4a; color: #ccc;
      text-decoration: none; font-size: 0.9rem; white-space: nowrap;
      border: 1px solid transparent; transition: background 0.15s, color 0.15s;
    }
    .lang-bar a.lang-tab:hover {background: #3a3a60; color: #fff;}
    .lang-bar a.lang-tab.active {
      background: #4fc3f7; color: #1a1a2e; font-weight: bold; border-color: #4fc3f7;
    }
    .tree {line-height: 1.6;}
    .folder > a {color: #0066cc; text-decoration: none; font-weight: bold;}
    .folder > a:hover {text-decoration: underline;}
    .file {display: flex; align-items: center; margin-bottom: 0.3rem;}
    .file > a {color: #d14; text-decoration: none; flex: 1;}
    .file > a:hover {text-decoration: underline;}
    .file-date {color: #666; font-size: 0.85rem; margin-left: 1rem; min-width: 140px;}
    .add-to-playlist {margin-left: 0.5rem; padding: 2px 8px; background: #28a745; color: white; border: none; border-radius: 3px; cursor: pointer; font-size: 0.8rem;}
    .add-to-playlist:hover {background: #218838;}
    .in-playlist {background: #6c757d !important;}
    .indent {margin-left: 1.5rem;}
    .sort-controls {margin-bottom: 1rem; padding: 0.5rem; background: #fff; border: 1px solid #ddd; border-radius: 4px;}
    .sort-controls label {margin-right: 1rem; font-weight: bold;}
    .sort-controls button {padding: 5px 10px; margin-right: 5px; cursor: pointer; background: #0066cc; color: white; border: none; border-radius: 3px;}
    .sort-controls button:hover {background: #0052a3;}
    .sort-controls button.active {background: #d14;}
    /* ── URL cast bar ── */
    .url-cast-bar {display:flex; gap:0.5rem; align-items:center; margin-bottom:1rem;
      padding:0.6rem 0.8rem; background:#fff; border:1px solid #ddd; border-radius:4px;}
    .url-cast-bar input {flex:1; padding:6px 10px; border:1px solid #bbb; border-radius:3px;
      font-size:0.9rem; min-width:0;}
    .url-cast-bar button {padding:6px 14px; background:#0066cc; color:#fff; border:none;
      border-radius:3px; cursor:pointer; white-space:nowrap; font-size:0.9rem;}
    .url-cast-bar button:hover {background:#0052a3;}
    .url-cast-bar button:disabled {background:#999; cursor:not-allowed;}
    video {width:100%; max-width:900px; margin-top:2rem; background:#000; border:1px solid #ccc;}
    .video-container {position: relative; display: inline-block; width: 100%; max-width: 900px;}
    .cast-button {position: absolute; bottom: 60px; right: 60px; background: rgba(0,0,0,0.7); color: white; border: 2px solid white; padding: 10px 15px; cursor: pointer; border-radius: 4px; font-size: 20px; z-index: 1000;}
    .cast-button:hover {background: rgba(255,255,255,0.2); transform: scale(1.1);}
    .cast-button:active {background: rgba(255,255,255,0.3);}
    .player-controls {display: flex; gap: 0.5rem; margin-top: 1rem; flex-wrap: wrap;}
    .player-controls button {padding: 10px 15px; background: #0066cc; color: white; border: none; cursor: pointer; border-radius: 4px; font-size: 0.9rem; display: flex; align-items: center; gap: 0.5rem;}
    .player-controls button:hover {background: #0052a3;}
    .player-controls button:active {background: #003d7a;}
    .player-controls .danger {background: #dc3545;}
    .player-controls .danger:hover {background: #c82333;}
    .speed-control {display: flex; gap: 0.3rem;}
    .speed-control button {padding: 8px 12px; font-size: 0.85rem;}
    .speed-control button.active {background: #28a745;}
    .back {margin-bottom: 1rem;}
    .player-section {display: flex; gap: 1rem; margin-bottom: 2rem; align-items: flex-start;}
    .video-wrapper {flex: 1; max-width: 900px;}
    .playlist-panel {width: 350px; background: #fff; border: 2px solid #ddd; border-radius: 4px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); position: sticky; top: 1rem; float: right; margin-left: 1rem; margin-bottom: 2rem;}
    .playlist-header {padding: 1rem; background: #f0f0f0; border-bottom: 1px solid #ddd;}
    .playlist-header h3 {margin: 0; font-size: 1.1rem;}
    .playlist-items {padding: 0.5rem; max-height: 500px; overflow-y: auto;}
    .playlist-item {padding: 0.5rem; margin-bottom: 0.5rem; background: #f9f9f9; border: 1px solid #ddd; border-radius: 3px; display: flex; justify-content: space-between; align-items: center; cursor: pointer;}
    .playlist-item:hover {background: #e9e9e9;}
    .playlist-item.playing {background: #d4edda; border-color: #28a745;}
    .playlist-item-name {flex: 1; font-size: 0.85rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;}
    .remove-from-playlist {background: #dc3545; color: white; border: none; padding: 2px 6px; cursor: pointer; border-radius: 2px; font-size: 0.75rem;}
    .playlist-controls {padding: 0.5rem; border-top: 1px solid #ddd; display: flex; gap: 0.5rem;}
    .playlist-controls button {flex: 1; padding: 8px; background: #0066cc; color: white; border: none; cursor: pointer; border-radius: 3px; font-size: 0.85rem;}
    .playlist-controls button:hover {background: #0052a3;}
    .playlist-empty {text-align: center; color: #999; padding: 2rem; font-size: 0.9rem;}
    .back {margin-bottom: 1rem;}
    .back a {color: #666; text-decoration: none;}
    .back a:hover {text-decoration: underline;}
    .warning {color: #b33; font-size: 0.9rem; margin-top: 2rem; padding: 1rem; background: #fff8f8; border-left: 4px solid #b33;}
    /* ── Cast overlay & status bar ── */
    .cast-overlay {
      display: none; position: absolute; top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0,0,0,0.72); color: #fff; flex-direction: column;
      align-items: center; justify-content: center; z-index: 10;
      border-radius: 4px; pointer-events: none; gap: 0.4rem;
    }
    .cast-overlay.active { display: flex; }
    .cast-overlay .co-icon { font-size: 2.8rem; }
    .cast-overlay .co-device { font-size: 1rem; color: #4fc3f7; font-weight: bold; }
    .cast-overlay .co-file { font-size: 0.95rem; color: #fff; max-width: 90%; text-align: center;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .cast-overlay .co-state { font-size: 0.85rem; color: #aaa; }
    .cast-status-bar {
      display: none; align-items: center; gap: 0.6rem;
      padding: 0.55rem 0.9rem; background: #1a1a2e; color: #eee;
      border-radius: 4px; margin-top: 0.4rem; font-size: 0.88rem;
    }
    .cast-status-bar.active { display: flex; }
    .cast-status-bar input[type=range] { flex: 1; accent-color: #4fc3f7; cursor: pointer; }
    .cast-status-bar .ct { min-width: 42px; text-align: center; font-family: monospace; }
    .cast-status-bar .ct-label { color: #4fc3f7; font-size: 0.8rem; margin-left: 0.3rem; }
  </style>
</head>
<body>
  <!-- Floating language nav bar -->
  <nav class="lang-bar">
    <a class="lang-home" href="/" title="All languages">🏠</a>
    <span class="lang-divider">|</span>
    {% for lang in top_folders %}
      <a class="lang-tab {% if lang == current_language %}active{% endif %}"
         href="/browse/{{ lang | urlencode }}">{{ lang }}</a>
    {% endfor %}
  </nav>

  <h1>Video Library</h1>

  <!-- Always show playlist panel -->
  <div class="playlist-panel" id="playlist-panel">
    <div class="playlist-header">
      <h3>📋 Playlist (<span id="playlist-count">0</span>)</h3>
    </div>
    <div class="playlist-items" id="playlist-items">
      <p class="playlist-empty">No videos in playlist</p>
    </div>
    <div class="playlist-controls">
      <button onclick="playNext()">Next ⏭</button>
      <button onclick="clearPlaylist()">Clear</button>
    </div>
  </div>

  {% if current_path != '.' %}
    <div class="back">
      <a href="{{ parent_url }}">Back to parent folder</a>
    </div>
  {% endif %}

  {% if selected %}
    <div class="player-section">
      <div class="video-wrapper">
        <h2>Now playing: <em>{{ selected }}</em></h2>
        <div class="video-container">
          <video id="video-player" controls width="100%" max-width="900px" preload="auto" playsinline>
            <source id="video-source" src="/stream/{{ selected|urlencode }}" type="video/mp4">
            Your browser cannot play this video.
          </video>
          <div class="cast-overlay" id="cast-overlay">
            <span class="co-icon">📺</span>
            <span class="co-device" id="cast-overlay-device">Casting...</span>
            <span class="co-file" id="cast-overlay-file"></span>
            <span class="co-state" id="cast-overlay-state">Playing</span>
          </div>
        </div>
        <div class="cast-status-bar" id="cast-status-bar">
          <span id="cast-state-icon">▶️</span>
          <span class="ct" id="cast-pos">0:00</span>
          <input type="range" id="cast-seek-bar" min="0" max="100" value="0"
                 oninput="castSeekTo(this.value)" title="Seek on TV">
          <span class="ct" id="cast-dur">0:00</span>
          <span class="ct-label">📺 TV</span>
        </div>
        
        <div class="player-controls">
          <button onclick="skipBackward()">⏪ -10s</button>
          <button onclick="skipForward()">⏩ +10s</button>
          <button onclick="togglePlayPause()" id="play-pause-btn">⏸️ Pause</button>
          <button onclick="toggleMute()" id="mute-btn">🔊 Mute</button>
          <button onclick="toggleFullscreen()">⛶ Fullscreen</button>
          <button onclick="initiateCast()" id="cast-button" title="Cast to device">📺 Cast</button>
          <button onclick="stopCast()" id="stop-cast-button" title="Stop casting" style="display:none;">⏹️ Stop Cast</button>
          <button onclick="playNext()">⏭️ Next</button>
          <button onclick="restartVideo()">🔄 Restart</button>
          <button onclick="manualResync()" title="Fix audio/video sync issues">🔃 Resync</button>
        </div>
        
        <div class="player-controls">
          <div class="speed-control">
            <span style="padding: 10px; color: #666;">Speed:</span>
            <button onclick="setSpeed(0.5)">0.5x</button>
            <button onclick="setSpeed(0.75)">0.75x</button>
            <button onclick="setSpeed(1)" class="active" id="speed-1">1x</button>
            <button onclick="setSpeed(1.25)">1.25x</button>
            <button onclick="setSpeed(1.5)">1.5x</button>
            <button onclick="setSpeed(2)">2x</button>
          </div>
        </div>
      </div>
    </div>
    <hr>
  {% endif %}  <div class="url-cast-bar">
    <span style="font-size:0.9rem;color:#555;white-space:nowrap;">🌐 Cast URL:</span>
    <input type="url" id="url-cast-input" placeholder="Paste a YouTube / video page URL…"
           onkeydown="if(event.key==='Enter') probeAndCastUrl()">
    <button id="url-cast-btn" onclick="probeAndCastUrl()">📺 Cast</button>
  </div>

  <div class="sort-controls">
    <label>Sort by:</label>
    <button id="sort-name-asc" onclick="sortFiles('name', 'asc')">Name ↑</button>
    <button id="sort-name-desc" onclick="sortFiles('name', 'desc')">Name ↓</button>
    <button id="sort-date-asc" onclick="sortFiles('date', 'asc')">Date ↑</button>
    <button id="sort-date-desc" onclick="sortFiles('date', 'desc')" class="active">Date ↓</button>
  </div>

  <div class="tree" id="file-tree">
    {% macro render_node(node, path_parts) %}
      {% for name, data in node.items()|list %}
        {% set current_path = path_parts + [name] %}
        {% set full_path = current_path|join('/') %}
        {% if data._type == 'folder' %}
          <div class="folder">
            <a href="/browse/{{ full_path }}">Folder: {{ name }}</a>
          </div>
          <div class="indent">
            {{ render_node(data._children, current_path) }}
          </div>
        {% else %}
          <div class="file" data-name="{{ name }}" data-date="{{ data.mtime }}">
            <a href="/watch/{{ data.path|urlencode }}">{{ name }}</a>
            <span class="file-date">{{ data.mtime|format_date }}</span>
            <button class="add-to-playlist" onclick="addToPlaylist('{{ data.path }}', '{{ name }}', event)">+ Playlist</button>
          </div>
        {% endif %}
      {% endfor %}
    {% endmacro %}

    {{ render_node(tree, []) }}
  </div>

  {% if not tree and not selected %}
    <p><em>No browser-playable .mp4 videos found.</em></p>
    <div class="warning">
      <strong>Tip:</strong> Only <code>.mp4</code> files with <strong>H.264 video + AAC audio</strong> can play in browsers.<br>
      Use <code>ffmpeg</code> to convert others: <br>
      <code>ffmpeg -i input.mkv -c:v libx264 -c:a aac -strict -2 output.mp4</code>
    </div>
  {% endif %}

  <script>
    // Playlist functionality
    let playlist = JSON.parse(localStorage.getItem('videoPlaylist') || '[]');
    let currentPlayingIndex = -1;
    
    function savePlaylist() {
      localStorage.setItem('videoPlaylist', JSON.stringify(playlist));
      updatePlaylistUI();
    }
    
    function updatePlaylistUI() {
      const count = document.getElementById('playlist-count');
      const items = document.getElementById('playlist-items');
      count.textContent = playlist.length;
      
      if (playlist.length === 0) {
        items.innerHTML = '<p class="playlist-empty">No videos in playlist</p>';
        // Reset all "Add to Playlist" buttons
        updateAddButtons();
        return;
      }
      
      items.innerHTML = playlist.map((item, index) => `
        <div class="playlist-item ${index === currentPlayingIndex ? 'playing' : ''}" onclick="playFromPlaylist(${index})">
          <span class="playlist-item-name" title="${item.name}">${index + 1}. ${item.name}</span>
          <button class="remove-from-playlist" onclick="removeFromPlaylist(${index}, event)">×</button>
        </div>
      `).join('');
      
      // Update "Add to Playlist" buttons
      updateAddButtons();
    }
    
    function updateAddButtons() {
      document.querySelectorAll('.add-to-playlist').forEach(btn => {
        const onclickAttr = btn.getAttribute('onclick');
        if (!onclickAttr) return;
        
        const match = onclickAttr.match(/'([^']+)'/);
        if (!match) return;
        
        const path = match[1];
        const inPlaylist = playlist.some(item => item.path === path);
        
        if (inPlaylist) {
          btn.classList.add('in-playlist');
          btn.textContent = '✓ Added';
        } else {
          btn.classList.remove('in-playlist');
          btn.textContent = '+ Playlist';
        }
      });
    }
    
    function togglePlaylist() {
      document.getElementById('playlist-panel').classList.toggle('open');
    }
    
    function addToPlaylist(path, name, event) {
      event.preventDefault();
      event.stopPropagation();
      
      if (!playlist.some(item => item.path === path)) {
        const wasEmpty = playlist.length === 0;
        playlist.push({path, name});
        savePlaylist();
        
        // If playlist was empty, auto-play the first video
        if (wasEmpty) {
          window.location.href = '/watch/' + encodeURIComponent(path);
        }
      }
    }
    
    function removeFromPlaylist(index, event) {
      event.stopPropagation();
      playlist.splice(index, 1);
      if (currentPlayingIndex === index) {
        currentPlayingIndex = -1;
      } else if (currentPlayingIndex > index) {
        currentPlayingIndex--;
      }
      savePlaylist();
    }
    
    function clearPlaylist() {
      if (confirm('Clear entire playlist?')) {
        playlist = [];
        currentPlayingIndex = -1;
        savePlaylist();
      }
    }
    
    function playFromPlaylist(index) {
      currentPlayingIndex = index;
      window.location.href = '/watch/' + encodeURIComponent(playlist[index].path);
    }
    
    function playNext() {
      if (playlist.length === 0) return;
      currentPlayingIndex = (currentPlayingIndex + 1) % playlist.length;
      playFromPlaylist(currentPlayingIndex);
    }
    
    // Initialize playlist UI
    updatePlaylistUI();
    
    // Video sync and buffering improvements
    const video = document.getElementById('video-player');

    // ── Cast-mode state ──
    let castMode = false;
    let castPollInterval = null;   // kept for fallback only
    let castDuration = 0;
    let castStartTime = 0;
    let castEverPlayed = false;

    function fmtTime(sec) {
      sec = Math.floor(sec || 0);
      return Math.floor(sec / 60) + ':' + (sec % 60).toString().padStart(2, '0');
    }

    function castControl(action, value) {
      return fetch('/api/cast/control', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({device: selectedCastDevice, action, value})
      }).then(r => r.json());
    }

    function castSeekTo(val) {
      castControl('seek', (parseFloat(val) / 100) * castDuration);
    }

    // ── Apply a status object from SSE to the UI ──
    function applyCastStatus(data) {
      const pos   = data.current_time || 0;
      const dur   = data.duration     || 0;
      const state = data.player_state || '';
      castDuration = dur;

      const posEl  = document.getElementById('cast-pos');
      const durEl  = document.getElementById('cast-dur');
      const seekBar = document.getElementById('cast-seek-bar');
      const icon   = document.getElementById('cast-state-icon');
      const overlayState = document.getElementById('cast-overlay-state');
      const ppBtn  = document.getElementById('play-pause-btn');

      if (posEl)  posEl.textContent  = fmtTime(pos);
      if (durEl)  durEl.textContent  = fmtTime(dur);
      if (seekBar && dur > 0) seekBar.value = (pos / dur) * 100;

      if (state === 'PLAYING') {
        castEverPlayed = true;
        if (icon)         icon.textContent         = '▶️';
        if (overlayState) overlayState.textContent = 'Playing';
        if (ppBtn)        ppBtn.textContent        = '⏸️ Pause';
      } else if (state === 'PAUSED') {
        castEverPlayed = true;
        if (icon)         icon.textContent         = '⏸️';
        if (overlayState) overlayState.textContent = 'Paused';
        if (ppBtn)        ppBtn.textContent        = '▶️ Play';
      } else if (state === 'BUFFERING' || state === 'LOADING') {
        if (overlayState) overlayState.textContent = 'Buffering…';
      }
    }

    // ── SSE subscription — one connection per tab, shared across all clients ──
    let _castEvtSource = null;

    function subscribeCastEvents() {
      if (_castEvtSource) return;
      _castEvtSource = new EventSource('/api/cast/events');

      _castEvtSource.addEventListener('cast_started', e => {
        const data = JSON.parse(e.data);
        selectedCastDevice = data.device;
        if (!castMode) startCastMode(data.device, data.filename);
        // Update filename on overlay even if already in cast mode
        const fileEl = document.getElementById('cast-overlay-file');
        if (fileEl && data.filename) fileEl.textContent = data.filename.split('/').pop().replace(/\.mp4$/i, '');
        // Update button states for ALL clients (not just the initiating one)
        const castBtn = document.getElementById('cast-button');
        if (castBtn) castBtn.textContent = '📺 Casting';
        const stopBtn = document.getElementById('stop-cast-button');
        if (stopBtn) stopBtn.style.display = 'inline-flex';
        console.log('[Cast] Started on', data.device, '→', data.url);
      });

      _castEvtSource.addEventListener('cast_status', e => {
        const data = JSON.parse(e.data);
        if (data.active) {
          if (!castMode) {
            selectedCastDevice = data.device;
            startCastMode(data.device, data.filename);
            const castBtn = document.getElementById('cast-button');
            if (castBtn) castBtn.textContent = '📺 Casting';
          } else if (data.filename) {
            // Keep filename up to date (e.g. after page refresh)
            const fileEl = document.getElementById('cast-overlay-file');
            if (fileEl && !fileEl.textContent)
              fileEl.textContent = data.filename.split('/').pop().replace(/\.mp4$/i, '');
          }
          const stopBtn = document.getElementById('stop-cast-button');
          if (stopBtn) stopBtn.style.display = 'inline-flex';
          applyCastStatus(data);
        }
      });

      _castEvtSource.addEventListener('cast_stopped', e => {
        if (castMode) exitCastMode();
        const stopBtn = document.getElementById('stop-cast-button');
        if (stopBtn) { stopBtn.style.display = 'none'; stopBtn.textContent = '⏹️ Stop Cast'; }
        const castBtn = document.getElementById('cast-button');
        if (castBtn) castBtn.textContent = '📺 Cast';
        const ppBtn = document.getElementById('play-pause-btn');
        if (ppBtn) ppBtn.textContent = '▶️ Play';
        const fileEl = document.getElementById('cast-overlay-file');
        if (fileEl) fileEl.textContent = '';
      });

      _castEvtSource.onerror = () => {
        // EventSource auto-reconnects; just log
        console.log('[Cast] SSE reconnecting…');
      };
    }

    subscribeCastEvents();

    function startCastMode(deviceName, filename) {
      castMode = true;
      castStartTime = Date.now();
      castEverPlayed = false;
      const overlay = document.getElementById('cast-overlay');
      if (overlay) {
        overlay.classList.add('active');
        document.getElementById('cast-overlay-device').textContent = 'Casting to ' + deviceName;
        document.getElementById('cast-overlay-state').textContent = 'Connecting…';
        const fileEl = document.getElementById('cast-overlay-file');
        if (fileEl) fileEl.textContent = filename
          ? filename.split('/').pop().replace(/\.mp4$/i, '')
          : '';
      }
      document.getElementById('cast-status-bar').classList.add('active');
      if (video) { video.style.opacity = '0.15'; video.style.pointerEvents = 'none'; }
    }

    function exitCastMode() {
      castMode = false;
      clearInterval(castPollInterval);
      castPollInterval = null;
      const overlay = document.getElementById('cast-overlay');
      if (overlay) overlay.classList.remove('active');
      const sb = document.getElementById('cast-status-bar');
      if (sb) sb.classList.remove('active');
      if (video) { video.style.opacity = ''; video.style.pointerEvents = ''; }
    }

    // Player control functions
    function skipBackward() {
      if (castMode) { castControl('seek_relative', -10); return; }
      if (video) video.currentTime = Math.max(0, video.currentTime - 10);
    }
    
    function skipForward() {
      if (castMode) { castControl('seek_relative', 10); return; }
      if (video) video.currentTime = Math.min(video.duration, video.currentTime + 10);
    }

    function togglePlayPause() {
      if (castMode) {
        const btn = document.getElementById('play-pause-btn');
        if (btn && btn.textContent.includes('Pause')) {
          castControl('pause').then(() => { if (btn) btn.textContent = '▶️ Play'; });
        } else {
          castControl('play').then(() => { if (btn) btn.textContent = '⏸️ Pause'; });
        }
        return;
      }
      if (!video) return;
      const btn = document.getElementById('play-pause-btn');
      if (video.paused) { video.play(); btn.textContent = '⏸️ Pause'; }
      else { video.pause(); btn.textContent = '▶️ Play'; }
    }

    function toggleMute() {
      if (castMode) { castControl('mute'); return; }
      if (!video) return;
      const btn = document.getElementById('mute-btn');
      video.muted = !video.muted;
      btn.textContent = video.muted ? '🔇 Unmute' : '🔊 Mute';
    }
    
    function toggleFullscreen() {
      if (!video) return;
      if (video.requestFullscreen) {
        video.requestFullscreen();
      } else if (video.webkitRequestFullscreen) {
        video.webkitRequestFullscreen();
      } else if (video.mozRequestFullScreen) {
        video.mozRequestFullScreen();
      }
    }
    
    function restartVideo() {
      if (castMode) { castControl('seek', 0).then(() => castControl('play')); return; }
      if (video) { video.currentTime = 0; video.play(); }
    }

    function setSpeed(speed) {
      if (castMode) { castControl('set_speed', speed); }
      document.querySelectorAll('.speed-control button').forEach(btn => {
        btn.classList.remove('active');
        if (btn.textContent === speed + 'x') btn.classList.add('active');
      });
      if (!castMode && video) video.playbackRate = speed;
    }



    // Manual resync: micro-seek to force decoder re-alignment
    function manualResync() {
      if (castMode || !video) return;
      const t = video.currentTime;
      if (video.fastSeek) { video.fastSeek(t); } else { video.currentTime = t; }
    }
    
    // Chromecast casting via server-side pychromecast
    let castDevices = [];
    let selectedCastDevice = '';

    // Discover cast devices on page load (non-blocking)
    fetch('/api/cast/devices')
      .then(r => r.json())
      .then(data => {
        castDevices = data.devices || [];
        const btn = document.getElementById('cast-button');
        if (btn && castDevices.length > 0) {
          btn.title = 'Cast to: ' + castDevices.join(', ');
        }
        // Default to a device whose name contains "TV", otherwise first device
        const tvDevice = castDevices.find(d => /tv/i.test(d));
        selectedCastDevice = tvDevice || castDevices[0] || '';
      })
      .catch(() => {});

    function _showCastPicker(filename, currentTime) {
      const dlg = document.getElementById('cast-picker-dialog');
      // Store context so the refresh button can re-use it
      dlg._castFilename = filename;
      dlg._castTime = currentTime;
      _populateCastPicker(filename, currentTime);
      document.getElementById('cast-picker-cancel').onclick = () => dlg.close();
      document.getElementById('cast-picker-refresh').onclick = () => {
        const list = document.getElementById('cast-picker-list');
        list.innerHTML = '<p style="color:#aaa;font-size:13px;margin:8px 0;">🔍 Scanning...</p>';
        fetch('/api/cast/devices')
          .then(r => r.json())
          .then(data => {
            castDevices = data.devices || [];
            const tvDevice = castDevices.find(d => /tv/i.test(d));
            selectedCastDevice = tvDevice || castDevices[0] || '';
            _populateCastPicker(dlg._castFilename, dlg._castTime);
          })
          .catch(() => {
            list.innerHTML = '<p style="color:#f66;font-size:13px;margin:8px 0;">Discovery failed.</p>';
          });
      };
      dlg.showModal();
    }

    function _populateCastPicker(filename, currentTime) {
      const dlg = document.getElementById('cast-picker-dialog');
      const list = document.getElementById('cast-picker-list');
      list.innerHTML = '';
      if (castDevices.length === 0) {
        list.innerHTML = '<p style="color:#aaa;font-size:13px;margin:8px 0;">No devices found. Click Refresh.</p>';
        return;
      }
      castDevices.forEach(name => {
        const isDefault = (name === selectedCastDevice);
        const btn = document.createElement('button');
        btn.textContent = name + (isDefault ? ' ★' : '');
        btn.style.cssText = 'display:block;width:100%;margin:4px 0;padding:8px 12px;cursor:pointer;border:1px solid ' + (isDefault ? '#4a9eff' : '#555') + ';background:' + (isDefault ? '#1a3a5c' : '#222') + ';color:#fff;border-radius:4px;font-size:14px;text-align:left;';
        btn.onclick = () => {
          dlg.close();
          selectedCastDevice = name;
          _doCast(filename, currentTime, name);
        };
        list.appendChild(btn);
      });
    }

    function initiateCast() {
      const source = document.getElementById('video-source');
      if (!source) { alert('No video is currently playing.'); return; }

      const pathname = new URL(source.src).pathname;
      const filename = decodeURIComponent(pathname.replace(/^\/stream\//, ''));
      const currentTime = video ? video.currentTime : 0;

      if (castDevices.length === 0) {
        // Devices not yet fetched — discover now, then show picker
        const castBtn = document.getElementById('cast-button');
        if (castBtn) castBtn.textContent = '🔍 Discovering...';
        fetch('/api/cast/devices')
          .then(r => r.json())
          .then(data => {
            castDevices = data.devices || [];
            const tvDevice = castDevices.find(d => /tv/i.test(d));
            selectedCastDevice = tvDevice || castDevices[0] || '';
            if (castBtn) castBtn.textContent = '📺 Cast';
            if (castDevices.length === 0) { alert('No Chromecast devices found on the network.'); return; }
            _showCastPicker(filename, currentTime);
          })
          .catch(err => {
            if (castBtn) castBtn.textContent = '📺 Cast';
            alert('Device discovery failed: ' + err);
          });
        return;
      }

      // Always show picker so user consciously chooses the target device
      _showCastPicker(filename, currentTime);
    }

    function _doCast(filename, currentTime, device) {
      const btn = document.getElementById('cast-button');
      if (btn) btn.textContent = '⏳ Casting...';

      fetch('/api/cast', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({filename: filename, position: currentTime, device: device})
      })
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          if (video) video.pause();
          if (btn) btn.textContent = '📺 Casting';
          selectedCastDevice = data.device;
          const stopBtn = document.getElementById('stop-cast-button');
          if (stopBtn) stopBtn.style.display = 'inline-flex';
          startCastMode(data.device, filename);
          console.log('[Cast] Streaming URL sent to TV:', data.url);
        } else {
          if (btn) btn.textContent = '📺 Cast';
          alert('Cast failed: ' + (data.error || 'unknown error'));
        }
      })
      .catch(err => {
        if (btn) btn.textContent = '📺 Cast';
        alert('Cast request failed: ' + err);
      });
    }

    function stopCast() {
      const stopBtn = document.getElementById('stop-cast-button');
      const castBtn = document.getElementById('cast-button');
      if (stopBtn) stopBtn.textContent = '⏳ Stopping...';
      fetch('/api/cast/stop', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({device: selectedCastDevice})
      })
      .then(r => r.json())
      .then(data => {
        if (data.ok) {
          exitCastMode();
          if (stopBtn) { stopBtn.textContent = '⏹️ Stop Cast'; stopBtn.style.display = 'none'; }
          if (castBtn) castBtn.textContent = '📺 Cast';
        } else {
          if (stopBtn) stopBtn.textContent = '⏹️ Stop Cast';
          alert('Stop cast failed: ' + (data.error || 'unknown error'));
        }
      })
      .catch(err => {
        if (stopBtn) stopBtn.textContent = '⏹️ Stop Cast';
        alert('Stop cast request failed: ' + err);
      });
    }
    
    // Update play/pause button based on video state
    if (video) {
      video.addEventListener('play', () => {
        const btn = document.getElementById('play-pause-btn');
        if (btn) btn.textContent = '⏸️ Pause';
      });
      video.addEventListener('pause', () => {
        const btn = document.getElementById('play-pause-btn');
        if (btn) btn.textContent = '▶️ Play';
      });
    }
    
    if (video) {
      // Auto-play
      video.addEventListener('loadedmetadata', () => {
        if (castMode) return;
        video.play().catch(() => {});
      });
      
      // Auto-play next video when current ends
      video.addEventListener('ended', () => {
        if (playlist.length > 0) {
          playNext();
        }
      });
      
      // Mark current video in playlist
      const currentPath = '{{ selected }}';
      if (currentPath) {
        currentPlayingIndex = playlist.findIndex(item => item.path === currentPath);
        updatePlaylistUI();
      }
    }
    
    // Cast button setup
    const castButton = document.getElementById('cast-button');
    if (castButton) {
      castButton.style.display = 'inline-flex';
      castButton.title = 'Cast to Chromecast';
    }

    // ── URL Cast ──────────────────────────────────────────────────────
    let _urlVideos = [];   // probed video list
    let _urlPendingDevice = null;  // device chosen before video chosen

    function probeAndCastUrl() {
      const input = document.getElementById('url-cast-input');
      const btn   = document.getElementById('url-cast-btn');
      const url   = (input.value || '').trim();
      if (!url) { input.focus(); return; }
      btn.disabled = true;
      btn.textContent = '🔍 Probing…';
      fetch('/api/url/probe', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({url})
      })
      .then(r => r.json())
      .then(data => {
        btn.disabled = false;
        btn.textContent = '📺 Cast';
        if (data.error) { alert('Probe failed: ' + data.error); return; }
        _urlVideos = data.videos || [];
        if (_urlVideos.length === 0) { alert('No playable video found at that URL.'); return; }
        if (_urlVideos.length === 1) {
          _pickDeviceForUrl(_urlVideos[0]);
        } else {
          _showUrlVideoPicker(data.page_title || url);
        }
      })
      .catch(err => {
        btn.disabled = false;
        btn.textContent = '📺 Cast';
        alert('Probe request failed: ' + err);
      });
    }

    function _showUrlVideoPicker(pageTitle) {
      const dlg  = document.getElementById('url-video-picker');
      const list = document.getElementById('url-video-list');
      document.getElementById('url-video-source').textContent = pageTitle;
      list.innerHTML = '';
      _urlVideos.forEach((v, i) => {
        const dur = v.duration ? _fmtDur(v.duration) : '?:??';
        const btn = document.createElement('button');
        btn.style.cssText = 'display:block;width:100%;margin:5px 0;padding:10px 12px;cursor:pointer;'
          + 'border:1px solid #555;background:#222;color:#fff;border-radius:4px;font-size:13px;text-align:left;';
        btn.innerHTML = `<strong style="display:block;margin-bottom:3px;">${_esc(v.title)}</strong>`
          + `<span style="color:#aaa;font-size:12px;">${dur} &nbsp;·&nbsp; ${_esc(v.format || '')}</span>`;
        btn.onclick = () => { dlg.close(); _pickDeviceForUrl(v); };
        list.appendChild(btn);
      });
      document.getElementById('url-video-cancel').onclick = () => dlg.close();
      dlg.showModal();
    }

    function _pickDeviceForUrl(videoEntry) {
      // Ensure devices are loaded, then show cast picker
      const go = () => _showCastPickerForUrl(videoEntry);
      if (castDevices.length === 0) {
        const btn = document.getElementById('url-cast-btn');
        if (btn) { btn.disabled = true; btn.textContent = '🔍 Finding devices…'; }
        fetch('/api/cast/devices').then(r => r.json()).then(data => {
          castDevices = data.devices || [];
          const tv = castDevices.find(d => /tv/i.test(d));
          selectedCastDevice = tv || castDevices[0] || '';
          if (btn) { btn.disabled = false; btn.textContent = '📺 Cast'; }
          if (castDevices.length === 0) { alert('No Chromecast found.'); return; }
          go();
        }).catch(() => { if (btn) { btn.disabled = false; btn.textContent = '📺 Cast'; } });
      } else {
        go();
      }
    }

    function _showCastPickerForUrl(videoEntry) {
      const dlg  = document.getElementById('cast-picker-dialog');
      const list = document.getElementById('cast-picker-list');
      dlg._urlVideo = videoEntry;
      list.innerHTML = '';
      castDevices.forEach(name => {
        const isDefault = (name === selectedCastDevice);
        const btn = document.createElement('button');
        btn.textContent = name + (isDefault ? ' ★' : '');
        btn.style.cssText = 'display:block;width:100%;margin:4px 0;padding:8px 12px;cursor:pointer;border:1px solid '
          + (isDefault ? '#4a9eff' : '#555') + ';background:' + (isDefault ? '#1a3a5c' : '#222')
          + ';color:#fff;border-radius:4px;font-size:14px;text-align:left;';
        btn.onclick = () => {
          dlg.close();
          selectedCastDevice = name;
          _castUrlDirect(videoEntry, name);
        };
        list.appendChild(btn);
      });
      document.getElementById('cast-picker-cancel').onclick = () => dlg.close();
      document.getElementById('cast-picker-refresh').onclick = () => {
        list.innerHTML = '<p style="color:#aaa;font-size:13px;margin:8px 0;">🔍 Scanning…</p>';
        fetch('/api/cast/devices').then(r => r.json()).then(data => {
          castDevices = data.devices || [];
          const tv = castDevices.find(d => /tv/i.test(d));
          selectedCastDevice = tv || castDevices[0] || '';
          _populateCastPicker(dlg._castFilename, dlg._castTime);
        }).catch(() => { list.innerHTML = '<p style="color:#f66;font-size:13px;">Discovery failed.</p>'; });
      };
      dlg.showModal();
    }

    function _castUrlDirect(videoEntry, device) {
      const btn = document.getElementById('url-cast-btn');
      if (btn) { btn.disabled = true; btn.textContent = '⏳ Casting…'; }
      fetch('/api/cast/url', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({stream_url: videoEntry.stream_url, title: videoEntry.title, device})
      })
      .then(r => r.json())
      .then(data => {
        if (btn) { btn.disabled = false; btn.textContent = '📺 Cast'; }
        if (!data.ok) { alert('Cast failed: ' + (data.error || 'unknown')); return; }
        selectedCastDevice = data.device;
        // SSE cast_started will fire and update all clients
      })
      .catch(err => {
        if (btn) { btn.disabled = false; btn.textContent = '📺 Cast'; }
        alert('Cast request failed: ' + err);
      });
    }

    function _fmtDur(sec) {
      if (!sec) return '?:??';
      sec = Math.floor(sec);
      const h = Math.floor(sec / 3600);
      const m = Math.floor((sec % 3600) / 60);
      const s = sec % 60;
      if (h > 0) return h + ':' + String(m).padStart(2,'0') + ':' + String(s).padStart(2,'0');
      return m + ':' + String(s).padStart(2,'0');
    }

    function _esc(s) {
      return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }

    // Sorting functionality
    function sortFiles(sortBy, order) {
      // Update button styles
      document.querySelectorAll('.sort-controls button').forEach(btn => btn.classList.remove('active'));
      document.getElementById(`sort-${sortBy}-${order}`).classList.add('active');
      
      // Get all file elements
      const tree = document.getElementById('file-tree');
      const files = Array.from(tree.querySelectorAll('.file'));
      
      // Sort files
      files.sort((a, b) => {
        let valA, valB;
        if (sortBy === 'name') {
          valA = a.dataset.name.toLowerCase();
          valB = b.dataset.name.toLowerCase();
        } else {
          valA = parseFloat(a.dataset.date);
          valB = parseFloat(b.dataset.date);
        }
        
        if (order === 'asc') {
          return valA > valB ? 1 : valA < valB ? -1 : 0;
        } else {
          return valA < valB ? 1 : valA > valB ? -1 : 0;
        }
      });
      
      // Reorder in DOM
      files.forEach(file => {
        const parent = file.parentElement;
        parent.appendChild(file);
      });
    }

    // Apply default sort on load
    sortFiles('date', 'desc');
  </script>

  <!-- Cast device picker dialog -->
  <dialog id="cast-picker-dialog" style="background:#1a1a1a;color:#fff;border:1px solid #444;border-radius:8px;padding:20px;min-width:280px;">
    <h3 style="margin:0 0 12px;font-size:16px;">Select Chromecast device</h3>
    <div id="cast-picker-list"></div>
    <div style="display:flex;gap:8px;margin-top:14px;">
      <button id="cast-picker-refresh" style="flex:1;padding:6px 14px;background:#1a3a5c;color:#4fc3f7;border:1px solid #4a9eff;border-radius:4px;cursor:pointer;">🔄 Refresh</button>
      <button id="cast-picker-cancel" style="flex:1;padding:6px 14px;background:#444;color:#fff;border:none;border-radius:4px;cursor:pointer;">Cancel</button>
    </div>
  </dialog>

  <!-- URL video picker dialog -->
  <dialog id="url-video-picker" style="background:#1a1a1a;color:#fff;border:1px solid #444;border-radius:8px;padding:20px;min-width:340px;max-width:520px;width:90vw;">
    <h3 style="margin:0 0 4px;font-size:16px;">🌐 Select video to cast</h3>
    <p id="url-video-source" style="margin:0 0 12px;font-size:12px;color:#aaa;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"></p>
    <div id="url-video-list" style="max-height:55vh;overflow-y:auto;"></div>
    <div style="display:flex;gap:8px;margin-top:14px;">
      <button id="url-video-cancel" style="flex:1;padding:6px 14px;background:#444;color:#fff;border:none;border-radius:4px;cursor:pointer;">Cancel</button>
    </div>
  </dialog>

</body>
</html>
"""

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    tree = build_tree()
    top_folders = get_top_level_folders()
    return render_template_string(INDEX_HTML, tree=tree, selected=None,
                                  current_path='.', parent_url=None,
                                  top_folders=top_folders, current_language='')

@app.route('/browse/<path:subpath>')
def browse(subpath):
    tree = build_tree()
    parts = subpath.split('/') if subpath else []
    current = tree
    for part in parts:
        if part not in current or current[part]['_type'] != 'folder':
            abort(404)
        current = current[part]['_children']
    parent_parts = parts[:-1]
    parent_url   = '/browse/' + '/'.join(parent_parts) if parent_parts else '/'
    top_folders      = get_top_level_folders()
    current_language = parts[0] if parts else ''
    return render_template_string(INDEX_HTML, tree=current, selected=None,
                                  current_path=subpath, parent_url=parent_url,
                                  top_folders=top_folders, current_language=current_language)

@app.route('/watch/<path:filename>')
def watch(filename):
    fullpath = os.path.abspath(os.path.join(VIDEO_ROOT, filename))
    if not fullpath.startswith(os.path.abspath(VIDEO_ROOT)) or not os.path.isfile(fullpath):
        abort(404)
    if not is_browser_playable(fullpath):
        abort(415)
    tree        = build_tree()
    top_folders = get_top_level_folders()
    parts            = filename.split('/')
    current_language = parts[0] if len(parts) > 1 else ''
    if current_language and current_language in tree and tree[current_language]['_type'] == 'folder':
        display_tree = tree[current_language]['_children']
        current_path = current_language
    else:
        display_tree = tree
        current_path = '.'
    return render_template_string(INDEX_HTML, tree=display_tree, selected=filename,
                                  current_path=current_path, parent_url='/',
                                  top_folders=top_folders, current_language=current_language)

def generate_stream(filepath):
    """Serve video with byte-range support for native browser seeking."""
    file_size    = os.path.getsize(filepath)
    range_header = request.headers.get('Range', None)
    content_type = mime.from_file(filepath)
    CHUNK_SIZE   = 2097152  # 2 MB

    if not range_header:
        def gen():
            with open(filepath, 'rb') as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    yield chunk
        return Response(gen(), mimetype=content_type, headers={
            'Accept-Ranges':              'bytes',
            'Cache-Control':              'no-cache',
            'Content-Length':             str(file_size),
            'Access-Control-Allow-Origin':  '*',
            'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
            'Access-Control-Allow-Headers': 'Range',
        })

    start = 0
    end   = file_size - 1
    if range_header.startswith('bytes='):
        r     = range_header[6:]
        parts = r.split('-')
        if parts[0]:
            start = int(parts[0])
        if len(parts) > 1 and parts[1]:
            end = int(parts[1])

    if start >= file_size:
        return Response('', 416, {'Content-Range': f'bytes */{file_size}'})

    def gen():
        with open(filepath, 'rb') as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    break
                yield chunk
                remaining -= len(chunk)

    headers = {
        'Content-Range':              f'bytes {start}-{end}/{file_size}',
        'Accept-Ranges':              'bytes',
        'Content-Length':             str(end - start + 1),
        'Content-Type':               content_type,
        'Cache-Control':              'no-cache',
        'Connection':                 'keep-alive',
        'Access-Control-Allow-Origin':  '*',
        'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
        'Access-Control-Allow-Headers': 'Range',
    }
    return Response(gen(), 206, headers)

@app.route('/stream/<path:filename>', methods=('GET', 'HEAD', 'OPTIONS'))
def stream(filename):
    if request.method == 'OPTIONS':
        return Response('', 204, {
            'Access-Control-Allow-Origin':  '*',
            'Access-Control-Allow-Methods': 'GET, HEAD, OPTIONS',
            'Access-Control-Allow-Headers': 'Range',
        })
    fullpath = os.path.abspath(os.path.join(VIDEO_ROOT, filename))
    if not fullpath.startswith(os.path.abspath(VIDEO_ROOT)) or not os.path.isfile(fullpath):
        abort(404)
    if not is_browser_playable(fullpath):
        return 'This video format is not supported in web browsers. Convert to H.264/AAC MP4.', 415
    # Serve faststart version (moov at front) for reliable Chromecast playback
    with _faststart_lock:
        serve_path = _get_faststart_path(fullpath)
    return generate_stream(serve_path)

# ── SSE broadcast ─────────────────────────────────────────────────────────────
def _sse_broadcast(event_type, data):
    """Push a JSON event to every connected SSE client."""
    payload = f'event: {event_type}\ndata: {json.dumps(data)}\n\n'
    with _sse_queues_lock:
        dead = []
        for q in _sse_queues:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_queues.remove(q)

# ── Cast poller thread ─────────────────────────────────────────────────────────
def _cast_poller():
    """Background thread: poll the active Chromecast every 2 s and broadcast."""
    while True:
        threading.Event().wait(2)
        with _cast_state_lock:
            if not _cast_state['active']:
                continue
            device_name = _cast_state['device']
            ever_played = _cast_state['ever_played']
            start_time  = _cast_state['start_time']
        try:
            with _active_cast_lock:
                cc = _active_cast.get(device_name)
            if cc is None:
                continue
            mc = cc.media_controller
            mc.update_status()
            s     = mc.status
            state = s.player_state if s else 'UNKNOWN'
            pos   = s.current_time if s else 0
            dur   = s.duration     if s else 0

            if state == 'PLAYING' and not ever_played:
                with _cast_state_lock:
                    _cast_state['ever_played'] = True
                    ever_played = True

            with _cast_state_lock:
                _cast_state['player_state'] = state
                _cast_state['current_time'] = pos
                _cast_state['duration']     = dur

            _sse_broadcast('cast_status', {
                'active':       True,
                'device':       device_name,
                'player_state': state,
                'current_time': pos,
                'duration':     dur,
                'filename':     _cast_state.get('filename', ''),
            })

            elapsed = _time.monotonic() - start_time
            if state in ('IDLE', 'UNKNOWN') and (ever_played or elapsed > 30):
                with _cast_state_lock:
                    _cast_state['active']      = False
                    _cast_state['ever_played'] = False
                _sse_broadcast('cast_stopped', {'device': device_name})
        except Exception:
            pass

_cast_poller_thread = threading.Thread(target=_cast_poller, daemon=True, name='cast-poller')
_cast_poller_thread.start()

# ── Internal helper: get or (re-)connect a Chromecast ─────────────────────────
def _get_or_connect(device_name):
    """Return a live Chromecast object for device_name, reusing or (re-)connecting."""
    import pychromecast
    with _active_cast_lock:
        cc = _active_cast.get(device_name)
    if cc is not None:
        try:
            cc.media_controller.update_status()
            return cc
        except Exception:
            pass
    with _cast_lock:
        entry = _cast_devices.get(device_name)
    if entry is None:
        raise RuntimeError(f"Device '{device_name}' not in cache — discover first")
    host, port = entry
    cc = pychromecast.get_chromecast_from_host((host, port, None, None, device_name or 'Chromecast'))
    cc.wait(timeout=10)
    with _active_cast_lock:
        _active_cast[device_name] = cc
    return cc

def _discover(timeout=5):
    """Discover Chromecasts and return {name: (host, port)} dict."""
    import pychromecast
    chromecasts, browser = pychromecast.get_chromecasts(
        timeout=timeout, zeroconf_instance=_zconf
    )
    pychromecast.discovery.stop_discovery(browser)
    return {cc.name: (cc.cast_info.host, cc.cast_info.port) for cc in chromecasts}

# ── Cast API routes ────────────────────────────────────────────────────────────
@app.route('/api/cast/devices')
def cast_devices():
    """Discover Chromecast devices on the LAN and return their names."""
    try:
        found = _discover()
        with _cast_lock:
            _cast_devices.clear()
            _cast_devices.update(found)
        return jsonify({'devices': list(_cast_devices.keys())})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cast/events')
def cast_events():
    """SSE endpoint — each browser subscribes here and receives cast state pushes."""
    q = queue.Queue(maxsize=30)
    with _sse_queues_lock:
        _sse_queues.append(q)
    with _cast_state_lock:
        initial = dict(_cast_state)
    event_type = 'cast_status' if initial['active'] else 'cast_stopped'
    q.put_nowait(f'event: {event_type}\ndata: {json.dumps(initial)}\n\n')

    def stream():
        try:
            while True:
                try:
                    yield q.get(timeout=20)
                except queue.Empty:
                    yield ': keepalive\n\n'
        finally:
            with _sse_queues_lock:
                try:
                    _sse_queues.remove(q)
                except ValueError:
                    pass

    return Response(stream(), mimetype='text/event-stream', headers={
        'Cache-Control':              'no-cache',
        'X-Accel-Buffering':          'no',
        'Access-Control-Allow-Origin': '*',
    })

@app.route('/api/cast', methods=['POST'])
def cast_media():
    """Tell a Chromecast to play a video.
    Body JSON: { "filename": "rel/path.mp4", "position": 123.4, "device": "Living Room TV" }
    """
    data        = request.get_json(force=True)
    filename    = data.get('filename', '')
    position    = float(data.get('position', 0))
    device_name = data.get('device', '')

    if not filename:
        return jsonify({'error': 'filename required'}), 400

    fullpath = os.path.abspath(os.path.join(VIDEO_ROOT, filename))
    if not fullpath.startswith(os.path.abspath(VIDEO_ROOT)) or not os.path.isfile(fullpath):
        return jsonify({'error': 'file not found'}), 404

    try:
        import pychromecast

        def _pick_entry(devices, name):
            if name:
                return devices.get(name)
            tv = next((v for k, v in devices.items() if 'tv' in k.lower()), None)
            return tv or next(iter(devices.values()), None)

        with _cast_lock:
            entry = _pick_entry(_cast_devices, device_name)

        if entry is None:
            found = _discover()
            with _cast_lock:
                _cast_devices.clear()
                _cast_devices.update(found)
                entry = _pick_entry(_cast_devices, device_name)

        if entry is None:
            return jsonify({'error': 'No Chromecast found on the network'}), 404

        host, port    = entry
        resolved_name = device_name or next(
            (k for k, v in _cast_devices.items() if v == entry), 'Chromecast'
        )

        cc = pychromecast.get_chromecast_from_host((host, port, None, None, resolved_name))
        cc.wait(timeout=10)
        with _active_cast_lock:
            _active_cast[resolved_name] = cc

        host_header = request.host.split(':')[0]
        video_url   = f'http://{host_header}:{HTTP_PORT}/stream/{quote(filename)}'

        cc.media_controller.play_media(video_url, 'video/mp4', current_time=position)

        with _cast_state_lock:
            _cast_state.update({
                'active':       True,
                'device':       cc.name,
                'player_state': 'BUFFERING',
                'current_time': 0,
                'duration':     0,
                'url':          video_url,
                'filename':     filename,
                'start_time':   _time.monotonic(),
                'ever_played':  False,
            })

        _sse_broadcast('cast_started', {
            'active': True, 'device': cc.name, 'url': video_url, 'filename': filename
        })
        return jsonify({'ok': True, 'device': cc.name, 'url': video_url})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cast/stop', methods=['POST'])
def cast_stop():
    """Stop playback on a Chromecast."""
    data        = request.get_json(force=True) or {}
    device_name = data.get('device', '')
    try:
        cc = _get_or_connect(device_name)
        cc.media_controller.stop()
        cc.quit_app()
        with _active_cast_lock:
            _active_cast.pop(device_name, None)
        with _cast_state_lock:
            _cast_state['active'] = False
        _sse_broadcast('cast_stopped', {'device': device_name})
        return jsonify({'ok': True, 'device': cc.name})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/cast/status')
def cast_status():
    """Return current playback position/state from the cached Chromecast connection."""
    device_name = request.args.get('device', '')
    try:
        cc = _get_or_connect(device_name)
        mc = cc.media_controller
        mc.update_status()
        s = mc.status
        return jsonify({
            'ok':           True,
            'player_state': s.player_state if s else 'UNKNOWN',
            'current_time': s.current_time if s else 0,
            'duration':     s.duration     if s else 0,
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

@app.route('/api/cast/control', methods=['POST'])
def cast_control():
    """Send a playback command to the cached Chromecast connection."""
    data        = request.get_json(force=True) or {}
    device_name = data.get('device', '')
    action      = data.get('action', '')
    value       = data.get('value')
    try:
        cc = _get_or_connect(device_name)
        mc = cc.media_controller
        if action == 'play':
            mc.play()
        elif action == 'pause':
            mc.pause()
        elif action == 'seek':
            mc.seek(float(value))
        elif action == 'seek_relative':
            mc.update_status()
            current = (mc.status.current_time or 0) if mc.status else 0
            mc.seek(max(0, current + float(value)))
        elif action == 'set_speed':
            try:
                mc.set_playback_rate(float(value))
            except Exception:
                pass
        elif action == 'mute':
            current_muted = cc.status.volume_muted if cc.status else False
            cc.set_volume_muted(not current_muted)
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

# ── URL probing and external cast ─────────────────────────────────────────────
def _strip_ansi(s):
    """Remove ANSI escape codes from a string (yt-dlp colour output)."""
    return _re.sub('\x1b\[[0-9;]*m', '', str(s))

_MAC_DEFAULT_SKEY = 'BC369F8DD3F466A2FC3F4567872BEA5D'

def _mac_decrypt_3(encoded, skey):
    """Decrypt a maccms encrypt=3 URL.

    The encoding works by:
      1. Replacing O0O0O→=, o000o→+, oo00o→/ (custom base64 alphabet)
      2. Spliting the string into 2-char chunks
      3. Stripping injected skey characters at their respective positions
      4. Joining chunks and base64-decoding the result
    """
    import base64 as _b64
    modified = encoded.replace('O0O0O', '=').replace('o000o', '+').replace('oo00o', '/')
    str_arr  = _re.findall('.{1,2}', modified)
    for k, value in enumerate(skey):
        if k < len(str_arr) and len(str_arr[k]) > 1 and str_arr[k][1] == value:
            str_arr[k] = str_arr[k][0]
    joined = ''.join(str_arr)
    pad    = (4 - len(joined) % 4) % 4
    return _b64.b64decode(joined + '=' * pad).decode('utf-8', errors='replace')

def _scrape_videos(page_url):
    """Fallback: fetch the page HTML and extract direct video URLs.

    Handles:
      • maccms mac_player_info with encrypt=3 (Chinese VOD sites)
      • <video src="..."> / <source src="...">
      • JSON strings containing .mp4 / .m3u8 / .flv URLs
    Returns a list of dicts compatible with the yt-dlp path.
    """
    import urllib.request
    import html as _html
    import json as _json
    from urllib.parse import urlparse

    headers = {
        'User-Agent':      'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    req = urllib.request.Request(page_url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read(2097152).decode('utf-8', errors='replace')

    title_m    = _re.search(r'<title[^>]*>([^<]+)</title>', raw, _re.I)
    page_title = _html.unescape(title_m.group(1).strip()) if title_m else page_url

    found_urls = []

    # ── maccms encrypt=3 ──
    mac_m = _re.search(r'var\s+mac_player_info\s*=\s*(\{.+?\})\s*(?:</script>|;)', raw, _re.DOTALL)
    if mac_m:
        try:
            info = _json.loads(mac_m.group(1))
            if str(info.get('encrypt')) == '3' and info.get('url'):
                skey      = _MAC_DEFAULT_SKEY
                from_name = info.get('from', '')
                parsed    = urlparse(page_url)
                site_base = f'{parsed.scheme}://{parsed.netloc}'
                if from_name:
                    try:
                        skin_url = f'{site_base}/static/player/{from_name}.js'
                        r2 = urllib.request.Request(skin_url, headers=headers)
                        with urllib.request.urlopen(r2, timeout=5) as pr:
                            skin_js = pr.read(50000).decode('utf-8', errors='replace')
                        ext_m = _re.search(r'https?://[^\s"\']+/player/', skin_js)
                        if ext_m:
                            ext_base = ext_m.group(0)
                            for ec_name in ('EcPlayer6.js', 'EcPlayer.js', 'player.min.js'):
                                try:
                                    ec_url = ext_base + 'js/art/' + ec_name
                                    r3 = urllib.request.Request(ec_url, headers=headers)
                                    with urllib.request.urlopen(r3, timeout=5) as er:
                                        ec_js = er.read(300000).decode('utf-8', errors='replace')
                                    sk_m = _re.search(r"skey\s*=\s*['\"]([A-Fa-f0-9]{32})['\"]", ec_js)
                                    if sk_m:
                                        skey = sk_m.group(1).upper()
                                        break
                                except Exception:
                                    continue
                    except Exception:
                        pass
                decrypted = _mac_decrypt_3(info['url'], skey)
                if decrypted.startswith('http'):
                    vod_data  = info.get('vod_data') or {}
                    vid_title = (vod_data.get('vod_name') if isinstance(vod_data, dict) else None) or page_title
                    ext       = decrypted.split('?')[0].rsplit('.', 1)[-1].lower()
                    fmt_map   = {'m3u8': 'HLS', 'mp4': 'mp4', 'webm': 'webm', 'flv': 'flv'}
                    found_urls.insert(0, ('__mac__', decrypted, vid_title, fmt_map.get(ext, ext)))
        except Exception:
            pass

    # ── plain video tags ──
    for m in _re.finditer(r'<(?:video|source)[^>]+src=["\']([^"\']+)["\']', raw, _re.I):
        found_urls.append(m.group(1))
    # ── bare URLs in page source ──
    for m in _re.finditer(r'["\']((https?://[^"\'<>\s]+?\.(?:mp4|m3u8|flv|webm|ts)(?:\?[^"\'<>\s]*)?)["\'])', raw, _re.I):
        found_urls.append(m.group(2))
    for m in _re.finditer(r'["\']((https?://[^"\'<>\s]+?(?:/video|/hls|/dash|/stream|/media)[^"\'<>\s]*\.(?:m3u8|mp4)[^"\'<>\s]*))["\']', raw, _re.I):
        found_urls.append(m.group(1))

    seen   = set()
    videos = []
    for entry in found_urls:
        if isinstance(entry, tuple) and entry[0] == '__mac__':
            _, url, vid_title, fmt = entry
            url = _html.unescape(url)
            if url not in seen:
                seen.add(url)
                videos.append({'title': vid_title, 'duration': None, 'format': fmt, 'stream_url': url})
        else:
            url = _html.unescape(entry if isinstance(entry, str) else entry)
            if url in seen:
                continue
            seen.add(url)
            ext     = url.split('?')[0].rsplit('.', 1)[-1].lower()
            fmt_map = {'m3u8': 'HLS', 'mp4': 'mp4', 'webm': 'webm', 'flv': 'flv'}
            videos.append({'title': page_title, 'duration': None, 'format': fmt_map.get(ext, ext), 'stream_url': url})

    return page_title, videos

@app.route('/api/url/probe', methods=['POST', 'GET'])
def url_probe():
    """Probe a URL with yt-dlp and return playable video entries.
    Falls back to HTML scraping when yt-dlp doesn't support the site.

    Returns JSON:
      { "page_title": "...", "videos": [
          { "title": "...", "duration": 123, "format": "1080p mp4",
            "stream_url": "https://..." },
          ...
      ]}
    """
    data     = request.get_json(force=True) or {}
    page_url = data.get('url', '').strip()
    if not page_url:
        return jsonify({'error': 'url required'}), 400
    try:
        import yt_dlp
        ydl_opts = {
            'quiet':       True,
            'no_warnings': True,
            'extract_flat': False,
            'format':      'bestvideo[ext=mp4][vcodec^=avc]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'noplaylist':  False,
            'playlistend': 20,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(page_url, download=False)
            entries    = info.get('entries') if 'entries' in info else [info]
            page_title = info.get('title') or info.get('webpage_url_basename') or page_url
            videos     = []
            for entry in (entries or []):
                if not entry:
                    continue
                stream_url = entry.get('url') or entry.get('webpage_url')
                if not stream_url:
                    continue
                fmt    = entry.get('format') or entry.get('ext') or ''
                height = entry.get('height')
                if height:
                    fmt = f'{height}p {entry.get("ext", "")}'
                videos.append({
                    'title':      entry.get('title') or entry.get('id') or 'Video',
                    'duration':   entry.get('duration'),
                    'format':     fmt,
                    'stream_url': stream_url,
                })
            if videos:
                return jsonify({'page_title': page_title, 'videos': videos})
            raise ValueError('yt-dlp found no streams')
        except Exception as ydl_err:
            ydl_msg = _strip_ansi(ydl_err)
            try:
                page_title, videos = _scrape_videos(page_url)
                if videos:
                    return jsonify({'page_title': page_title, 'videos': videos, '_source': 'scrape'})
            except Exception:
                pass
            return jsonify({'error': ydl_msg}), 500
    except Exception as e:
        return jsonify({'error': _strip_ansi(e)}), 500

@app.route('/api/cast/url', methods=['POST'])
def cast_url():
    """Cast a direct stream URL (from yt-dlp) to a Chromecast.

    Body JSON: { "stream_url": "https://...", "title": "Movie", "device": "TV" }"""
    data        = request.get_json(force=True)
    stream_url  = data.get('stream_url', '')
    title       = data.get('title', 'Video')
    device_name = data.get('device', '')

    if not stream_url:
        return jsonify({'error': 'stream_url required'}), 400

    try:
        import pychromecast

        def _pick_entry(devices, name):
            if name:
                return devices.get(name)
            tv = next((v for k, v in devices.items() if 'tv' in k.lower()), None)
            return tv or next(iter(devices.values()), None)

        with _cast_lock:
            entry = _pick_entry(_cast_devices, device_name)

        if entry is None:
            found = _discover()
            with _cast_lock:
                _cast_devices.clear()
                _cast_devices.update(found)
                entry = _pick_entry(_cast_devices, device_name)

        if entry is None:
            return jsonify({'error': 'No Chromecast found on the network'}), 404

        host, port    = entry
        resolved_name = device_name or next(
            (k for k, v in _cast_devices.items() if v == entry), 'Chromecast'
        )

        cc = pychromecast.get_chromecast_from_host((host, port, None, None, resolved_name))
        cc.wait(timeout=10)
        with _active_cast_lock:
            _active_cast[resolved_name] = cc

        mime_type = 'video/mp4'
        ext = stream_url.split('?')[0].rsplit('.', 1)[-1].lower()
        if ext in ('webm',):
            mime_type = 'video/webm'
        elif ext in ('m3u8',):
            mime_type = 'application/x-mpegURL'

        cc.media_controller.play_media(stream_url, mime_type, title=title)

        with _cast_state_lock:
            _cast_state.update({
                'active':       True,
                'device':       cc.name,
                'player_state': 'BUFFERING',
                'current_time': 0,
                'duration':     0,
                'url':          stream_url,
                'filename':     title,
                'start_time':   _time.monotonic(),
                'ever_played':  False,
            })

        _sse_broadcast('cast_started', {
            'active': True, 'device': cc.name, 'url': stream_url, 'filename': title
        })
        return jsonify({'ok': True, 'device': cc.name})

    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500

# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print(f' * Listening on http://0.0.0.0:{HTTP_PORT}')
    app.run(host='0.0.0.0', port=HTTP_PORT, threaded=True)
