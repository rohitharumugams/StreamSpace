#!/usr/bin/env python3
"""Transcode a source video into multi-bitrate HLS (fMP4) packages.

Produces:
  content/hls/<name>/
    master.m3u8
    manifest.json
    360p/ ...
    480p/ ...
    720p/ ...
    1080p/ ...  (if source tall enough)
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# height, video bitrate (kbps), audio bitrate (kbps), maxrate, bufsize
RENDITIONS = [
    {"name": "360p", "height": 360, "v_bitrate": 800, "a_bitrate": 96, "maxrate": 856, "bufsize": 1200},
    {"name": "480p", "height": 480, "v_bitrate": 1400, "a_bitrate": 128, "maxrate": 1498, "bufsize": 2100},
    {"name": "720p", "height": 720, "v_bitrate": 2800, "a_bitrate": 128, "maxrate": 2996, "bufsize": 4200},
    {"name": "1080p", "height": 1080, "v_bitrate": 5000, "a_bitrate": 192, "maxrate": 5350, "bufsize": 7500},
]


def ffprobe_json(path: Path) -> dict:
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def source_height(probe: dict) -> int:
    for stream in probe.get("streams", []):
        if stream.get("codec_type") == "video":
            return int(stream["height"])
    raise ValueError("No video stream found")


def source_duration(probe: dict) -> float:
    fmt = probe.get("format", {})
    if "duration" in fmt:
        return float(fmt["duration"])
    for stream in probe.get("streams", []):
        if "duration" in stream:
            return float(stream["duration"])
    raise ValueError("Could not determine duration")


def even_width(height: int, src_w: int, src_h: int) -> int:
    width = int(round(src_w * (height / src_h)))
    if width % 2:
        width += 1
    return width


def encode_rendition(
    source: Path,
    out_dir: Path,
    rendition: dict,
    width: int,
    segment_seconds: float,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    playlist = out_dir / "playlist.m3u8"
    segment_pattern = out_dir / "seg_%04d.m4s"
    init = out_dir / "init.mp4"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-vf",
        f"scale=w={width}:h={rendition['height']}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{rendition['height']}:(ow-iw)/2:(oh-ih)/2,setsar=1",
        "-c:v",
        "libx264",
        "-profile:v",
        "main",
        "-preset",
        "veryfast",
        "-b:v",
        f"{rendition['v_bitrate']}k",
        "-maxrate",
        f"{rendition['maxrate']}k",
        "-bufsize",
        f"{rendition['bufsize']}k",
        "-g",
        str(int(segment_seconds * 30)),
        "-keyint_min",
        str(int(segment_seconds * 30)),
        "-sc_threshold",
        "0",
        "-c:a",
        "aac",
        "-b:a",
        f"{rendition['a_bitrate']}k",
        "-ac",
        "2",
        "-ar",
        "48000",
        "-f",
        "hls",
        "-hls_time",
        str(segment_seconds),
        "-hls_playlist_type",
        "vod",
        "-hls_flags",
        "independent_segments",
        "-hls_segment_type",
        "fmp4",
        "-hls_fmp4_init_filename",
        init.name,
        "-hls_segment_filename",
        str(segment_pattern),
        str(playlist),
    ]
    print(f"  Encoding {rendition['name']} ({width}x{rendition['height']})...")
    subprocess.run(cmd, check=True)


def write_master_playlist(out_root: Path, renditions: list[dict], widths: dict[str, int]) -> None:
    lines = ["#EXTM3U", "#EXT-X-VERSION:7"]
    for r in renditions:
        bandwidth = (r["v_bitrate"] + r["a_bitrate"]) * 1000
        w = widths[r["name"]]
        h = r["height"]
        lines.append(
            f'#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={w}x{h},NAME="{r["name"]}"'
        )
        lines.append(f"{r['name']}/playlist.m3u8")
    (out_root / "master.m3u8").write_text("\n".join(lines) + "\n")


def count_segments(playlist: Path) -> int:
    text = playlist.read_text()
    return len(re.findall(r"\.m4s", text))


def write_manifest_json(
    out_root: Path,
    name: str,
    source: Path,
    duration: float,
    segment_seconds: float,
    renditions: list[dict],
    widths: dict[str, int],
) -> None:
    reps = []
    for r in renditions:
        playlist = out_root / r["name"] / "playlist.m3u8"
        reps.append(
            {
                "name": r["name"],
                "width": widths[r["name"]],
                "height": r["height"],
                "video_bitrate_kbps": r["v_bitrate"],
                "audio_bitrate_kbps": r["a_bitrate"],
                "bandwidth_bps": (r["v_bitrate"] + r["a_bitrate"]) * 1000,
                "playlist": f"{r['name']}/playlist.m3u8",
                "init": f"{r['name']}/init.mp4",
                "segment_count": count_segments(playlist),
            }
        )

    manifest = {
        "name": name,
        "source": str(source.name),
        "duration_seconds": round(duration, 3),
        "segment_duration_seconds": segment_seconds,
        "master_playlist": "master.m3u8",
        "representations": reps,
    }
    (out_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Package a video as multi-bitrate HLS")
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "content" / "source" / "sample.mp4",
        help="Source video path",
    )
    parser.add_argument(
        "--name",
        type=str,
        default=None,
        help="Output package name (default: input stem)",
    )
    parser.add_argument(
        "--segment-duration",
        type=float,
        default=2.0,
        help="Target HLS segment duration in seconds",
    )
    parser.add_argument(
        "--max-height",
        type=int,
        default=1080,
        help="Skip renditions taller than this (and taller than source)",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Input not found: {args.input}", file=sys.stderr)
        print("Run: python scripts/generate_sample.py", file=sys.stderr)
        return 1

    name = args.name or args.input.stem
    out_root = ROOT / "content" / "hls" / name
    out_root.mkdir(parents=True, exist_ok=True)

    probe = ffprobe_json(args.input)
    height = source_height(probe)
    duration = source_duration(probe)
    video_stream = next(s for s in probe["streams"] if s.get("codec_type") == "video")
    src_w = int(video_stream["width"])
    src_h = int(video_stream["height"])

    selected = [
        r
        for r in RENDITIONS
        if r["height"] <= min(height, args.max_height)
    ]
    if not selected:
        selected = [RENDITIONS[0]]

    print(f"Packaging '{name}' ({src_w}x{src_h}, {duration:.1f}s) → {out_root}")
    widths: dict[str, int] = {}
    for r in selected:
        w = even_width(r["height"], src_w, src_h)
        widths[r["name"]] = w
        encode_rendition(args.input, out_root / r["name"], r, w, args.segment_duration)

    write_master_playlist(out_root, selected, widths)
    write_manifest_json(
        out_root, name, args.input, duration, args.segment_duration, selected, widths
    )

    print(f"Done. Master playlist: {out_root / 'master.m3u8'}")
    print(f"Manifest: {out_root / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"ffmpeg failed with exit code {exc.returncode}", file=sys.stderr)
        raise SystemExit(exc.returncode)
