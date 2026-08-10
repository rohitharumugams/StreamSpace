# Adaptive Video Streaming + Spatial Smart Captions

Systems project: adaptive bitrate streaming, then spatial smart captions on top.

## Current status

**AV fusion captions:** stereo L/C/R + visual speaker-candidate detection fused into spatial captions, with accuracy evaluation.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Dialogue demo (macOS `say` + stereo pan) → HLS → captions
python scripts/generate_dialogue_demo.py
python scripts/package_hls.py --input content/source/dialogue_demo.mp4 --name dialogue_demo
python -m captions.build --video dialogue_demo
python -m captions.eval_accuracy --video dialogue_demo

# Server
uvicorn server.main:app --reload --port 8080
```

Open [http://127.0.0.1:8081](http://127.0.0.1:8081) (or `:8080` if you restarted there). Select **dialogue_demo**, set captions to **Spatial** or **Full accessibility**. Caption A/B study: [http://127.0.0.1:8081/study](http://127.0.0.1:8081/study).

### One-command demo

```bash
./scripts/run_demo.sh
```

### Reports & checks

```bash
python scripts/smoke_test.py
python scripts/simulate_study_session.py   # optional tooling demo data
python scripts/summarize_study.py
python scripts/generate_report.py --refresh-abr --refresh-captions
```

See [docs/RESULTS.md](docs/RESULTS.md) and [docs/PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md).

### Caption pipeline

```text
Video ─┬─► Stereo analysis ─► LEFT/CENTER/RIGHT
       ├─► Vision detection ─► speaker candidates (faces or panels)
       └─► ASR / script cues ─► transcript
                │
                ▼
           AV fusion
                │
                ▼
        captions.json → player overlay
```

### Caption modes

| Mode | Example |
|------|---------|
| Standard | `Where are you going?` |
| Speaker-aware | `JOHN: Where are you going?` |
| Spatial | `← JOHN: Where are you going?` |
| Full | speech + `[PHONE RINGS] →` |

### Use your own video + subtitles

Drop files into the inbox:

```text
content/inbox/myclip.mp4
content/inbox/myclip.srt    # or .vtt
```

Then run:

```bash
python scripts/ingest.py
```

Open the player and select **myclip**. See `content/inbox/README.md`.

If no subtitle file is present, ingest tries Whisper (`pip install openai-whisper`).

### ABR evaluation

```bash
python -m eval.run_experiments --abr throughput,hybrid,risk --trace congested,spike_drop,volatile
```

## Layout

```text
captions/         # stereo, vision, ASR hook, fusion, build + accuracy eval
content/inbox/    # DROP your video + .srt/.vtt here, then run scripts/ingest.py
content/source/   # ingested originals
content/hls/      # HLS packages + captions.json
player/           # player, ABR, caption overlay, study UI
server/           # FastAPI + network throttle
scripts/          # FFmpeg / ingest / demo helpers
traces/           # Mbps network traces
eval/             # ABR experiment runner
docs/             # project + results writeups
```

## Roadmap

1. Stream video ✅
2. Multi-quality + telemetry ✅
3. Network simulator ✅
4. ABR baselines ✅
5. Evaluation framework ✅
6. Risk-aware ABR ✅
7. Smart captions MVP ✅
8. Vision speaker detection + AV fusion ✅
9. Caption placement engine ✅
10. Caption A/B user-study harness ✅

See [docs/PROJECT_SUMMARY.md](docs/PROJECT_SUMMARY.md).

## API

| Endpoint | Description |
|----------|-------------|
| `GET /` | Player UI |
| `GET /api/videos` | Packaged videos |
| `GET /api/videos/{name}/captions.json` | Spatial caption track |
| `GET /hls/{name}/...` | HLS (segments may be throttled) |
| `GET/POST /api/throttle` | Network trace simulator |
