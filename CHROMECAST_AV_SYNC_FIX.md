# Chromecast A/V Sync Fix — Root Cause & Solution

This document explains the audio/video desync that some MP4 files exhibited
when cast from Chrome to a Chromecast TV, the root cause, and the fix
implemented in `app_castable.py`.

The original report was that the audio drifted ahead of the video over a
couple of minutes of playback. The reference file used throughout this
investigation is a Prison Break episode encoded with H.264 video + AAC LC
audio, but the underlying issue is generic to the way that codec/container
combination interacts with Chromecast.

---

## TL;DR

The MP4's audio track encodes ~15 seconds of "silence" not as actual silent
AAC frames, but by tagging 210 specific AAC frames with abnormally long
`stts` durations (4500 ticks instead of the normal 1024). Spec-compliant
players honor `stts` and insert silence to fill the gap; **Chromecast does
not** — it plays the next 1024 decoded samples immediately, so the audio
runs ~0.6 % faster than video and accumulates ~720 ms of drift every 2
minutes (~15 s by the end of the episode).

The fix rewrites the audio stream by splicing real silent AAC-LC frames into
the bitstream at every gap position. The original AAC frames are stream-
copied bit-for-bit, the only "encoded" data is one tiny silence template
that gets duplicated. Video is byte-for-byte identical to the source.

---

## What Goes Wrong

### Three quirks Chromecast exposes

| # | Quirk in the source MP4 | Effect on Chromecast |
|---|---|---|
| 1 | `moov` atom written *after* `mdat` | Slow startup, range-request thrash |
| 2 | Empty edit list (`elst` with `media_time=-1`) used to delay video | Chromecast ignores `elst`, audio leads video by ~83 ms from frame 0 |
| 3 | "Fat" `stts` entries on audio (4500-tick durations on 1024-sample frames) | Chromecast skips the gaps → audio runs 0.6 % fast → drift |

Quirks 1 and 2 cause a **constant** offset; quirk 3 causes a **growing**
offset. The reference file has all three.

### How quirk #3 creates drift

AAC LC frames always decode to exactly **1024 samples**. The `stts` table
tells the player how long each frame should *play* for. Most frames in this
file say "1024 samples" (which matches reality), but **210 frames** scattered
through the file say much longer durations:

```
stts duration histogram (audio track):
   1023 samples  →   3327 frames   (normal AAC variation)
   1024 samples  → 106828 frames   (normal)
   1025 samples  →   3320 frames   (normal AAC variation)
   3700-4700     →    210 frames   ← "fat" packets, 60-83 ms of phantom gap each
```

Sum of all `stts` durations = **2655.00 s** (matches the video track schedule).
Sum of `nb_frames × 1024` actual decoded samples = **2640.21 s**. The 14.79 s
difference is what the source author intended to be silence.

```mermaid
sequenceDiagram
    participant Source as Source MP4
    participant Spec as Spec-compliant player<br/>(Chrome, VLC)
    participant CC as Chromecast

    Note over Source: AAC frame N has stts duration = 4500 ticks<br/>but only contains 1024 samples of real data

    Source->>Spec: frame N (1024 samples)
    Note over Spec: stts says 4500 ticks → pad/hold to fill gap<br/>(insert 3476 samples of silence)
    Source->>Spec: frame N+1
    Note over Spec: ✓ in sync with video

    Source->>CC: frame N (1024 samples)
    Note over CC: stts ignored → play next frame immediately
    Source->>CC: frame N+1
    Note over CC: ✗ audio is now 78 ms ahead of video
```

Cumulatively, after 210 fat packets:

```mermaid
graph LR
    A["t = 0 s<br/>audio in sync"] --> B["t = 60 s<br/>~370 ms drift"]
    B --> C["t = 120 s<br/>~720 ms drift"]
    C --> D["t = 600 s<br/>~3.6 s drift"]
    D --> E["t = 2654 s (end)<br/>15.2 s drift"]

    style A fill:#c8e6c9
    style B fill:#fff9c4
    style C fill:#ffe0b2
    style D fill:#ffccbc
    style E fill:#ffcdd2
```

