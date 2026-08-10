"""ASR helpers — Whisper when available, otherwise scripted demo transcripts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class TranscriptCue:
    start: float
    end: float
    text: str
    confidence: float = 1.0


def transcribe_whisper(audio_path: Path, model_size: str = "base") -> list[TranscriptCue]:
    try:
        import whisper  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "openai-whisper is not installed. pip install openai-whisper"
        ) from exc

    model = whisper.load_model(model_size)
    result = model.transcribe(str(audio_path), verbose=False)
    cues: list[TranscriptCue] = []
    for seg in result.get("segments", []):
        cues.append(
            TranscriptCue(
                start=float(seg["start"]),
                end=float(seg["end"]),
                text=str(seg["text"]).strip(),
                confidence=float(seg.get("avg_logprob", 0.0) and 0.8 or 0.7),
            )
        )
    return [c for c in cues if c.text]
