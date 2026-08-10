#!/usr/bin/env python3
"""Create a synthetic study session for pipeline demos (not real participants).

Simulates weaker standard-caption performance and stronger spatial-caption
performance so report/summary tooling can be exercised end-to-end.
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDY_ROOT = ROOT / "content" / "study_results"
CUES = ROOT / "content" / "source" / "dialogue_demo.cues.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--participant", default="sim-demo")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    rng = random.Random(args.seed)

    cues = json.loads(CUES.read_text())
    trials = []
    for i, cue in enumerate(cues[:4]):
        for condition in ("standard", "spatial"):
            # Spatial: mostly correct. Standard: often misses side, sometimes speaker.
            if condition == "spatial":
                speaker_ok = rng.random() > 0.1
                side_ok = rng.random() > 0.15
            else:
                speaker_ok = rng.random() > 0.35
                side_ok = rng.random() > 0.55

            resp_speaker = cue["speaker"] if speaker_ok else ("SARA" if cue["speaker"] == "JOHN" else "JOHN")
            resp_side = cue["side"] if side_ok else ("RIGHT" if cue["side"] == "LEFT" else "LEFT")
            trials.append(
                {
                    "index": len(trials),
                    "condition": condition,
                    "text": cue["text"],
                    "gt_speaker": cue["speaker"],
                    "gt_side": cue["side"],
                    "response_speaker": resp_speaker,
                    "response_side": resp_side,
                    "speaker_correct": speaker_ok,
                    "side_correct": side_ok,
                    "pair": i,
                }
            )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    session = {
        "participant": args.participant,
        "video": "dialogue_demo",
        "startedAt": now,
        "finishedAt": now,
        "summary": None,
        "trials": trials,
        "synthetic": True,
        "note": "Synthetic session for tooling demo — replace with real /study runs",
    }
    STUDY_ROOT.mkdir(parents=True, exist_ok=True)
    out = STUDY_ROOT / f"{args.participant}-{now}.json"
    out.write_text(json.dumps(session, indent=2) + "\n")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
