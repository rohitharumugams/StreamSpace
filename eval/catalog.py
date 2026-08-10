"""Load packaged HLS segment sizes + parse Mbps traces."""

from __future__ import annotations

import json
from pathlib import Path

from eval.abr import Level

ROOT = Path(__file__).resolve().parents[1]
HLS_ROOT = ROOT / "content" / "hls"
TRACES_ROOT = ROOT / "traces"


def parse_trace_file(path: Path) -> list[float]:
    samples: list[float] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        samples.append(float(line.split()[0]))
    if not samples:
        raise ValueError(f"Empty trace: {path}")
    return samples


def list_traces() -> list[str]:
    if not TRACES_ROOT.exists():
        return []
    return sorted(p.stem for p in TRACES_ROOT.glob("*.txt"))


def list_videos() -> list[str]:
    if not HLS_ROOT.exists():
        return []
    return sorted(
        p.name
        for p in HLS_ROOT.iterdir()
        if p.is_dir() and (p / "manifest.json").exists()
    )


def _segment_files(rendition_dir: Path) -> list[Path]:
    files = sorted(rendition_dir.glob("seg_*.m4s"))
    if files:
        return files
    return sorted(rendition_dir.glob("seg_*.ts"))


def load_video_levels(name: str) -> tuple[dict, list[Level], float]:
    package = HLS_ROOT / name
    manifest_path = package / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing manifest for video '{name}'")

    manifest = json.loads(manifest_path.read_text())
    segment_duration = float(manifest["segment_duration_seconds"])
    levels: list[Level] = []

    for rep in manifest["representations"]:
        rendition_dir = package / rep["name"]
        segs = _segment_files(rendition_dir)
        if not segs:
            raise FileNotFoundError(f"No segments in {rendition_dir}")
        sizes = [p.stat().st_size for p in segs]
        levels.append(
            Level(
                name=rep["name"],
                height=int(rep["height"]),
                bitrate=int(rep["bandwidth_bps"]),
                segment_bytes=sizes,
            )
        )

    # Ensure equal segment counts across renditions
    counts = {lvl.name: len(lvl.segment_bytes) for lvl in levels}
    if len(set(counts.values())) != 1:
        raise ValueError(f"Segment count mismatch across renditions: {counts}")

    return manifest, levels, segment_duration


def bandwidth_at(trace_mbps: list[float], time_s: float, loop: bool = True) -> float:
    if not trace_mbps:
        return 100.0  # effectively unlimited
    idx = int(time_s)
    if idx < 0:
        idx = 0
    if idx >= len(trace_mbps):
        idx = idx % len(trace_mbps) if loop else len(trace_mbps) - 1
    return trace_mbps[idx]
