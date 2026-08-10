"""L/R energy balance over short windows → LEFT / CENTER / RIGHT."""

from __future__ import annotations

import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from captions.schema import Direction


@dataclass
class SpatialWindow:
    start: float
    end: float
    direction: Direction
    left_energy: float
    right_energy: float
    balance: float  # -1 left … +1 right
    confidence: float


def extract_wav(video: Path, wav_out: Path, sample_rate: int = 16000) -> Path:
    wav_out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-ac",
        "2",
        "-ar",
        str(sample_rate),
        "-vn",
        str(wav_out),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return wav_out


def load_stereo_wav(path: Path) -> tuple[np.ndarray, np.ndarray, int]:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
        width = handle.getsampwidth()

    if width == 2:
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
    elif width == 4:
        audio = np.frombuffer(frames, dtype=np.int32).astype(np.float32)
    else:
        raise ValueError(f"Unsupported sample width: {width}")

    if channels == 1:
        left = right = audio
    elif channels == 2:
        audio = audio.reshape(-1, 2)
        left, right = audio[:, 0], audio[:, 1]
    else:
        audio = audio.reshape(-1, channels)
        left, right = audio[:, 0], audio[:, 1]

    # Normalize
    peak = max(float(np.max(np.abs(left))), float(np.max(np.abs(right))), 1.0)
    left /= peak
    right /= peak
    return left, right, rate


# Film pans are usually mild — tight deadzone so we still catch them.
BALANCE_DEADZONE = 0.08


def _direction_from_balance(balance: float, deadzone: float = BALANCE_DEADZONE) -> Direction:
    if balance < -deadzone:
        return "LEFT"
    if balance > deadzone:
        return "RIGHT"
    return "CENTER"


def analyze_stereo(
    wav_path: Path,
    window_s: float = 0.5,
    hop_s: float = 0.25,
) -> list[SpatialWindow]:
    left, right, rate = load_stereo_wav(wav_path)
    win = max(1, int(window_s * rate))
    hop = max(1, int(hop_s * rate))
    windows: list[SpatialWindow] = []

    for start in range(0, max(1, len(left) - win + 1), hop):
        end = start + win
        l = left[start:end]
        r = right[start:end]
        le = float(np.mean(l * l) + 1e-12)
        re = float(np.mean(r * r) + 1e-12)
        # ICLD-style balance
        balance = (re - le) / (re + le)
        direction = _direction_from_balance(balance)
        confidence = min(1.0, abs(balance) / 0.35)
        if direction == "CENTER":
            confidence = max(0.25, 1.0 - abs(balance) / BALANCE_DEADZONE)
        windows.append(
            SpatialWindow(
                start=start / rate,
                end=end / rate,
                direction=direction,
                left_energy=le,
                right_energy=re,
                balance=float(balance),
                confidence=float(confidence),
            )
        )
    return windows


def direction_for_span(
    windows: list[SpatialWindow],
    start: float,
    end: float,
) -> tuple[Direction, float, float]:
    """Return (direction, confidence, balance) for a time span.

    balance is in [-1, 1] (negative = left-heavy).
    """
    if not windows:
        return "CENTER", 0.0, 0.0
    mid = (start + end) / 2.0
    # Prefer overlapping windows; otherwise nearest to mid.
    overlapping = [w for w in windows if w.end >= start and w.start <= end]
    if not overlapping:
        overlapping = [min(windows, key=lambda w: abs((w.start + w.end) / 2 - mid))]

    # Energy-weighted mean balance (beats hard voting on soft pans).
    num = 0.0
    den = 0.0
    for w in overlapping:
        weight = w.left_energy + w.right_energy
        num += weight * w.balance
        den += weight
    balance = num / den if den > 0 else 0.0
    direction = _direction_from_balance(balance)
    confidence = min(1.0, abs(balance) / 0.35)
    if direction == "CENTER":
        confidence = max(0.25, 1.0 - abs(balance) / BALANCE_DEADZONE)
    return direction, float(confidence), float(balance)


def x_from_balance(balance: float, *, gain: float = 0.22) -> float:
    """balance ∈ [-1,1] → caption x in roughly [0.15, 0.85]."""
    # |balance| >= gain saturates toward the side.
    t = max(-1.0, min(1.0, balance / max(gain, 1e-6)))
    return float(0.5 + 0.35 * t)
