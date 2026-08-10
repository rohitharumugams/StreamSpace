"""Smart captions data model."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Direction = Literal["LEFT", "CENTER", "RIGHT"]
EventKind = Literal["speech", "sound"]


class CaptionEvent(BaseModel):
    id: str
    start: float
    end: float
    text: str
    kind: EventKind = "speech"
    speaker: str | None = None
    direction: Direction = "CENTER"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    # Normalized placement anchor [0, 1]
    x: float | None = Field(default=None, ge=0.0, le=1.0)
    y: float | None = Field(default=None, ge=0.0, le=1.0)
    align: Direction | None = None
    placement_score: float | None = None
    # Fusion diagnostics
    stereo_direction: Direction | None = None
    vision_direction: Direction | None = None
    fusion_source: str | None = None


class CaptionTrack(BaseModel):
    video: str
    language: str = "en"
    mode_default: str = "spatial"
    generated_by: list[str] = Field(default_factory=list)
    events: list[CaptionEvent] = Field(default_factory=list)
