"""Intelligent caption placement.

Chooses a screen position that stays near the speaker while avoiding
faces / speaker panels and other important visual regions.
"""

from __future__ import annotations

from dataclasses import dataclass

from captions.schema import Direction
from captions.vision import VisualDetection, VisualFrame, vision_candidates_for_span


@dataclass(frozen=True)
class PlacementBox:
    # Normalized [0,1] top-left + size, relative to the video frame.
    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class PlacementResult:
    x: float  # caption anchor x (center)
    y: float  # caption anchor y (top of box)
    align: Direction
    score: float
    avoided: int


def _overlap(a: PlacementBox, b: PlacementBox) -> float:
    ax2, ay2 = a.x + a.w, a.y + a.h
    bx2, by2 = b.x + b.w, b.y + b.h
    ix = max(0.0, min(ax2, bx2) - max(a.x, b.x))
    iy = max(0.0, min(ay2, by2) - max(a.y, b.y))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    return inter / min(a.w * a.h, b.w * b.h)


def _det_box(det: VisualDetection, pad: float = 0.03) -> PlacementBox:
    return PlacementBox(
        x=max(0.0, det.x - det.w / 2 - pad),
        y=max(0.0, det.y - det.h / 2 - pad),
        w=min(1.0, det.w + 2 * pad),
        h=min(1.0, det.h + 2 * pad),
    )


def _candidate_slots(direction: Direction, caption_w: float = 0.42, caption_h: float = 0.10) -> list[tuple[PlacementBox, Direction, float]]:
    """Generate ranked candidate slots: (box, align, prior)."""
    # prior favors speaker side + lower third (readable captions).
    slots: list[tuple[PlacementBox, Direction, float]] = []

    def add(x: float, y: float, align: Direction, prior: float) -> None:
        x = min(max(x, 0.02), 1.0 - caption_w - 0.02)
        y = min(max(y, 0.05), 1.0 - caption_h - 0.05)
        slots.append((PlacementBox(x=x, y=y, w=caption_w, h=caption_h), align, prior))

    if direction == "LEFT":
        add(0.04, 0.78, "LEFT", 1.0)
        add(0.04, 0.66, "LEFT", 0.9)
        add(0.04, 0.12, "LEFT", 0.7)
        add(0.29, 0.78, "CENTER", 0.55)
        add(0.54, 0.78, "RIGHT", 0.35)
    elif direction == "RIGHT":
        add(0.54, 0.78, "RIGHT", 1.0)
        add(0.54, 0.66, "RIGHT", 0.9)
        add(0.54, 0.12, "RIGHT", 0.7)
        add(0.29, 0.78, "CENTER", 0.55)
        add(0.04, 0.78, "LEFT", 0.35)
    else:
        add(0.29, 0.78, "CENTER", 1.0)
        add(0.29, 0.66, "CENTER", 0.85)
        add(0.04, 0.78, "LEFT", 0.5)
        add(0.54, 0.78, "RIGHT", 0.5)
        add(0.29, 0.12, "CENTER", 0.45)

    return slots


def _align_from_x(x: float) -> Direction:
    if x < 0.38:
        return "LEFT"
    if x > 0.62:
        return "RIGHT"
    return "CENTER"


def place_caption(
    *,
    direction: Direction,
    preferred_x: float | None,
    obstacles: list[VisualDetection],
    caption_w: float = 0.42,
    caption_h: float = 0.10,
) -> PlacementResult:
    slots = _candidate_slots(direction, caption_w=caption_w, caption_h=caption_h)
    # Also consider a continuous slot anchored at preferred_x.
    if preferred_x is not None:
        ax = min(max(preferred_x - caption_w / 2, 0.02), 1.0 - caption_w - 0.02)
        for y, prior in ((0.78, 1.05), (0.66, 0.95), (0.12, 0.55)):
            slots.append(
                (
                    PlacementBox(x=ax, y=y, w=caption_w, h=caption_h),
                    _align_from_x(preferred_x),
                    prior,
                )
            )

    obstacle_boxes = [_det_box(d) for d in obstacles]

    best: PlacementResult | None = None
    for box, align, prior in slots:
        overlap_penalty = 0.0
        hits = 0
        for obs in obstacle_boxes:
            ov = _overlap(box, obs)
            if ov > 0:
                hits += 1
                overlap_penalty += ov

        center_x = box.x + box.w / 2
        proximity = 0.0
        if preferred_x is not None:
            proximity = 1.0 - min(1.0, abs(center_x - preferred_x) / 0.55)

        lower = 0.15 if box.y >= 0.6 else 0.0
        score = prior + 0.55 * proximity + lower - 1.8 * overlap_penalty
        candidate = PlacementResult(
            x=round(center_x, 3),
            y=round(box.y, 3),
            align=align,
            score=round(score, 4),
            avoided=hits,
        )
        if best is None or candidate.score > best.score:
            best = candidate

    assert best is not None
    return best


def place_near_speaker(
    *,
    preferred_x: float,
    preferred_y: float,
    direction: Direction,
    obstacles: list[VisualDetection],
    speaker: VisualDetection | None = None,
    caption_w: float = 0.38,
    caption_h: float = 0.10,
) -> PlacementResult:
    """Place caption near a detected speaker, nudging away from face boxes."""
    x = min(max(preferred_x, 0.12), 0.88)
    y = min(max(preferred_y, 0.08), 0.86)
    align = direction if direction != "CENTER" else _align_from_x(x)

    # Candidate y offsets: under chin, lower-third, above head.
    y_opts = [
        y,
        min(0.84, y + 0.08),
        0.78,
        0.66,
        max(0.08, (speaker.y - speaker.h / 2 - 0.12) if speaker else 0.12),
    ]

    obstacle_boxes = [_det_box(d) for d in obstacles]
    if speaker is not None:
        obstacle_boxes.append(_det_box(speaker, pad=0.02))

    best: PlacementResult | None = None
    for yi in y_opts:
        box = PlacementBox(
            x=min(max(x - caption_w / 2, 0.02), 1.0 - caption_w - 0.02),
            y=min(max(yi, 0.05), 1.0 - caption_h - 0.05),
            w=caption_w,
            h=caption_h,
        )
        overlap_penalty = 0.0
        hits = 0
        for obs in obstacle_boxes:
            ov = _overlap(box, obs)
            if ov > 0:
                hits += 1
                overlap_penalty += ov
        center_x = box.x + box.w / 2
        proximity = 1.0 - min(1.0, abs(center_x - preferred_x) / 0.45)
        y_prox = 1.0 - min(1.0, abs(box.y - preferred_y) / 0.5)
        score = 1.2 + 0.7 * proximity + 0.35 * y_prox - 2.2 * overlap_penalty
        candidate = PlacementResult(
            x=round(center_x, 3),
            y=round(box.y, 3),
            align=align,
            score=round(score, 4),
            avoided=hits,
        )
        if best is None or candidate.score > best.score:
            best = candidate

    assert best is not None
    return best


def obstacles_for_event(
    frames: list[VisualFrame],
    start: float,
    end: float,
) -> list[VisualDetection]:
    return vision_candidates_for_span(frames, start, end)
