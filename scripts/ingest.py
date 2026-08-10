#!/usr/bin/env python3
"""Copy inbox drops → source/, package HLS, build captions.

Layouts:

  content/inbox/myclip.mp4 + myclip.srt
  content/inbox/myclip/{video.mp4,subs.srt}

  python scripts/ingest.py
  python scripts/ingest.py --name myclip
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "content" / "inbox"
SOURCE = ROOT / "content" / "source"
HLS = ROOT / "content" / "hls"

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
SUB_EXTS = {".srt", ".vtt", ".json"}


def find_pairs(name_filter: str | None = None) -> list[tuple[str, Path, Path | None]]:
    pairs: list[tuple[str, Path, Path | None]] = []
    if not INBOX.exists():
        return pairs

    # Flat files: name.mp4 + name.srt
    for video in sorted(INBOX.iterdir()):
        if not video.is_file() or video.suffix.lower() not in VIDEO_EXTS:
            continue
        name = video.stem
        if name_filter and name != name_filter:
            continue
        subs = None
        for ext in (".srt", ".vtt", ".cues.json", ".json"):
            candidate = INBOX / f"{name}{ext}"
            if candidate.exists():
                subs = candidate
                break
        pairs.append((name, video, subs))

    # Folders: inbox/name/*
    for folder in sorted(INBOX.iterdir()):
        if not folder.is_dir() or folder.name.startswith("."):
            continue
        name = folder.name
        if name_filter and name != name_filter:
            continue
        videos = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
        if not videos:
            continue
        video = sorted(videos)[0]
        subs = None
        for p in sorted(folder.iterdir()):
            if not p.is_file():
                continue
            if p.suffix.lower() in {".srt", ".vtt"} or p.name.endswith(".cues.json") or p.suffix.lower() == ".json":
                subs = p
                break
        # Avoid duplicating if flat pair already found
        if any(n == name for n, _, _ in pairs):
            continue
        pairs.append((name, video, subs))

    return pairs


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def ingest_one(name: str, video: Path, subs: Path | None, max_height: int, no_vision: bool) -> None:
    SOURCE.mkdir(parents=True, exist_ok=True)
    dest_video = SOURCE / f"{name}{video.suffix.lower()}"
    shutil.copy2(video, dest_video)
    print(f"Copied video → {dest_video}")

    dest_subs = None
    if subs is not None:
        if subs.name.endswith(".cues.json"):
            dest_subs = SOURCE / f"{name}.cues.json"
        else:
            dest_subs = SOURCE / f"{name}{subs.suffix.lower()}"
        shutil.copy2(subs, dest_subs)
        print(f"Copied subtitles → {dest_subs}")

    run(
        [
            sys.executable,
            "scripts/package_hls.py",
            "--input",
            str(dest_video),
            "--name",
            name,
            "--max-height",
            str(max_height),
        ]
    )

    build_cmd = [
        sys.executable,
        "-m",
        "captions.build",
        "--video",
        name,
        "--input",
        str(dest_video),
        "--name",
        name,
    ]
    if dest_subs is not None:
        build_cmd.extend(["--asr", "subtitles", "--subtitles", str(dest_subs)])
    else:
        print("No subtitle file found — attempting Whisper ASR")
        build_cmd.extend(["--asr", "whisper"])
    if no_vision:
        build_cmd.append("--no-vision")
    run(build_cmd)

    print(f"Ready: HLS package 'content/hls/{name}'")
    print("Open the player and select this video.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest inbox video + subtitles")
    parser.add_argument("--name", default=None, help="Only ingest this title")
    parser.add_argument("--max-height", type=int, default=720)
    parser.add_argument("--no-vision", action="store_true")
    parser.add_argument("--list", action="store_true", help="List inbox pairs only")
    args = parser.parse_args()

    INBOX.mkdir(parents=True, exist_ok=True)
    pairs = find_pairs(args.name)
    if args.list:
        if not pairs:
            print(f"Inbox empty: {INBOX}")
            print("Drop myclip.mp4 + myclip.srt here.")
            return 0
        for name, video, subs in pairs:
            print(f"{name}: video={video.name} subs={subs.name if subs else 'NONE'}")
        return 0

    if not pairs:
        print(f"No videos found in {INBOX}")
        print("Put files like:")
        print("  content/inbox/myclip.mp4")
        print("  content/inbox/myclip.srt")
        return 1

    for name, video, subs in pairs:
        print(f"\n=== Ingesting '{name}' ===")
        try:
            ingest_one(name, video, subs, args.max_height, args.no_vision)
        except subprocess.CalledProcessError as exc:
            print(f"Failed ingest for {name}: {exc}", file=sys.stderr)
            return exc.returncode or 1

    print("\nDone. Restart/reload the player if it was already open.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
