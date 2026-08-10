# VideoStreaming

Local adaptive HLS player with a network-trace throttle, a handful of ABR controllers (including a risk-aware one), and a spatial caption pipeline that tries to put speaker labels and direction cues back into the subtitle track.

This started as an ABR systems project. Captions came later once the streaming path was solid enough to demo against.

---

## What you get

**Streaming**
- FFmpeg packaging into multi-bitrate HLS (fMP4 segments, typically 360p / 480p / 720p, 1080p if the source is tall enough)
- FastAPI server that serves the player, playlists, and segment bytes
- Trace-driven bandwidth throttle on media segments (playlists stay unthrottled so the player doesn't stall on `.m3u8` fetches)
- Browser player on hls.js with manual level control for custom ABR
- Offline ABR × trace simulator that mirrors the browser controllers in Python

**Captions**
- Stereo L/R energy → LEFT / CENTER / RIGHT
- Vision speaker candidates (OpenCV Haar faces, or colored panels on the synthetic demo)
- Per-cue AV fusion + placement that tries not to sit on faces
- Player modes: off / standard / speaker / spatial / full
- Accuracy eval against `.cues.json` ground truth
- Short A/B study UI at `/study`

---

## Quick start

Needs: Python 3.11+, FFmpeg / ffprobe, a modern browser.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# optional one-shot: builds demo media, captions, then starts the server
./scripts/run_demo.sh
```

Or step through it yourself:

```bash
python scripts/generate_dialogue_demo.py
python scripts/package_hls.py --input content/source/dialogue_demo.mp4 --name dialogue_demo
python -m captions.build --video dialogue_demo
python -m captions.eval_accuracy --video dialogue_demo

uvicorn server.main:app --reload --port 8080
```

Then open:
- Player: http://127.0.0.1:8080
- Caption study: http://127.0.0.1:8080/study

Pick `dialogue_demo`, set captions to **Spatial** or **Full accessibility**, and turn on a trace like `volatile` with the **risk** ABR if you want the interesting streaming behavior.

`make demo` / `make smoke` / `make abr` / `make captions` / `make report` wrap the common commands.

---

## Repo layout

```text
captions/          stereo, vision, fusion, placement, build + accuracy
content/
  inbox/           drop your own video + .srt/.vtt here
  source/          originals after ingest / demo generation
  hls/<name>/      master.m3u8, rendition folders, captions.json, manifest.json
  captions_work/   intermediate stereo/vision dumps + accuracy.json
  study_results/   saved /study sessions
player/            index.html, hls.js ABR, caption overlay, study UI
server/            FastAPI + throttle
scripts/           FFmpeg helpers, ingest, report generation
traces/            one Mbps sample per line (one second each)
eval/              Python ABR ports + trace-driven simulator
docs/              writeups / generated results
```

---

## Architecture

Two mostly-independent pipelines share the same packaged HLS content and the same FastAPI process.

```text
                    ┌──────────────────────────────────────┐
  source.mp4 ──────►│  package_hls.py (FFmpeg ladder)      │
                    │  content/hls/<name>/{360p,480p,...}  │
                    └──────────────┬───────────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                    ▼                    ▼
     browser player         caption build          offline eval
     (hls.js + ABR)         (stereo/vision/        (eval.simulator
      GET /hls/...           fuse → captions.json)  reads segment sizes
      optionally throttled                          + traces)
              │                    │
              ▼                    ▼
         overlay +                 player fetches
         telemetry                 /api/videos/.../captions.json
```

### Streaming path

1. `scripts/package_hls.py` probes the source, picks ladder rungs that fit the height, and encodes each rendition with `-f hls` (fMP4 init + `seg_*.m4s`). It also writes `manifest.json` with per-rendition bandwidth and segment duration so the offline eval doesn't have to re-parse playlists.
2. `server/main.py` lists packages under `content/hls/`, serves `master.m3u8` + segments at `/hls/...`, and exposes throttle + caption/study APIs.
3. When throttle is on, only media suffixes (`.m4s`, `.ts`, `.mp4`, …) go through `throttled_bytes()`. Rate comes from `server/throttle.py`: one Mbps sample per wall-clock second into the active trace, optionally looping. Playlists skip the throttle on purpose.
4. `player/player.js` loads the master playlist with hls.js. For non-`hls` ABR modes it disables auto level selection and calls `abr.decide(...)` after each `FRAG_LOADED`, setting `hls.loadLevel` / `hls.nextLevel`.
5. Throughput for ABR is an EWMA (`α = 0.3`) of per-fragment `(bytes * 8) / download_s`, plus a short window (last 8 samples) for stdev and a half-window trend used by risk-aware ABR.

### Caption path

```text
 video ─┬─ ffmpeg → stereo wav → sliding-window L/R energy → balance ∈ [-1,1]
        ├─ OpenCV frames @ cue times → faces (Haar) or demo panels
        └─ transcript (script cues / .srt|.vtt / Whisper)
                 │
                 ▼
            fuse per cue  →  direction + speaker + (x,y)
                 │
                 ▼
            content/hls/<name>/captions.json
                 │
                 ▼
            player overlay (mode-dependent formatting)
```

`captions/build.py` is the CLI entry. Work files land in `content/captions_work/<name>/` (`audio.wav`, `stereo_windows.json`, `vision_frames.json`). Final track goes next to the HLS package.

---

## ABR controllers

Implemented twice: JS for the live player (`player/abr.js`), Python for offline runs (`eval/abr.py`). Same decision logic.

| Name | Idea |
|------|------|
| `throughput` | Pick highest level whose bitrate ≤ `ewma * 0.8` |
| `buffer` | Step down below 4s buffer, step up above 12s |
| `hybrid` | Throughput pick gated by buffer bands (panic at &lt;2s → level 0; reservoir before upgrades) |
| `risk` | Conservative estimate `mean − z·std` (z grows with CV, low buffer, negative trend), then underrun risk `est_download / buffer`. Upgrades need healthy buffer, low hold counter, and mild volatility |
| `fixed` / `hls` | Locked level, or hand control back to hls.js |

Risk-aware ABR also keeps a short `hold` so it doesn't bounce levels every segment when the trace is noisy. Under `volatile` / `spike_drop` it usually sits lower than pure throughput; under `congested` everyone collapses toward the bottom rung.

Offline experiments:

```bash
python -m eval.run_experiments --abr throughput,hybrid,risk --trace congested,spike_drop,volatile
# or
make abr
```

The simulator (`eval/simulator.py`) walks segment-by-segment: decide level → integrate download time against the 1 Hz trace → drain/grow buffer → record rebuffer / switches / bitrate. Segment byte sizes come from the real packaged files via `eval/catalog.py`.

Traces live in `traces/*.txt` (Mbps per second). Included: `stable`, `volatile`, `congested`, `spike_drop`, `sudden_drop`, `gradual_degradation`, `recovery`.

---

## Spatial captions — how decisions are made

### Stereo (`captions/stereo.py`)

- Extract 16 kHz stereo WAV.
- 0.5s windows, 0.25s hop.
- Balance = `(E_r − E_l) / (E_r + E_l)`. Deadzone `±0.08` → CENTER (film dialogue is usually only mildly panned, so the deadzone stays tight).
- For a cue span, energy-weighted average of overlapping windows (not majority vote).
- Continuous `x = 0.5 + 0.35 * clamp(balance / 0.22)` for placement when vision is weak.

### Vision (`captions/vision.py`)

- Sample frames at cue start / mid (±0.35s) / end, plus a few fixed times.
- Haar frontal + profile cascades first; if nothing fires, look for the green/blue panels used by `dialogue_demo`.
- Greedy NMS on normalized boxes.
- For each cue, gather nearby detections, bucket by track / coarse x-bin, then `pick_visual_speaker` scores confidence + proximity to stereo-derived x + side agreement + size. Faces get a small bonus over panels.

### Fusion (`captions/fuse.py`)

`resolve_direction` is deliberately asymmetric:

- No vision → stereo wins.
- Stereo and vision agree → blend confidence, source `av-agree`.
- Stereo is CENTER / near-zero balance → trust the face (`vision`).
- Vision is CENTER but stereo leans → keep stereo for the arrow (`stereo-bias`).
- Hard conflict → still park on the chosen face (`av-select`).

Speaker labels default to `SPEAKER L/R` by side; if a `.cues.json` sits next to the source, build overwrites names from that script while keeping fused direction/placement.

### Placement (`captions/placement.py`)

Two strategies:

- **Slot search** (`place_caption`): discrete lower-third / side candidates plus a continuous slot at `preferred_x`. Score = prior + proximity − overlap with obstacle boxes (other faces/panels).
- **Near speaker** (`place_near_speaker`): when a face/panel was chosen, bias under the chin (`y ≈ face_bottom + pad`), try a few y offsets, treat the speaker box itself as an obstacle so the text doesn't cover it.

Eval compares average overlap of smart boxes vs a naive “drop it on the speaker side mid-frame” baseline (`captions/eval_accuracy.py`).

### Player rendering (`player/captions.js`)

Modes:

| Mode | Behavior |
|------|----------|
| `standard` | Centered text only |
| `speaker` | `NAME: text`, still centered |
| `spatial` | Arrow + name, absolute `(x,y)` from the track |
| `full` | Spatial speech + sound events like `[PHONE RINGS] →` |

Sound events are currently scripted for `dialogue_demo` only (see `default_sound_events` in `build.py`).

### Caption JSON shape

```json
{
  "video": "dialogue_demo",
  "generated_by": ["stereo", "subtitles:json", "vision", "fuse", "placement"],
  "events": [
    {
      "id": "speech-000",
      "start": 1.2,
      "end": 3.0,
      "text": "Where are you going?",
      "kind": "speech",
      "speaker": "JOHN",
      "direction": "LEFT",
      "x": 0.22,
      "y": 0.78,
      "align": "LEFT",
      "stereo_direction": "LEFT",
      "vision_direction": "LEFT",
      "fusion_source": "av-agree",
      "confidence": 0.91
    }
  ]
}
```

---

## Using your own video

Drop files in the inbox:

```text
content/inbox/myclip.mp4
content/inbox/myclip.srt          # or .vtt / .cues.json
```

or a folder:

```text
content/inbox/myclip/
  video.mp4
  subs.srt
```

Then:

```bash
python scripts/ingest.py
# copies → content/source/, packages HLS, runs captions.build
```

No subtitle file → ingest tries Whisper (`pip install openai-whisper`). You can also build manually:

```bash
python -m captions.build --video myclip --asr whisper
# or
python -m captions.build --video myclip --asr subtitles --subtitles path/to/file.srt
```

`--no-vision` skips OpenCV if you only care about stereo arrows.

---

## Caption A/B study

`/study` loads ground-truth cues + captions, builds paired trials (same line once in standard, once in spatial), and records speaker / side guesses. Results POST to `/api/study/results` and land in `content/study_results/`.

```bash
python scripts/summarize_study.py
python scripts/simulate_study_session.py   # synthetic session for tooling only
```

Don't treat `sim-*` sessions as real user data.

---

## HTTP API (short)

| Route | What |
|-------|------|
| `GET /` | Player |
| `GET /study` | Caption study UI |
| `GET /api/videos` | Packaged HLS titles |
| `GET /api/videos/{name}/manifest.json` | Ladder metadata |
| `GET /api/videos/{name}/captions.json` | Spatial track |
| `GET /hls/{name}/...` | Playlists + segments (segments may be throttled) |
| `GET/POST /api/throttle` | Enable/disable a named trace |
| `GET /api/traces` | Available Mbps traces |
| `GET /api/study/trials` | Study cues for a video |
| `POST /api/study/results` | Persist a session |

---

## Reports & checks

```bash
python scripts/smoke_test.py
python scripts/generate_report.py --refresh-abr --refresh-captions
```

Generated tables live in `docs/RESULTS.md`. Longer narrative notes in `docs/PROJECT_SUMMARY.md`.

On `dialogue_demo`, caption eval typically hits perfect direction/speaker/AV agreement, with smart placement overlap near ~0.002 vs ~0.600 for the naive baseline. ABR numbers move with the traces you run — risk trades average bitrate for fewer aggressive upgrades when the pipe is jumpy.

---

## Dependencies

Core (`requirements.txt`): FastAPI, uvicorn, aiofiles, pydantic, numpy, opencv-python-headless.

Optional: `openai-whisper` for ASR when you don't have subtitles.

System: FFmpeg + ffprobe on `PATH`. The dialogue demo generator also uses macOS `say` for speech audio; on other platforms generate or bring your own source file.

---

## Notes / limitations

- Vision is Haar + demo panels, not a production speaker-ID model. Real multi-face scenes will be messier.
- Sound-effect captions are demo-scripted, not classified from audio.
- Risk ABR parameters were tuned against the included traces; expect to retune for other ladders or segment durations.
- Throttle is server-side and cooperative — it doesn't model latency, loss, or CDN quirks, just goodput.
