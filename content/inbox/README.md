# Drop your media here

Put a video and matching subtitle file in this folder, then run:

```bash
python scripts/ingest.py
```

## Layout A (simplest)

```text
content/inbox/
  myclip.mp4
  myclip.srt      # or myclip.vtt
```

## Layout B (folder)

```text
content/inbox/myclip/
  video.mp4
  subs.srt
```

Supported subtitles: `.srt`, `.vtt`, `.cues.json`

If no subtitle file is present, ingest will try Whisper ASR (requires `openai-whisper`).

After ingest, open the player and select your video name.