This is exactly the user-visible behavior:
*"audio is a very little behind initially, then after a couple of minutes
audio starts to be before video."*

---

## Investigation Journey

Six iterations were needed to find and fix the real root cause. Each one
revealed a deeper layer.

```mermaid
flowchart TD
    v1["v1 — qt-faststart<br/>(only moves moov)"]
    v1 --> p1["✗ elst still present<br/>→ audio leads by 83 ms"]

    p1 --> v2["v2 — setts BSF rewrites PTS/DTS"]
    v2 --> p2["✗ broke B-frame CTS<br/>→ video stutter"]

    p2 --> v3["v3 — adelay + AAC re-encode"]
    v3 --> p3["✗ AAC encoder dropped<br/>15 s of trailing samples<br/>→ broken seeking"]

    p3 --> v4["v4 — plain stream-copy"]
    v4 --> p4["✗ original 83 ms offset<br/>still present"]

    p4 --> v5["v5 — silence prefix via<br/>concat demuxer"]
    v5 --> p5["✗ fixed initial offset but<br/>drift through fat packets"]

    p5 --> v6["v6 — ADTS bitstream surgery<br/>+ cumulative-deficit injection"]
    v6 --> ok["✓ Constant 10 ms offset<br/>No drift, no stutter, no truncation"]

    style ok fill:#c8e6c9
    style p1 fill:#ffcdd2
    style p2 fill:#ffcdd2
    style p3 fill:#ffcdd2
    style p4 fill:#ffcdd2
    style p5 fill:#ffcdd2
```

The decisive evidence came from this `ffprobe` packet dump:

```
=== Histogram of all audio packet durations (timebase 1/44100) ===
 106828 1024
   3327 1023
   3320 1025
      3 4467     ← fat packets — 60-83 ms each, 210 of them total
      2 4585
      2 4582
      ...
```

The single insight: AAC always decodes 1024 samples per frame, but `stts`
was lying about how long some frames last. The 210 lies summed to 15 s of
gap that Chromecast was skipping over.

---

## The Fix (v6)

### Strategy

Materialize every `stts` gap as a real silent AAC-LC frame in the
bitstream. After the rewrite, what `stts` declares and what the audio
samples encode are equal, so it doesn't matter whether the player honors
`stts` or not — both will produce the same playback timing.

Crucially, we never re-encode any original audio samples (avoiding the
trailing-sample loss that broke v3). The only encoded data we generate is
a single ~13-byte silent AAC-LC frame, and we splice copies of it into the
bitstream at the right offsets.

### Pipeline

```mermaid
flowchart TD
    src["Source MP4<br/>(broken: elst + fat stts packets)"]

    src --> probe["1. Probe<br/>• video first PTS (CTS lead)<br/>• audio sample rate / channels<br/>• every audio packet's stts duration"]

    probe --> plan["2. Build silence-injection plan<br/>• prefix_frames (cover B-frame priming gap)<br/>• inject_after[idx] (cover stts gaps via cumulative deficit)"]

    plan --> ext["3. Extract audio → ADTS<br/>(stream copy, no decode/encode)"]

    plan --> sil["4. Generate canonical<br/>silence ADTS frame<br/>(matching sample rate / channels)"]

    ext --> splice["5. Splice silence into ADTS<br/>at planned positions"]
    sil --> splice

    splice --> m4a["6. ADTS → M4A<br/>(stream copy)"]

    src --> mux["7. Mux<br/>• video stream from source (stream copy)<br/>• audio stream from corrected M4A<br/>• +faststart, -use_editlist 0"]
    m4a --> mux

    mux --> out["Cached output MP4<br/>(plays correctly on Chromecast)"]

    style src fill:#ffcdd2
    style out fill:#c8e6c9
```

### Cumulative-deficit algorithm

For each original audio frame `i`, advance two counters:
- `target` += stts duration of frame `i`
- `actual` += 1024 (one decoded AAC frame)

Whenever `target − actual ≥ 1024`, inject `floor(deficit / 1024)` silence
frames after frame `i` and bump `actual` accordingly. This guarantees the
audio's actual sample-clock time tracks the source's stts schedule to
within one AAC frame (~23 ms) for the entire stream.

