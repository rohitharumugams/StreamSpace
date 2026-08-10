#!/usr/bin/env python3
"""Evaluate spatial / speaker / placement caption quality.

Example:
  python -m captions.eval_accuracy --video dialogue_demo
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from captions.placement import PlacementBox, _overlap, obstacles_for_event
from captions.vision import VisualFrame, VisualDetection, analyze_video_speakers

HLS_ROOT = ROOT / "content" / "hls"
SOURCE_ROOT = ROOT / "content" / "source"
WORK_ROOT = ROOT / "content" / "captions_work"


def normalize_side(value: str) -> str:
    value = value.strip().upper()
    if value in {"LEFT", "L"}:
        return "LEFT"
    if value in {"RIGHT", "R"}:
        return "RIGHT"
    return "CENTER"


def load_visual_frames(video: str, source: Path, events: list[dict]) -> list[VisualFrame]:
    cached = WORK_ROOT / video / "vision_frames.json"
    if cached.exists():
        raw = json.loads(cached.read_text())
        frames = []
        for item in raw:
            dets = [VisualDetection(**d) for d in item.get("detections", [])]
            frames.append(VisualFrame(time=float(item["time"]), detections=dets))
        return frames
    times = sorted({round((e["start"] + e["end"]) / 2, 3) for e in events})
    return analyze_video_speakers(source, sample_times=times)


def caption_box(event: dict, w: float = 0.42, h: float = 0.10) -> PlacementBox | None:
    if event.get("x") is None or event.get("y") is None:
        return None
    x = float(event["x"]) - w / 2
    y = float(event["y"])
    return PlacementBox(x=max(0.0, x), y=max(0.0, y), w=w, h=h)


def naive_box(direction: str, w: float = 0.42, h: float = 0.10) -> PlacementBox:
    # Old behavior: dump captions over the speaker region in the lower third.
    if direction == "LEFT":
        return PlacementBox(x=0.05, y=0.45, w=w, h=h)
    if direction == "RIGHT":
        return PlacementBox(x=0.53, y=0.45, w=w, h=h)
    return PlacementBox(x=0.29, y=0.78, w=w, h=h)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate spatial caption accuracy")
    parser.add_argument("--video", default="dialogue_demo")
    parser.add_argument("--captions", type=Path, default=None)
    parser.add_argument("--ground-truth", type=Path, default=None)
    args = parser.parse_args()

    captions_path = args.captions or (HLS_ROOT / args.video / "captions.json")
    gt_path = args.ground_truth or (SOURCE_ROOT / f"{args.video}.cues.json")
    source = SOURCE_ROOT / f"{args.video}.mp4"
    if not captions_path.exists():
        print(f"Missing captions: {captions_path}", file=sys.stderr)
        return 1
    if not gt_path.exists():
        print(f"Missing ground truth: {gt_path}", file=sys.stderr)
        return 1

    captions = json.loads(captions_path.read_text())
    truth = json.loads(gt_path.read_text())
    by_text = {item["text"]: item for item in truth}

    speech = [e for e in captions.get("events", []) if e.get("kind") == "speech"]
    if not speech:
        print("No speech events in captions.", file=sys.stderr)
        return 1

    visual_frames = load_visual_frames(args.video, source, speech) if source.exists() else []

    direction_hits = 0
    speaker_hits = 0
    stereo_hits = 0
    vision_hits = 0
    agree = 0
    compared = 0
    placed_events = 0
    smart_overlap = 0.0
    naive_overlap = 0.0
    rows = []

    for event in speech:
        gt = by_text.get(event["text"])
        if not gt:
            continue
        compared += 1
        gt_side = normalize_side(str(gt.get("side", "CENTER")))
        gt_speaker = str(gt.get("speaker", "")).upper()
        pred_side = normalize_side(str(event.get("direction", "CENTER")))
        pred_speaker = str(event.get("speaker") or "").upper()
        stereo = event.get("stereo_direction")
        vision = event.get("vision_direction")

        d_ok = pred_side == gt_side
        s_ok = bool(gt_speaker) and pred_speaker == gt_speaker
        direction_hits += int(d_ok)
        speaker_hits += int(s_ok)
        if stereo:
            stereo_hits += int(normalize_side(stereo) == gt_side)
        if vision:
            vision_hits += int(normalize_side(vision) == gt_side)
        if stereo and vision and normalize_side(stereo) == normalize_side(vision):
            agree += 1

        obstacles = obstacles_for_event(visual_frames, event["start"], event["end"])
        obs_boxes = [
            PlacementBox(
                x=max(0.0, d.x - d.w / 2),
                y=max(0.0, d.y - d.h / 2),
                w=d.w,
                h=d.h,
            )
            for d in obstacles
        ]
        smart = caption_box(event)
        naive = naive_box(pred_side)
        smart_ov = 0.0
        naive_ov = 0.0
        if smart is not None and obs_boxes:
            placed_events += 1
            smart_ov = max((_overlap(smart, o) for o in obs_boxes), default=0.0)
            naive_ov = max((_overlap(naive, o) for o in obs_boxes), default=0.0)
            smart_overlap += smart_ov
            naive_overlap += naive_ov

        rows.append(
            {
                "text": event["text"],
                "gt": gt_side,
                "pred": pred_side,
                "stereo": stereo,
                "vision": vision,
                "fusion": event.get("fusion_source"),
                "x": event.get("x"),
                "y": event.get("y"),
                "placement_score": event.get("placement_score"),
                "smart_overlap": round(smart_ov, 4),
                "naive_overlap": round(naive_ov, 4),
                "speaker_ok": s_ok,
                "direction_ok": d_ok,
            }
        )

    summary = {
        "video": args.video,
        "compared": compared,
        "direction_accuracy": round(direction_hits / compared, 4) if compared else 0.0,
        "speaker_accuracy": round(speaker_hits / compared, 4) if compared else 0.0,
        "stereo_direction_accuracy": round(stereo_hits / compared, 4) if compared else 0.0,
        "vision_direction_accuracy": round(vision_hits / compared, 4) if compared else 0.0,
        "av_agreement_rate": round(agree / compared, 4) if compared else 0.0,
        "placement_events": placed_events,
        "avg_smart_overlap": round(smart_overlap / placed_events, 4) if placed_events else 0.0,
        "avg_naive_overlap": round(naive_overlap / placed_events, 4) if placed_events else 0.0,
        "rows": rows,
    }

    out = WORK_ROOT / args.video / "accuracy.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n")

    print(f"Compared {compared} speech events")
    print(f"Direction accuracy: {summary['direction_accuracy']*100:.1f}%")
    print(f"Speaker accuracy:   {summary['speaker_accuracy']*100:.1f}%")
    print(f"Stereo-only:        {summary['stereo_direction_accuracy']*100:.1f}%")
    print(f"Vision-only:        {summary['vision_direction_accuracy']*100:.1f}%")
    print(f"AV agreement:       {summary['av_agreement_rate']*100:.1f}%")
    print(
        f"Placement overlap:  smart={summary['avg_smart_overlap']:.3f}  "
        f"naive={summary['avg_naive_overlap']:.3f}"
    )
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
