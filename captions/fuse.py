"""Per-cue merge of transcript, stereo direction, and vision speaker pick."""

from __future__ import annotations

from dataclasses import replace

from captions.asr import TranscriptCue
from captions.placement import obstacles_for_event, place_caption, place_near_speaker
from captions.schema import CaptionEvent, CaptionTrack, Direction
from captions.stereo import SpatialWindow, direction_for_span, x_from_balance
from captions.vision import VisualDetection, VisualFrame, vision_for_span

# Demo defaults; .cues.json speaker names win when present.
SPEAKER_BY_DIRECTION: dict[Direction, str] = {
    "LEFT": "SPEAKER L",
    "RIGHT": "SPEAKER R",
    "CENTER": "SPEAKER",
}

DIRECTION_X: dict[Direction, float] = {
    "LEFT": 0.18,
    "CENTER": 0.5,
    "RIGHT": 0.82,
}


def _agree(a: Direction | None, b: Direction | None) -> bool:
    return a is not None and b is not None and a == b


def resolve_direction(
    *,
    stereo_dir: Direction,
    stereo_conf: float,
    stereo_balance: float,
    vision_dir: Direction | None,
    vision_conf: float,
    chosen: VisualDetection | None,
) -> tuple[Direction, float, str]:
    """Pick LEFT/CENTER/RIGHT when stereo and vision disagree."""
    if vision_dir is None or chosen is None:
        return stereo_dir, stereo_conf, "stereo"

    if _agree(stereo_dir, vision_dir):
        conf = min(1.0, 0.45 * stereo_conf + 0.65 * vision_conf)
        return vision_dir, conf, "av-agree"

    # Weak / center-mixed stereo → trust the face we picked.
    if stereo_dir == "CENTER" or abs(stereo_balance) < 0.10:
        return vision_dir, min(1.0, vision_conf + 0.05), "vision"

    # Face centered but audio leans — keep the arrow on the audio side.
    if vision_dir == "CENTER" and stereo_dir != "CENTER":
        return stereo_dir, stereo_conf * 0.75, "stereo-bias"

    # Disagree hard: still put the caption on the chosen face.
    return vision_dir, max(0.4, vision_conf * 0.75), "av-select"


def _speaker_label(
    direction: Direction,
    chosen: VisualDetection | None,
    speakers: dict[Direction, str],
) -> str | None:
    if chosen is not None:
        if chosen.direction in speakers:
            return speakers[chosen.direction]
        if chosen.track_id and chosen.track_id.endswith("left"):
            return speakers.get("LEFT", "SPEAKER L")
        if chosen.track_id and chosen.track_id.endswith("right"):
            return speakers.get("RIGHT", "SPEAKER R")
    return speakers.get(direction)


def fuse_captions(
    *,
    video_name: str,
    cues: list[TranscriptCue],
    windows: list[SpatialWindow],
    visual_frames: list[VisualFrame] | None = None,
    sound_events: list[CaptionEvent] | None = None,
    generated_by: list[str] | None = None,
    speaker_map: dict[Direction, str] | None = None,
) -> CaptionTrack:
    speakers = speaker_map or SPEAKER_BY_DIRECTION
    events: list[CaptionEvent] = []
    visual_frames = visual_frames or []

    for idx, cue in enumerate(cues):
        stereo_dir, stereo_conf, stereo_balance = direction_for_span(
            windows, cue.start, cue.end
        )
        vision_dir, vision_conf, vision_x, dets, chosen = vision_for_span(
            visual_frames,
            cue.start,
            cue.end,
            preferred=stereo_dir,
            stereo_balance=stereo_balance,
        )

        direction, conf, source = resolve_direction(
            stereo_dir=stereo_dir,
            stereo_conf=stereo_conf,
            stereo_balance=stereo_balance,
            vision_dir=vision_dir,
            vision_conf=vision_conf,
            chosen=chosen,
        )

        stereo_x = x_from_balance(stereo_balance)
        obstacles = [d for d in dets if chosen is None or d is not chosen]
        if not obstacles:
            obstacles = obstacles_for_event(visual_frames, cue.start, cue.end)

        if chosen is not None:
            preferred_x = 0.78 * chosen.x + 0.22 * stereo_x
            preferred_y = min(0.84, chosen.y + chosen.h * 0.55 + 0.03)
            placement = place_near_speaker(
                preferred_x=preferred_x,
                preferred_y=preferred_y,
                direction=direction,
                obstacles=obstacles,
                speaker=chosen,
            )
        elif vision_x is not None:
            preferred_x = 0.7 * vision_x + 0.3 * stereo_x
            placement = place_caption(
                direction=direction,
                preferred_x=preferred_x,
                obstacles=obstacles,
            )
        else:
            preferred_x = stereo_x
            placement = place_caption(
                direction=direction,
                preferred_x=preferred_x,
                obstacles=obstacles,
            )
            placement = replace(placement, x=round(preferred_x, 3), align=direction)

        speaker = _speaker_label(direction, chosen, speakers)

        events.append(
            CaptionEvent(
                id=f"speech-{idx:03d}",
                start=round(cue.start, 3),
                end=round(cue.end, 3),
                text=cue.text,
                kind="speech",
                speaker=speaker,
                direction=direction,
                confidence=round(min(cue.confidence, conf), 3),
                x=placement.x,
                y=placement.y,
                align=placement.align,
                placement_score=placement.score,
                stereo_direction=stereo_dir,
                vision_direction=vision_dir,
                fusion_source=source,
            )
        )

    if sound_events:
        for event in sound_events:
            if event.x is None or event.y is None:
                preferred_x = (
                    event.x if event.x is not None else DIRECTION_X[event.direction]
                )
                obstacles = obstacles_for_event(
                    visual_frames, event.start, event.end
                )
                placement = place_caption(
                    direction=event.direction,
                    preferred_x=preferred_x,
                    obstacles=obstacles,
                )
                event.x = placement.x
                event.y = placement.y
                event.align = placement.align
                event.placement_score = placement.score
            events.append(event)

    events.sort(key=lambda e: (e.start, e.end))
    return CaptionTrack(
        video=video_name,
        generated_by=generated_by or ["fuse"],
        events=events,
    )
