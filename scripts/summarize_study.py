#!/usr/bin/env python3
"""Summarize saved caption A/B study sessions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDY_ROOT = ROOT / "content" / "study_results"


def summarize_file(path: Path) -> dict:
    data = json.loads(path.read_text())
    trials = data.get("trials") or []
    by = {"standard": [], "spatial": []}
    for trial in trials:
        cond = trial.get("condition")
        if cond in by:
            by[cond].append(trial)

    def score(rows: list[dict]) -> dict:
        if not rows:
            return {"n": 0, "speaker_pct": None, "side_pct": None}
        speaker = sum(1 for r in rows if r.get("speaker_correct")) / len(rows)
        side = sum(1 for r in rows if r.get("side_correct")) / len(rows)
        return {
            "n": len(rows),
            "speaker_pct": round(100 * speaker, 1),
            "side_pct": round(100 * side, 1),
        }

    return {
        "file": path.name,
        "participant": data.get("participant"),
        "video": data.get("video"),
        "standard": score(by["standard"]),
        "spatial": score(by["spatial"]),
        "raw_summary": data.get("summary"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize caption study results")
    parser.add_argument(
        "--dir",
        type=Path,
        default=STUDY_ROOT,
        help="Directory of study JSON files",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write aggregate JSON summary",
    )
    args = parser.parse_args()

    if not args.dir.exists():
        print(f"No study results at {args.dir}", file=sys.stderr)
        return 1

    files = sorted(args.dir.glob("*.json"))
    # Ignore empty placeholder sessions with no trials
    rows = []
    for path in files:
        item = summarize_file(path)
        if (item["standard"]["n"] + item["spatial"]["n"]) == 0:
            continue
        rows.append(item)

    if not rows:
        print("No completed study sessions with trials found.")
        print(f"Run the study UI at /study and submit answers into {args.dir}")
        return 0

    def mean(key_cond: str, metric: str) -> float | None:
        vals = [
            r[key_cond][metric]
            for r in rows
            if r[key_cond][metric] is not None and r[key_cond]["n"] > 0
        ]
        if not vals:
            return None
        return round(sum(vals) / len(vals), 1)

    aggregate = {
        "sessions": len(rows),
        "mean_standard_speaker_pct": mean("standard", "speaker_pct"),
        "mean_standard_side_pct": mean("standard", "side_pct"),
        "mean_spatial_speaker_pct": mean("spatial", "speaker_pct"),
        "mean_spatial_side_pct": mean("spatial", "side_pct"),
        "sessions_detail": rows,
    }

    print(f"Sessions: {aggregate['sessions']}")
    print(
        f"Standard — speaker {aggregate['mean_standard_speaker_pct']}%  "
        f"side {aggregate['mean_standard_side_pct']}%"
    )
    print(
        f"Spatial  — speaker {aggregate['mean_spatial_speaker_pct']}%  "
        f"side {aggregate['mean_spatial_side_pct']}%"
    )

    out = args.out or (args.dir / "aggregate.json")
    out.write_text(json.dumps(aggregate, indent=2) + "\n")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
