"""Parse common subtitle formats into transcript cues."""

from __future__ import annotations

import json
import re
from pathlib import Path

from captions.asr import TranscriptCue

_TIME_SRT = re.compile(
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2}),(?P<ms>\d{3})"
)
_TIME_VTT = re.compile(
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})\.(?P<ms>\d{3})"
)


def _parse_ts(token: str) -> float:
    token = token.strip().replace(",", ".")
    parts = token.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    if len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    return float(token)


def load_srt(path: Path) -> list[TranscriptCue]:
    text = path.read_text(encoding="utf-8-sig")
    blocks = re.split(r"\n\s*\n", text.strip(), flags=re.MULTILINE)
    cues: list[TranscriptCue] = []
    for block in blocks:
        lines = [ln.strip("\ufeff") for ln in block.splitlines() if ln.strip() != ""]
        if len(lines) < 2:
            continue
        # Optional index line
        if "-->" not in lines[0] and len(lines) >= 2 and "-->" in lines[1]:
            lines = lines[1:]
        if "-->" not in lines[0]:
            continue
        start_s, end_s = [p.strip() for p in lines[0].split("-->")]
        # Strip VTT positioning junk after timestamp
        end_s = end_s.split(" ")[0]
        body = " ".join(lines[1:]).strip()
        body = re.sub(r"<[^>]+>", "", body)
        if not body:
            continue
        cues.append(
            TranscriptCue(
                start=_parse_ts(start_s),
                end=_parse_ts(end_s),
                text=body,
                confidence=1.0,
            )
        )
    return cues


def load_vtt(path: Path) -> list[TranscriptCue]:
    text = path.read_text(encoding="utf-8-sig")
    # Drop header
    text = re.sub(r"^WEBVTT.*?\n\n", "", text, count=1, flags=re.IGNORECASE | re.DOTALL)
    # Reuse SRT-ish parsing after normalizing commas
    fake = text.replace(".", ",").replace("-->", "-->")
    # Actually keep dots for VTT; load_srt expects commas. Convert VTT times to SRT style.
    normalized = []
    for line in text.splitlines():
        if "-->" in line:
            line = line.replace(".", ",")
            # remove settings after end ts
            left, right = line.split("-->", 1)
            right_ts = right.strip().split()[0]
            line = f"{left.strip()} --> {right_ts}"
        normalized.append(line)
    tmp = path.with_suffix(".normalized.srt")
    try:
        tmp.write_text("\n".join(normalized) + "\n", encoding="utf-8")
        return load_srt(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def load_cues_json(path: Path) -> list[TranscriptCue]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cues: list[TranscriptCue] = []
    for item in data:
        cues.append(
            TranscriptCue(
                start=float(item["start"]),
                end=float(item["end"]),
                text=str(item["text"]).strip(),
                confidence=1.0,
            )
        )
    return [c for c in cues if c.text]


def load_subtitles(path: Path) -> list[TranscriptCue]:
    suffix = path.suffix.lower()
    if suffix == ".srt":
        return load_srt(path)
    if suffix == ".vtt":
        return load_vtt(path)
    if suffix == ".json" or path.name.endswith(".cues.json"):
        return load_cues_json(path)
    raise ValueError(f"Unsupported subtitle format: {path}")
