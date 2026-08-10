"""Adaptive streaming server — HLS + network throttle + player UI."""

from __future__ import annotations

import asyncio
import json
import mimetypes
from pathlib import Path

import aiofiles
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from server.throttle import parse_trace_file, throttle

ROOT = Path(__file__).resolve().parents[1]
HLS_ROOT = ROOT / "content" / "hls"
PLAYER_ROOT = ROOT / "player"
TRACES_ROOT = ROOT / "traces"
SOURCE_ROOT = ROOT / "content" / "source"
STUDY_ROOT = ROOT / "content" / "study_results"

CHUNK_SIZE = 16 * 1024

app = FastAPI(title="Adaptive Video Streaming", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ThrottleUpdate(BaseModel):
    enabled: bool = False
    trace: str | None = None
    loop: bool = True
    reset: bool = True


class StudyResult(BaseModel):
    participant: str
    video: str
    startedAt: str | None = None
    finishedAt: str | None = None
    summary: dict | None = None
    trials: list[dict] = []


def list_packages() -> list[dict]:
    if not HLS_ROOT.exists():
        return []
    packages = []
    for path in sorted(HLS_ROOT.iterdir()):
        if not path.is_dir():
            continue
        manifest = path / "manifest.json"
        master = path / "master.m3u8"
        if master.exists():
            packages.append(
                {
                    "name": path.name,
                    "manifest_url": f"/api/videos/{path.name}/manifest.json",
                    "master_playlist_url": f"/hls/{path.name}/master.m3u8",
                    "captions_url": f"/api/videos/{path.name}/captions.json",
                    "has_manifest": manifest.exists(),
                    "has_captions": (path / "captions.json").exists(),
                }
            )
    return packages


def safe_hls_path(rel: str) -> Path:
    candidate = (HLS_ROOT / rel).resolve()
    if not str(candidate).startswith(str(HLS_ROOT.resolve())):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return candidate


def should_throttle(path: Path) -> bool:
    # Throttle media segments / init segments; keep playlists snappy.
    suffix = path.suffix.lower()
    return suffix in {".m4s", ".ts", ".mp4", ".aac", ".m4a"}


async def throttled_bytes(path: Path, mbps: float):
    bytes_per_sec = max(mbps, 0.05) * 1_000_000 / 8.0
    async with aiofiles.open(path, "rb") as handle:
        while True:
            chunk = await handle.read(CHUNK_SIZE)
            if not chunk:
                break
            yield chunk
            await asyncio.sleep(len(chunk) / bytes_per_sec)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "throttle": throttle.status()}


@app.get("/api/videos")
async def videos() -> dict:
    return {"videos": list_packages()}


@app.get("/api/videos/{name}/manifest.json")
async def video_manifest(name: str) -> Response:
    path = HLS_ROOT / name / "manifest.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Manifest not found for '{name}'")
    async with aiofiles.open(path, "r") as handle:
        content = await handle.read()
    return Response(content=content, media_type="application/json")


@app.get("/api/videos/{name}/captions.json")
async def video_captions(name: str) -> Response:
    path = HLS_ROOT / name / "captions.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Captions not found for '{name}'")
    async with aiofiles.open(path, "r") as handle:
        content = await handle.read()
    return Response(content=content, media_type="application/json")


@app.get("/api/traces")
async def traces() -> dict:
    if not TRACES_ROOT.exists():
        return {"traces": []}
    items = []
    for path in sorted(TRACES_ROOT.glob("*.txt")):
        try:
            samples = parse_trace_file(path)
        except ValueError:
            continue
        items.append(
            {
                "name": path.stem,
                "samples": len(samples),
                "min_mbps": min(samples),
                "max_mbps": max(samples),
                "url": f"/traces/{path.name}",
            }
        )
    return {"traces": items}


@app.get("/api/throttle")
async def get_throttle() -> dict:
    return throttle.status()


@app.post("/api/throttle")
async def set_throttle(body: ThrottleUpdate) -> dict:
    if body.enabled:
        if not body.trace:
            raise HTTPException(status_code=400, detail="trace is required when enabling")
        path = TRACES_ROOT / f"{body.trace}.txt"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Unknown trace '{body.trace}'")
        throttle.samples_mbps = parse_trace_file(path)
        throttle.trace = body.trace
        throttle.loop = body.loop
        throttle.enabled = True
        if body.reset or throttle.started_at is None:
            throttle.reset_clock()
    else:
        throttle.enabled = False
        throttle.trace = body.trace
        throttle.loop = body.loop
        if body.reset:
            throttle.started_at = None
    return throttle.status()


@app.post("/api/throttle/reset")
async def reset_throttle() -> dict:
    if throttle.enabled:
        throttle.reset_clock()
    return throttle.status()


@app.get("/")
async def index() -> FileResponse:
    index_path = PLAYER_ROOT / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Player not found")
    return FileResponse(index_path)


@app.get("/study")
async def study_page() -> FileResponse:
    path = PLAYER_ROOT / "study.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Study page not found")
    return FileResponse(path)


@app.get("/api/study/trials")
async def study_trials(video: str = "dialogue_demo") -> dict:
    captions_path = HLS_ROOT / video / "captions.json"
    cues_path = SOURCE_ROOT / f"{video}.cues.json"
    if not captions_path.exists():
        raise HTTPException(status_code=404, detail=f"No captions for '{video}'")
    if not cues_path.exists():
        raise HTTPException(status_code=404, detail=f"No ground-truth cues for '{video}'")

    async with aiofiles.open(captions_path, "r") as handle:
        captions = json.loads(await handle.read())
    async with aiofiles.open(cues_path, "r") as handle:
        cues = json.loads(await handle.read())

    trials = [
        {
            "start": float(item["start"]),
            "end": float(item["end"]),
            "speaker": item["speaker"],
            "side": str(item["side"]).upper(),
            "text": item["text"],
        }
        for item in cues
    ]
    return {"video": video, "trials": trials, "captions": captions}


@app.post("/api/study/results")
async def save_study_results(body: StudyResult) -> dict:
    STUDY_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = body.finishedAt or body.startedAt or "session"
    safe_participant = "".join(ch for ch in body.participant if ch.isalnum() or ch in "-_")[:40]
    path = STUDY_ROOT / f"{safe_participant}-{stamp.replace(':', '').replace('+', '')}.json"
    path.write_text(body.model_dump_json(indent=2) + "\n")
    return {"saved": str(path.name)}


@app.get("/hls/{file_path:path}")
async def serve_hls(file_path: str):
    path = safe_hls_path(file_path)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix.lower() == ".m3u8":
        media_type = "application/vnd.apple.mpegurl"

    headers = {"Cache-Control": "no-cache"}
    mbps = throttle.current_mbps() if should_throttle(path) else None
    if mbps is None:
        return FileResponse(path, media_type=media_type, headers=headers)

    headers["X-Simulated-Mbps"] = f"{mbps:.3f}"
    headers["X-Throttle-Trace"] = throttle.trace or ""
    return StreamingResponse(
        throttled_bytes(path, mbps),
        media_type=media_type,
        headers=headers,
    )


app.mount("/player", StaticFiles(directory=str(PLAYER_ROOT)), name="player")
app.mount("/traces", StaticFiles(directory=str(TRACES_ROOT)), name="traces_static")
