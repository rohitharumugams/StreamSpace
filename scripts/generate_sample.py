#!/usr/bin/env python3
"""Tiny lavfi stereo test clip → content/source/sample.mp4 (no drawtext needed)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "content" / "source" / "sample.mp4"


def build_ffmpeg_cmd(out: Path, duration: float, fps: int) -> list[str]:
    # Visual: animated test pattern + left/right speaker panels.
    # Audio: 440Hz left, 660Hz right (useful later for stereo spatial demos).
    filter_complex = (
        f"testsrc2=size=1280x720:rate={fps}:duration={duration}[bg];"
        f"color=c=0x1b4332:s=320x400:d={duration}:r={fps}[left];"
        f"color=c=0x1d3557:s=320x400:d={duration}:r={fps}[right];"
        f"[bg][left]overlay=80:160[tmp];"
        f"[tmp][right]overlay=880:160[vout];"
        f"sine=frequency=440:sample_rate=48000:duration={duration}[aL];"
        f"sine=frequency=660:sample_rate=48000:duration={duration}[aR];"
        f"[aL][aR]join=inputs=2:channel_layout=stereo[aout]"
    )
    return [
        "ffmpeg",
        "-y",
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-profile:v",
        "main",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        str(out),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a sample source video")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--duration", type=float, default=30.0, help="seconds")
    parser.add_argument("--fps", type=int, default=30)
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_ffmpeg_cmd(args.out, args.duration, args.fps)
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"ffmpeg failed with exit code {exc.returncode}", file=sys.stderr)
        raise SystemExit(exc.returncode)
