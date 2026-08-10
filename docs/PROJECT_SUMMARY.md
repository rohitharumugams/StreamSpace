# Project notes

Built in two layers: get a real adaptive stream working end-to-end, then hang spatial captions off the same packages.

## Streaming

- Ladder packaging via FFmpeg (`scripts/package_hls.py`) → fMP4 HLS under `content/hls/`
- FastAPI serves playlists + segments; `server/throttle.py` rate-limits segment bodies from Mbps traces
- Player (`player/player.js`) drives hls.js with custom ABR (`throughput`, `buffer`, `hybrid`, `risk`, plus fixed / native)
- Offline twin of those controllers in `eval/` so you can sweep ABR × trace without clicking around

Risk ABR is the interesting one: it uses EWMA mean/std + trend, shrinks the budget when CV is high or buffer is thin, and refuses upgrades until things look calm. On the included volatile traces it sits below pure throughput; on congested traces everyone ends up on the safe floor while fixed-high rebuffers.

## Captions

- Stereo ICLD-style balance → LEFT / CENTER / RIGHT (`captions/stereo.py`)
- OpenCV Haar faces (or green/blue panels on `dialogue_demo`) (`captions/vision.py`)
- Per-cue fusion + face-aware placement (`captions/fuse.py`, `captions/placement.py`)
- Modes in the overlay: standard / speaker / spatial / full
- Accuracy vs `.cues.json`: `python -m captions.eval_accuracy`
- Short A/B harness at `/study`

On `dialogue_demo` (scripted stereo + panels) direction/speaker/AV agreement are clean; smart placement overlap is ~0.002 vs ~0.600 naive. That's a controlled demo — real footage will need better vision / ASR.

## Demo

```bash
./scripts/run_demo.sh
# player http://127.0.0.1:8080
# study  http://127.0.0.1:8080/study
```

Numbers refresh into `docs/RESULTS.md` via `python scripts/generate_report.py --refresh-abr --refresh-captions`.

## Still rough

- Study UI has almost no real participants yet; ignore `sim-*` sessions when claiming user results
- Haar ≠ speaker diarization; swap in a real multi-speaker scene + Whisper when you want a harder eval
- Optional: record a short screen capture of player + study for the writeup
