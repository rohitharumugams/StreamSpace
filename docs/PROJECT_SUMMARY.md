# Project Summary

## Goal

Build a real adaptive streaming system, then add **spatial smart captions** that preserve speaker identity and coarse sound direction lost by normal subtitles.

## What’s implemented

### Adaptive streaming
- Multi-bitrate HLS packaging (360p / 480p / 720p)
- Segment streaming server + browser player
- Network trace throttle (`stable`, `volatile`, `congested`, `spike_drop`, …)
- ABR controllers: throughput, buffer, hybrid, **risk-aware**
- Offline evaluation: `python -m eval.run_experiments`

### Spatial smart captions
- Stereo L/C/R analysis
- Vision speaker candidates (faces or demo panels)
- Audio-visual fusion → speaker + direction
- Placement engine avoiding faces/panels
- Player modes: standard / speaker / spatial / full
- Accuracy eval: `python -m captions.eval_accuracy`
- Caption A/B study UI: `/study`

## Demo path

```bash
./scripts/run_demo.sh
```

- Player: http://127.0.0.1:8080
- Study: http://127.0.0.1:8080/study

## Measured results (dialogue_demo)

| Metric | Result |
|--------|--------|
| Direction accuracy | 100% |
| Speaker accuracy | 100% |
| AV agreement | 100% |
| Placement overlap (smart vs naive) | 0.002 vs 0.600 |

Risk-aware ABR trades bitrate for stability under volatile traces; on `congested` it matches baselines at the safe floor while `fixed-high` rebuffers heavily.

## Architecture

```text
Source video
   ├─ FFmpeg → HLS renditions → ABR player + network simulator
   └─ Captions pipeline
        ├─ ASR / script cues
        ├─ Stereo analysis
        ├─ Vision detection
        ├─ AV fusion
        └─ Placement → captions.json → overlay / study
```

## Suggested next polish

- Run `/study` with real participants and refresh `docs/RESULTS.md`
- Swap in a real multi-speaker stereo scene + Whisper ASR
- Optional: commit a short recorded demo GIF/video of player + study
