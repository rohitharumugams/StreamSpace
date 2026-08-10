#!/usr/bin/env python3
"""CLI: stereo + vision + transcript → content/hls/<name>/captions.json

  python -m captions.build --video dialogue_demo
  python -m captions.build --input content/source/clip.mp4 --name clip --asr whisper
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from captions.asr import TranscriptCue, transcribe_whisper
from captions.fuse import fuse_captions
from captions.schema import CaptionEvent
from captions.stereo import analyze_stereo, extract_wav
from captions.subtitles import load_subtitles
from captions.vision import analyze_video_speakers, dump_visual_frames

HLS_ROOT = ROOT / "content" / "hls"
SOURCE_ROOT = ROOT / "content" / "source"
WORK_ROOT = ROOT / "content" / "captions_work"


def load_script_cues(path: Path) -> list[TranscriptCue]:
    data = json.loads(path.read_text())
    return [
        TranscriptCue(
            start=float(item["start"]),
            end=float(item["end"]),
            text=str(item["text"]),
            confidence=1.0,
        )
        for item in data
    ]


def default_sound_events() -> list[CaptionEvent]:
    return [
        CaptionEvent(
            id="sound-001",
            start=13.2,
            end=14.0,
            text="[PHONE RINGS]",
            kind="sound",
            speaker=None,
            direction="RIGHT",
            confidence=0.9,
            fusion_source="script",
        )
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build smart captions sidecar")
    parser.add_argument("--video", default="dialogue_demo", help="HLS package name")
    parser.add_argument("--input", type=Path, default=None, help="Source media path")
    parser.add_argument("--name", default=None, help="Output package/video name")
    parser.add_argument(
        "--asr",
        choices=["script", "whisper", "subtitles"],
        default="script",
        help="Transcript source",
    )
    parser.add_argument(
        "--subtitles",
        type=Path,
        default=None,
        help="Subtitle file (.srt / .vtt / .cues.json)",
    )
    parser.add_argument("--whisper-model", default="base")
    parser.add_argument("--no-vision", action="store_true", help="Skip vision analysis")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output captions.json (default: content/hls/<name>/captions.json)",
    )
    args = parser.parse_args()

    name = args.name or args.video
    source = args.input
    if source is None:
        for candidate in [
            SOURCE_ROOT / f"{name}.mp4",
            SOURCE_ROOT / "dialogue_demo.mp4",
            SOURCE_ROOT / "sample.mp4",
        ]:
            if candidate.exists():
                source = candidate
                break
    if source is None or not source.exists():
        print(f"Source video not found for '{name}'", file=sys.stderr)
        return 1

    # Grab a .srt/.vtt/.cues.json next to the source if one exists.
    subs_path = args.subtitles
    if subs_path is None:
        for candidate in [
            source.with_suffix(".srt"),
            source.with_suffix(".vtt"),
            source.with_suffix(".cues.json"),
            SOURCE_ROOT / f"{name}.srt",
            SOURCE_ROOT / f"{name}.vtt",
            SOURCE_ROOT / f"{name}.cues.json",
        ]:
            if candidate.exists():
                subs_path = candidate
                break

    work = WORK_ROOT / name
    work.mkdir(parents=True, exist_ok=True)
    wav = work / "audio.wav"
    print(f"Extracting stereo audio from {source}…")
    extract_wav(source, wav)

    print("Analyzing stereo spatial balance…")
    windows = analyze_stereo(wav)

    cues: list[TranscriptCue]
    generated_by = ["stereo"]
    if args.asr == "whisper":
        print(f"Running Whisper ({args.whisper_model})…")
        cues = transcribe_whisper(wav, model_size=args.whisper_model)
        generated_by.append("whisper")
    else:
        # script / subtitles path
        if subs_path is None or not subs_path.exists():
            print(
                "No cues/subtitles found. Drop a .srt/.vtt/.cues.json next to the video "
                "or pass --subtitles / use --asr whisper",
                file=sys.stderr,
            )
            return 1
        print(f"Loading transcript from {subs_path}…")
        cues = load_subtitles(subs_path)
        generated_by.append(f"subtitles:{subs_path.suffix.lstrip('.') or 'json'}")

    if not cues:
        print("Subtitle/transcript produced zero cues.", file=sys.stderr)
        return 1

    visual_frames = []
    if not args.no_vision:
        sample_times: set[float] = set()
        for c in cues:
            sample_times.add(round(c.start, 3))
            sample_times.add(round((c.start + c.end) / 2, 3))
            sample_times.add(round(c.end, 3))
            # Offsets help when the mid frame is a cut or blurry.
            mid = (c.start + c.end) / 2
            sample_times.add(round(max(0.0, mid - 0.35), 3))
            sample_times.add(round(mid + 0.35, 3))
        sample_times.update({0.5, 2.0, 6.0, 12.0, 16.0, 20.0})
        sample_list = sorted(sample_times)
        print(f"Detecting visual speaker candidates ({len(sample_list)} frames)…")
        visual_frames = analyze_video_speakers(source, sample_times=sample_list)
        dump_visual_frames(visual_frames, work / "vision_frames.json")
        generated_by.append("vision")
        n_det = sum(len(f.detections) for f in visual_frames)
        print(f"  vision: {n_det} detections across {len(visual_frames)} frames")

    sound_events = default_sound_events() if name == "dialogue_demo" else []
    if sound_events:
        generated_by.append("sound-events")

    track = fuse_captions(
        video_name=name,
        cues=cues,
        windows=windows,
        visual_frames=visual_frames,
        sound_events=sound_events,
        generated_by=generated_by + ["fuse", "placement"],
    )

    # Scripted names for identity; fused direction/placement stay as-is.
    cues_path = source.with_suffix(".cues.json")
    if cues_path.exists():
        script = json.loads(cues_path.read_text())
        by_text = {item["text"]: item for item in script}
        for event in track.events:
            if event.kind != "speech":
                continue
            meta = by_text.get(event.text)
            if meta:
                event.speaker = meta["speaker"]

    out = args.out or (HLS_ROOT / name / "captions.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(track.model_dump_json(indent=2) + "\n")
    print(f"Wrote {out} ({len(track.events)} events)")

    windows_out = work / "stereo_windows.json"
    windows_out.write_text(json.dumps([w.__dict__ for w in windows], indent=2) + "\n")
    print(f"Wrote {windows_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
