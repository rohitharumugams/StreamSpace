#!/usr/bin/env python3
"""Sanity checks: packages exist, captions parse, optional live /api/health."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    suffix = f" — {detail}" if detail else ""
    print(f"[{status}] {name}{suffix}")
    if not ok:
        raise SystemExit(1)


def main() -> int:
    print("Smoke test")
    sample = ROOT / "content" / "hls" / "sample" / "master.m3u8"
    dialogue = ROOT / "content" / "hls" / "dialogue_demo" / "master.m3u8"
    captions = ROOT / "content" / "hls" / "dialogue_demo" / "captions.json"
    check("sample HLS package", sample.exists(), str(sample))
    check("dialogue HLS package", dialogue.exists(), str(dialogue))
    check("dialogue captions", captions.exists(), str(captions))

    from eval.abr import create_abr
    from eval.catalog import load_video_levels, parse_trace_file
    from eval.simulator import simulate

    _, levels, seg = load_video_levels("sample")
    trace = parse_trace_file(ROOT / "traces" / "congested.txt")
    result = simulate(
        video="sample",
        abr=create_abr("risk"),
        levels=levels,
        segment_duration=seg,
        trace_mbps=trace,
        trace_name="congested",
    )
    check("ABR simulator (risk×congested)", result.segment_count > 0, f"{result.segment_count} segs")

    data = json.loads(captions.read_text())
    speech = [e for e in data["events"] if e.get("kind") == "speech"]
    check("captions have speech events", len(speech) >= 4, str(len(speech)))
    check(
        "captions include placement",
        all(e.get("x") is not None and e.get("y") is not None for e in speech),
    )
    check(
        "captions include fusion fields",
        all(e.get("fusion_source") for e in speech),
    )

    # Optional live server check
    for port in (8081, 8080):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as resp:
                payload = json.loads(resp.read().decode())
            check(f"server :{port} health", payload.get("status") == "ok")
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/study/trials?video=dialogue_demo", timeout=2
            ) as resp:
                trials = json.loads(resp.read().decode())
            check(
                f"server :{port} study trials",
                len(trials.get("trials", [])) >= 1,
                f"n={len(trials.get('trials', []))}",
            )
            break
        except urllib.error.URLError:
            continue
        except Exception as exc:  # noqa: BLE001
            # Old server without study routes
            print(f"[WARN] server check incomplete: {exc}")
            break
    else:
        print("[WARN] no live server on 8080/8081 (skip API checks)")

    print("All required smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
