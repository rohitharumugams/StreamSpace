#!/usr/bin/env python3
"""ABR × trace × video sweep → eval/results/<stamp>/{results.json,results.csv}

  python -m eval.run_experiments
  python -m eval.run_experiments --abr hybrid,throughput --trace volatile,sudden_drop
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.abr import create_abr
from eval.catalog import list_traces, list_videos, load_video_levels, parse_trace_file
from eval.simulator import simulate

RESULTS_ROOT = ROOT / "eval" / "results"

DEFAULT_ABRS = ["throughput", "buffer", "hybrid", "risk", "fixed-low", "fixed-high"]


def parse_list(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return default
    return [part.strip() for part in value.split(",") if part.strip()]


def format_table(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return "(no results)"
    widths = {c: len(c) for c in columns}
    for row in rows:
        for c in columns:
            widths[c] = max(widths[c], len(str(row.get(c, ""))))
    header = "  ".join(c.ljust(widths[c]) for c in columns)
    sep = "  ".join("-" * widths[c] for c in columns)
    lines = [header, sep]
    for row in rows:
        lines.append("  ".join(str(row.get(c, "")).ljust(widths[c]) for c in columns))
    return "\n".join(lines)


def run_suite(
    videos: list[str],
    abrs: list[str],
    traces: list[str],
    write_segments: bool,
) -> list[dict]:
    results: list[dict] = []
    for video in videos:
        manifest, levels, seg_dur = load_video_levels(video)
        del manifest  # available if needed later
        for trace_name in traces:
            trace_path = ROOT / "traces" / f"{trace_name}.txt"
            trace = parse_trace_file(trace_path)
            for abr_name in abrs:
                abr = create_abr(abr_name)

                result = simulate(
                    video=video,
                    abr=abr,
                    levels=levels,
                    segment_duration=seg_dur,
                    trace_mbps=trace,
                    trace_name=trace_name,
                )
                summary = result.summary()
                if write_segments:
                    summary["segments"] = [s.__dict__ for s in result.segments]
                results.append(summary)
                print(
                    f"  {video:12} {abr.name:14} {trace_name:20} "
                    f"bitrate={summary['avg_bitrate_kbps']:7.1f}kbps  "
                    f"rebuf={summary['total_rebuffer_s']:6.2f}s  "
                    f"switches={summary['quality_switches']:3d}  "
                    f"startup={summary['startup_latency_s']:5.2f}s"
                )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run ABR evaluation suite")
    parser.add_argument("--video", default=None, help="Comma-separated video names")
    parser.add_argument("--abr", default=None, help="Comma-separated ABR names")
    parser.add_argument("--trace", default=None, help="Comma-separated trace names")
    parser.add_argument(
        "--segments",
        action="store_true",
        help="Include per-segment timelines in JSON output",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory (default: eval/results/<timestamp>)",
    )
    args = parser.parse_args()

    videos = parse_list(args.video, list_videos())
    abrs = parse_list(args.abr, DEFAULT_ABRS)
    traces = parse_list(args.trace, list_traces())

    if not videos:
        print("No packaged videos found. Run scripts/package_hls.py first.", file=sys.stderr)
        return 1
    if not traces:
        print("No traces found in traces/.", file=sys.stderr)
        return 1

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out or (RESULTS_ROOT / stamp)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Running {len(videos)} video(s) × {len(abrs)} ABR(s) × {len(traces)} trace(s)")
    print(f"Output: {out_dir}")
    results = run_suite(videos, abrs, traces, write_segments=args.segments)

    # Strip segments for the compact CSV/summary tables
    compact = [{k: v for k, v in row.items() if k != "segments"} for row in results]

    json_path = out_dir / "results.json"
    json_path.write_text(json.dumps(results if args.segments else compact, indent=2) + "\n")

    csv_path = out_dir / "results.csv"
    fieldnames = [
        "video",
        "abr",
        "trace",
        "avg_bitrate_kbps",
        "total_rebuffer_s",
        "rebuffer_events",
        "quality_switches",
        "startup_latency_s",
        "avg_buffer_s",
        "bandwidth_utilization",
        "segment_count",
        "duration_s",
    ]
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(compact)

    columns = [
        "abr",
        "trace",
        "avg_bitrate_kbps",
        "total_rebuffer_s",
        "quality_switches",
        "startup_latency_s",
    ]
    table = format_table(compact, columns)
    summary_path = out_dir / "summary.txt"
    summary_path.write_text(table + "\n")
    print()
    print(table)
    print()
    print(f"Wrote {json_path}")
    print(f"Wrote {csv_path}")
    print(f"Wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
