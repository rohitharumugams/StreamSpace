#!/usr/bin/env python3
"""Generate a consolidated markdown results report."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def latest_abr_csv() -> Path | None:
    results = ROOT / "eval" / "results"
    if not results.exists():
        return None
    report_focus = results / "report_focus" / "results.csv"
    if report_focus.exists():
        return report_focus
    preferred = results / "risk_compare" / "results.csv"
    if preferred.exists():
        return preferred
    csvs = sorted(results.glob("*/results.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    return csvs[0] if csvs else None


def load_abr_rows(path: Path) -> list[dict]:
    with path.open() as handle:
        return list(csv.DictReader(handle))


def fmt(row: dict, key: str) -> str:
    val = row.get(key, "")
    try:
        return f"{float(val):.2f}"
    except (TypeError, ValueError):
        return str(val)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate project results report")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "RESULTS.md")
    parser.add_argument("--refresh-abr", action="store_true")
    parser.add_argument("--refresh-captions", action="store_true")
    args = parser.parse_args()

    py = sys.executable
    if args.refresh_abr:
        subprocess.run(
            [
                py, "-m", "eval.run_experiments",
                "--abr", "throughput,hybrid,risk",
                "--trace", "congested,volatile,spike_drop",
                "--out", str(ROOT / "eval" / "results" / "report_focus"),
            ],
            cwd=ROOT,
            check=True,
        )

    if args.refresh_captions:
        subprocess.run(
            [py, "-m", "captions.eval_accuracy", "--video", "dialogue_demo"],
            cwd=ROOT,
            check=True,
        )

    abr_csv = latest_abr_csv()
    abr_rows = load_abr_rows(abr_csv) if abr_csv else []

    cap_path = ROOT / "content" / "captions_work" / "dialogue_demo" / "accuracy.json"
    cap = json.loads(cap_path.read_text()) if cap_path.exists() else None

    study_agg = ROOT / "content" / "study_results" / "aggregate.json"
    study = json.loads(study_agg.read_text()) if study_agg.exists() else None

    lines: list[str] = []
    lines.append("# Results Report")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")
    lines.append("## Adaptive streaming (ABR)")
    lines.append("")
    if abr_rows and abr_csv:
        lines.append(f"Source: `{abr_csv.relative_to(ROOT)}`")
        lines.append("")
        lines.append("| ABR | Trace | Avg bitrate (kbps) | Rebuffer (s) | Switches | Startup (s) |")
        lines.append("|-----|-------|--------------------:|-------------:|---------:|------------:|")
        for row in abr_rows:
            lines.append(
                "| {abr} | {trace} | {br} | {rebuf} | {sw} | {start} |".format(
                    abr=row.get("abr", ""),
                    trace=row.get("trace", ""),
                    br=fmt(row, "avg_bitrate_kbps"),
                    rebuf=fmt(row, "total_rebuffer_s"),
                    sw=row.get("quality_switches", ""),
                    start=fmt(row, "startup_latency_s"),
                )
            )
        lines.append("")
        lines.append(
            "Interpretation: risk-aware ABR is more conservative under volatility; "
            "on congested traces all adaptive methods drop to a safe floor while fixed-high rebuffers."
        )
    else:
        lines.append("_No ABR results found. Run `python -m eval.run_experiments`._")
    lines.append("")

    lines.append("## Spatial captions")
    lines.append("")
    if cap:
        lines.append(f"Source: `{cap_path.relative_to(ROOT)}`")
        lines.append("")
        lines.append("| Metric | Value |")
        lines.append("|--------|------:|")
        lines.append(f"| Direction accuracy | {100 * cap.get('direction_accuracy', 0):.1f}% |")
        lines.append(f"| Speaker accuracy | {100 * cap.get('speaker_accuracy', 0):.1f}% |")
        lines.append(f"| Stereo-only direction | {100 * cap.get('stereo_direction_accuracy', 0):.1f}% |")
        lines.append(f"| Vision-only direction | {100 * cap.get('vision_direction_accuracy', 0):.1f}% |")
        lines.append(f"| AV agreement | {100 * cap.get('av_agreement_rate', 0):.1f}% |")
        lines.append(f"| Smart placement overlap | {cap.get('avg_smart_overlap', 0):.3f} |")
        lines.append(f"| Naive placement overlap | {cap.get('avg_naive_overlap', 0):.3f} |")
        lines.append("")
    else:
        lines.append("_No caption accuracy file. Run `python -m captions.eval_accuracy`._")
        lines.append("")

    lines.append("## Caption user study")
    lines.append("")
    if study and study.get("sessions"):
        lines.append(f"Sessions: **{study['sessions']}**")
        lines.append("")
        lines.append("| Condition | Speaker accuracy | Side accuracy |")
        lines.append("|-----------|-----------------:|--------------:|")
        lines.append(
            f"| Standard | {study.get('mean_standard_speaker_pct')}% | {study.get('mean_standard_side_pct')}% |"
        )
        lines.append(
            f"| Spatial | {study.get('mean_spatial_speaker_pct')}% | {study.get('mean_spatial_side_pct')}% |"
        )
        lines.append("")
        if any((d.get("file") or "").startswith("sim-") for d in study.get("sessions_detail", [])):
            lines.append(
                "_Includes synthetic tooling sessions (`sim-*`). Replace with real `/study` participants for claims._"
            )
            lines.append("")
    else:
        lines.append("No completed participant sessions yet. Open `/study`, then run `python scripts/summarize_study.py`.")
        lines.append("")

    lines.append("## How to refresh")
    lines.append("")
    lines.append("```bash")
    lines.append("python scripts/generate_report.py --refresh-abr --refresh-captions")
    lines.append("python scripts/summarize_study.py")
    lines.append("python scripts/generate_report.py")
    lines.append("```")
    lines.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines))
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