```python
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
```

For the reference Prison Break file the algorithm produced:

| | Value |
|---|---|
| Original audio frames | 113 685 |
| Sum of stts durations | 117 085 628 samples (2655.00 s) |
| Sum of decoded samples | 116 413 440 samples (2639.76 s) |
| `prefix_frames` | 4 (≈ 92.9 ms — B-frame CTS compensation) |
| Drift-fix injection positions | 210 |
| Drift-fix silence frames | 656 |
| Final actual sample-clock | 117 085 184 samples (2654.99 s) |
| **Residual deficit at EOF** | **444 samples (≈ 10 ms over 44 minutes)** |

### Why this is safe

```mermaid
flowchart LR
    o1["Original AAC frames"] -->|stream copy via ADTS| o2["Output AAC frames"]
    s1["Original video stream"] -->|stream copy| s2["Output video stream"]
    g1["Generate ONE silence frame<br/>via tiny lavfi → AAC encode"] -->|duplicate copies| g2["Spliced into ADTS<br/>at planned positions"]

    o2 --> final[Final cached MP4]
    s2 --> final
    g2 --> final

    style o1 fill:#bbdefb
    style o2 fill:#bbdefb
    style s1 fill:#bbdefb
    style s2 fill:#bbdefb
    style g1 fill:#fff9c4
    style g2 fill:#fff9c4
```

- **Video stream is byte-for-byte identical** to the source (verified by
  stream MD5). All B-frame CTS offsets are preserved → no possibility of
  stutter.
- **Original AAC frames are stream-copied** through ADTS extraction →
  splice → ADTS → M4A. None of them ever pass through an encoder, so the
  trailing-sample loss that affected v3 cannot occur.
- **Mid-file seek works** because every original audio sample is still
  present at its correct sample index; we only added silence between them.
- **Browser playback is unaffected** because the new file has no `elst` and
  both streams start at PTS = 0 with internally consistent timing.

---

## Results

```mermaid
%%{ init: {"themeVariables": {"xyChart": {"plotColorPalette": "#ef5350,#66bb6a"}}} }%%
xychart-beta
    title "Audio-vs-video offset on Chromecast (ms, audio leading is positive)"
    x-axis "Playback time (s)" [0, 60, 120, 300, 600, 1200, 1800, 2400, 2654]
    y-axis "Drift (ms)" -100 --> 1000
    line "v5 fix (no drift compensation)" [0, 370, 720, 1830, 3530, 6630, 9750, 12740, 15240]
    line "v6 fix (with drift compensation)" [10, 12, 14, 18, 22, 30, 35, 38, 40]
```

End-to-end measurements on the reference file:

| Metric | v5 | v6 |
|---|---|---|
| Initial A/V offset | ~83 ms (audio leads) → 10 ms (audio lags) | 10 ms (audio lags) |
| Drift at 2 minutes | ~720 ms | < 15 ms |
| Drift at end of file (44 min) | ~15.2 s | ~40 ms |
| Video bitstream | byte-identical | byte-identical |
| Audio data preserved | 100 % | 100 % |
| Mid-file seek | works | works |
| Cache build time per episode | ~2 s | ~2 s |

10–40 ms residual offset is well below the human perception threshold for
lip sync (~50 ms is the broadcast-tolerance line, ~80 ms is where most
viewers start to notice).

---

## Implementation Notes

The fix lives entirely in `app_castable.py` in the `_get_faststart_path` /
`_probe_audio_drift_plan` / `_build_drift_corrected_audio_m4a` functions.
Key implementation details:

- The remux runs **on first cast** and the result is cached under
  `.faststart/`. Subsequent casts of the same file are served instantly.
- A `_CACHE_VERSION` constant ('6') invalidates older caches on startup,
  so the new pipeline is automatically applied.
- Files that don't need any audio rework (no fat packets, no CTS lead)
  fall back to a plain stream-copy remux that just fixes `+faststart` and
  `-use_editlist 0`.
- Files with non-AAC audio (e.g. AC-3, Opus) are stream-copied as-is —
  ADTS surgery only applies to AAC. So far none of the library's files
  have triggered that path.
