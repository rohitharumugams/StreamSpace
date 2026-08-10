"""Visual speaker-candidate detection from video frames.

Uses:
  1) OpenCV Haar face detection (frontal + profile) when faces are present
  2) Colored speaker-panel detection for the synthetic dialogue demo
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

from captions.schema import Direction
from captions.stereo import x_from_balance


@dataclass
class VisualDetection:
    x: float  # normalized bbox center [0, 1]
    y: float
    w: float
    h: float
    direction: Direction
    source: str  # "face" | "panel"
    confidence: float
    track_id: str | None = None


@dataclass
class VisualFrame:
    time: float
    detections: list[VisualDetection]


def _direction_from_x(x: float) -> Direction:
    if x < 0.38:
        return "LEFT"
    if x > 0.62:
        return "RIGHT"
    return "CENTER"


def _nms(dets: list[VisualDetection], iou_thresh: float = 0.35) -> list[VisualDetection]:
    """Greedy NMS on normalized boxes (sorted by confidence then size)."""
    if len(dets) <= 1:
        return dets

    ordered = sorted(dets, key=lambda d: (d.confidence, d.w * d.h), reverse=True)
    kept: list[VisualDetection] = []

    def iou(a: VisualDetection, b: VisualDetection) -> float:
        ax1, ay1 = a.x - a.w / 2, a.y - a.h / 2
        ax2, ay2 = a.x + a.w / 2, a.y + a.h / 2
        bx1, by1 = b.x - b.w / 2, b.y - b.h / 2
        bx2, by2 = b.x + b.w / 2, b.y + b.h / 2
        ix = max(0.0, min(ax2, bx2) - max(ax1, bx1))
        iy = max(0.0, min(ay2, by2) - max(ay1, by1))
        inter = ix * iy
        if inter <= 0:
            return 0.0
        union = a.w * a.h + b.w * b.h - inter
        return inter / union if union > 0 else 0.0

    for det in ordered:
        if any(iou(det, k) >= iou_thresh for k in kept):
            continue
        kept.append(det)
    return kept


def _detect_faces(frame_bgr: np.ndarray, cascades: list[cv2.CascadeClassifier]) -> list[VisualDetection]:
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    h, w = gray.shape
    dets: list[VisualDetection] = []
    for cascade in cascades:
        if cascade.empty():
            continue
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.08,
            minNeighbors=3,
            minSize=(28, 28),
            flags=cv2.CASCADE_SCALE_IMAGE,
        )
        for x, y, fw, fh in faces:
            # Reject tiny / absurd aspect ratios
            if fw < 24 or fh < 24:
                continue
            aspect = fw / max(fh, 1)
            if aspect < 0.55 or aspect > 1.7:
                continue
            cx = (x + fw / 2) / w
            cy = (y + fh / 2) / h
            size = (fw / w) * (fh / h)
            conf = min(0.92, 0.62 + min(0.3, size * 4.0))
            dets.append(
                VisualDetection(
                    x=float(cx),
                    y=float(cy),
                    w=float(fw / w),
                    h=float(fh / h),
                    direction=_direction_from_x(cx),
                    source="face",
                    confidence=float(conf),
                )
            )
    return _nms(dets)


def _detect_speaker_panels(frame_bgr: np.ndarray) -> list[VisualDetection]:
    """Detect the green/blue speaker panels used in dialogue_demo."""
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    h, w = frame_bgr.shape[:2]
    dets: list[VisualDetection] = []

    green_mask = cv2.inRange(hsv, (35, 40, 20), (95, 255, 180))
    blue_mask = cv2.inRange(hsv, (90, 40, 20), (130, 255, 180))

    for mask, expected_side, track_id in (
        (green_mask, "LEFT", "panel-left"),
        (blue_mask, "RIGHT", "panel-right"),
    ):
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(contour)
        if area < (w * h) * 0.02:
            continue
        x, y, bw, bh = cv2.boundingRect(contour)
        cx = (x + bw / 2) / w
        cy = (y + bh / 2) / h
        direction = _direction_from_x(cx)
        conf = 0.85 if direction == expected_side else 0.55
        dets.append(
            VisualDetection(
                x=float(cx),
                y=float(cy),
                w=float(bw / w),
                h=float(bh / h),
                direction=direction,
                source="panel",
                confidence=conf,
                track_id=track_id,
            )
        )
    return dets


def analyze_video_speakers(
    video_path: Path,
    sample_times: list[float] | None = None,
    sample_hz: float = 1.0,
) -> list[VisualFrame]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / fps if fps > 0 else 0.0

    cascade_dir = Path(cv2.data.haarcascades)
    cascades = [
        cv2.CascadeClassifier(str(cascade_dir / "haarcascade_frontalface_default.xml")),
        cv2.CascadeClassifier(str(cascade_dir / "haarcascade_profileface.xml")),
    ]

    if sample_times is None:
        if duration <= 0:
            sample_times = [0.0]
        else:
            step = 1.0 / max(sample_hz, 0.1)
            t = 0.0
            sample_times = []
            while t <= duration:
                sample_times.append(round(t, 3))
                t += step

    frames: list[VisualFrame] = []
    for t in sample_times:
        frame_idx = int(max(0, min(frame_count - 1, round(t * fps))))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        detections = _detect_faces(frame, cascades)
        if not detections:
            detections = _detect_speaker_panels(frame)
        detections = sorted(detections, key=lambda d: d.x)
        for i, det in enumerate(detections):
            if det.track_id is None:
                if det.direction == "LEFT":
                    det.track_id = "vis-left"
                elif det.direction == "RIGHT":
                    det.track_id = "vis-right"
                else:
                    det.track_id = f"vis-center-{i}"
        frames.append(VisualFrame(time=float(t), detections=detections))

    cap.release()
    return frames


def vision_candidates_for_span(
    frames: list[VisualFrame],
    start: float,
    end: float,
    *,
    window_s: float = 1.25,
) -> list[VisualDetection]:
    """Collect visual speaker candidates near an utterance span."""
    if not frames:
        return []
    mid = (start + end) / 2.0
    nearby = [f for f in frames if abs(f.time - mid) <= window_s]
    if not nearby:
        nearby = [min(frames, key=lambda f: abs(f.time - mid))]

    # Prefer detections closer in time to the cue midpoint.
    scored: list[tuple[float, VisualDetection]] = []
    for frame in nearby:
        time_w = 1.0 - min(1.0, abs(frame.time - mid) / max(window_s, 1e-3))
        for d in frame.detections:
            scored.append((time_w * d.confidence, d))

    best: dict[str, tuple[float, VisualDetection]] = {}
    for score, d in scored:
        # Bucket by coarse horizontal bin so the same person merges across frames.
        bin_x = int(round(d.x * 6))
        key = d.track_id or f"{d.source}-{bin_x}"
        prev = best.get(key)
        if prev is None or score > prev[0]:
            best[key] = (score, d)

    dets = [item[1] for item in best.values()]
    return sorted(_nms(dets, iou_thresh=0.4), key=lambda d: d.x)


def pick_visual_speaker(
    dets: list[VisualDetection],
    *,
    stereo_balance: float = 0.0,
    stereo_dir: Direction | None = None,
) -> VisualDetection | None:
    """Choose the active speaker face/panel using stereo as a prior."""
    if not dets:
        return None

    target_x = x_from_balance(stereo_balance)
    best: VisualDetection | None = None
    best_score = -1e9
    for d in dets:
        src_bonus = 0.2 if d.source == "face" else 0.0
        prox = 1.0 - min(1.0, abs(d.x - target_x) / 0.55)
        side_bonus = 0.0
        if stereo_dir and stereo_dir != "CENTER" and d.direction == stereo_dir:
            side_bonus = 0.25
        elif stereo_dir == "CENTER":
            # Mild preference for larger/central faces when audio is center-mixed.
            side_bonus = 0.08 * (1.0 - abs(d.x - 0.5) * 1.2)
        size_bonus = min(0.25, d.w * d.h * 3.5)
        score = d.confidence + src_bonus + 0.55 * prox + side_bonus + size_bonus
        if score > best_score:
            best_score = score
            best = d
    return best


def vision_for_span(
    frames: list[VisualFrame],
    start: float,
    end: float,
    preferred: Direction | None = None,
    stereo_balance: float = 0.0,
) -> tuple[Direction | None, float, float | None, list[VisualDetection], VisualDetection | None]:
    """Return visual direction near an utterance, disambiguated by stereo."""
    dets = vision_candidates_for_span(frames, start, end)
    if not dets:
        return None, 0.0, None, [], None

    chosen = pick_visual_speaker(
        dets,
        stereo_balance=stereo_balance,
        stereo_dir=preferred,
    )
    if chosen is None:
        return None, 0.0, None, dets, None
    return chosen.direction, float(chosen.confidence), float(chosen.x), dets, chosen


def dump_visual_frames(frames: list[VisualFrame], path: Path) -> None:
    payload = [
        {"time": f.time, "detections": [asdict(d) for d in f.detections]} for f in frames
    ]
    path.write_text(json.dumps(payload, indent=2) + "\n")
