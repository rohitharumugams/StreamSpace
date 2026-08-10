#!/usr/bin/env python3
"""Generate a short stereo dialogue demo for spatial captions.

Uses macOS `say` for left/right speakers, then FFmpeg to mux video + stereo audio.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Timed script: (start_s, speaker, side, text, voice)
SCRIPT = [
    (1.0, "JOHN", "left", "Where are you going?", "Alex"),
    (4.0, "SARA", "right", "Over to the window.", "Samantha"),
    (7.5, "JOHN", "left", "Wait for me.", "Alex"),
    (10.5, "SARA", "right", "I'm coming.", "Samantha"),
    (14.0, "JOHN", "left", "Did you hear that?", "Alex"),
    (17.0, "SARA", "right", "It sounded like a phone.", "Samantha"),
]


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def say_to_wav(text: str, voice: str, out_wav: Path) -> float:
    aiff = out_wav.with_suffix(".aiff")
    run(["say", "-v", voice, "-o", str(aiff), text])
    run(["ffmpeg", "-y", "-i", str(aiff), str(out_wav)])
    aiff.unlink(missing_ok=True)
    # probe duration
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            str(out_wav),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return float(json.loads(probe.stdout)["format"]["duration"])


def build_stereo_track(work: Path, duration: float) -> Path:
    """Create a stereo wav with left/right panned speech at scripted times."""
    pieces = []
    cues = []
    for idx, (start, speaker, side, text, voice) in enumerate(SCRIPT):
        wav = work / f"line_{idx}.wav"
        line_dur = say_to_wav(text, voice, wav)
        pieces.append((start, side, wav, line_dur))
        cues.append(
            {
                "start": start,
                "end": round(start + line_dur, 3),
                "speaker": speaker,
                "side": side.upper() if side != "center" else "CENTER",
                "text": text,
            }
        )

    # Build filter: anullsrc stereo base + adelay + pan each line into L or R
    # Simpler approach: generate left and right mono mixes separately, then join.
    left_inputs = []
    right_inputs = []
    filter_parts = []
    input_args: list[str] = []

    # silent bases
    filter_parts.append(f"anullsrc=r=16000:cl=mono:d={duration}[lbase]")
    filter_parts.append(f"anullsrc=r=16000:cl=mono:d={duration}[rbase]")

    for idx, (start, side, wav, _dur) in enumerate(pieces):
        input_args.extend(["-i", str(wav)])
        delay_ms = int(start * 1000)
        filter_parts.append(
            f"[{idx}:a]adelay={delay_ms}|{delay_ms},apad=whole_dur={duration}[a{idx}]"
        )
        if side == "left":
            left_inputs.append(f"[a{idx}]")
        else:
            right_inputs.append(f"[a{idx}]")

    # Mix left
    if left_inputs:
        n = len(left_inputs) + 1
        filter_parts.append(
            "[lbase]" + "".join(left_inputs) + f"amix=inputs={n}:normalize=0[left]"
        )
    else:
        filter_parts.append("[lbase]anull[left]")

    if right_inputs:
        n = len(right_inputs) + 1
        filter_parts.append(
            "[rbase]" + "".join(right_inputs) + f"amix=inputs={n}:normalize=0[right]"
        )
    else:
        filter_parts.append("[rbase]anull[right]")

    filter_parts.append("[left][right]join=inputs=2:channel_layout=stereo[aout]")
    filt = ";".join(filter_parts)

    stereo = work / "stereo.wav"
    cmd = [
        "ffmpeg",
        "-y",
        *input_args,
        "-filter_complex",
        filt,
        "-map",
        "[aout]",
        "-t",
        str(duration),
        str(stereo),
    ]
    run(cmd)
    (work / "script_cues.json").write_text(json.dumps(cues, indent=2) + "\n")
    return stereo


def build_video(out: Path, duration: float, stereo: Path, work: Path) -> None:
    # Visual: test pattern + left/right panels (no drawtext — may be unavailable)
    video_only = work / "video_only.mp4"
    filter_complex = (
        f"testsrc2=size=1280x720:rate=30:duration={duration}[bg];"
        f"color=c=0x1b4332:s=320x400:d={duration}:r=30[left];"
        f"color=c=0x1d3557:s=320x400:d={duration}:r=30[right];"
        f"[bg][left]overlay=80:160[tmp];"
        f"[tmp][right]overlay=880:160[vout]"
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-profile:v",
            "main",
            "-an",
            str(video_only),
        ]
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video_only),
            "-i",
            str(stereo),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            str(out),
        ]
    )
    # Persist cues next to source for caption builder fallback
    cues_src = work / "script_cues.json"
    cues_dst = out.with_suffix(".cues.json")
    cues_dst.write_text(cues_src.read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate stereo dialogue demo video")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "content" / "source" / "dialogue_demo.mp4",
    )
    parser.add_argument("--duration", type=float, default=22.0)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="dialogue_demo_") as tmp:
        work = Path(tmp)
        print("Synthesizing speech lines…")
        stereo = build_stereo_track(work, args.duration)
        print("Muxing video…")
        build_video(args.out, args.duration, stereo, work)

    print(f"Wrote {args.out}")
    print(f"Wrote {args.out.with_suffix('.cues.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
