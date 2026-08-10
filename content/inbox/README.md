# Inbox

Drop a video (and ideally matching subs) here, then:

```bash
python scripts/ingest.py
```

That copies into `content/source/`, packages HLS, and runs the caption build.

## Flat

```text
content/inbox/
  myclip.mp4
  myclip.srt      # .vtt or .cues.json also fine
```

## Folder

```text
content/inbox/myclip/
  video.mp4
  subs.srt
```

No subtitle file → ingest tries Whisper (`pip install openai-whisper`).

After it finishes, refresh the player and pick `myclip`.
