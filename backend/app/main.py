from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.datastructures import UploadFile

from .config import settings
from .crop_planner import (
    CropPlanningError,
    CropWindow,
    SmoothingOptions,
    plan_crop_windows,
)
from .exporter import export_video
from .jobs import JobNotFoundError, JobRegistry
from .models.locate_engine import get_locate_engine
from .models.sam2_engine import get_sam2_engine, get_sam2_video_engine
from .selection import (
    ClickSelection,
    ClickSelector,
    EmptySelectionError,
    SelectionInputError,
    SelectionUnavailableError,
    TextSelectionUnavailableError,
    TextSelector,
)
from .tracking import VideoTracker
from .videos import (
    InvalidFrameError,
    InvalidVideoError,
    VideoNotFoundError,
    VideoStore,
    VideoToolError,
    metadata_dict,
)


class VideoPathRequest(BaseModel):
    path: str


class VideoResponse(BaseModel):
    videoId: str
    width: int
    height: int
    fps: float
    nbFrames: int
    duration: float


class ClickSelectionRequest(BaseModel):
    videoId: str
    frameIdx: int = Field(ge=0)
    x: int = Field(ge=0)
    y: int = Field(ge=0)


class ClickSelectionResponse(BaseModel):
    box: tuple[int, int, int, int]
    maskPng: str
    score: float


class TextSelectionRequest(BaseModel):
    videoId: str
    frameIdx: int = Field(ge=0)
    prompt: str = Field(min_length=1, max_length=500)


class LocateCandidateResponse(BaseModel):
    box: tuple[int, int, int, int]
    score: float


class TextSelectionResponse(BaseModel):
    candidates: list[LocateCandidateResponse]


class TrackRequest(BaseModel):
    videoId: str
    frameIdx: int = Field(ge=0)
    box: tuple[int, int, int, int]


class TrackJobResponse(BaseModel):
    jobId: str


class SmoothingRequest(BaseModel):
    windowSec: float = Field(default=0.8, ge=0)
    deadZonePx: float = Field(default=30.0, ge=0)
    maxVelPxPerFrame: float = Field(default=28.0, gt=0)


class ExportRequest(BaseModel):
    videoId: str
    trackJobId: str
    outWidth: int = Field(ge=2)
    outHeight: int = Field(ge=2)
    zoom: float = 1.0
    smoothing: SmoothingRequest = Field(default_factory=SmoothingRequest)


def create_app(
    video_store: VideoStore | None = None,
    *,
    frontend_dist: Path | None = None,
    click_selector: Any | None = None,
    text_selector: Any | None = None,
    track_runner: Any | None = None,
    job_registry: JobRegistry | None = None,
    video_exporter: Any | None = None,
    exports_dir: Path | None = None,
) -> FastAPI:
    store = video_store or VideoStore(
        repo_root=settings.repo_root,
        data_dir=settings.data_dir,
        ffmpeg_binary=settings.ffmpeg_binary,
        ffprobe_binary=settings.ffprobe_binary,
        frame_cache_max_dimension=settings.frame_cache_max_dimension,
        tracking_max_dimension=settings.tracking_max_dimension,
    )
    sam_image_engine = get_sam2_engine(
        settings.sam2_checkpoint, settings.sam2_model_config
    )
    sam_video_engine = get_sam2_video_engine(
        settings.sam2_checkpoint,
        settings.sam2_model_config,
        offload_video_to_cpu=settings.sam2_offload_video_to_cpu,
        offload_state_to_cpu=settings.sam2_offload_state_to_cpu,
    )
    selector = click_selector
    if selector is None:
        selector = ClickSelector(
            store,
            engine_provider=lambda: sam_image_engine,
            crop_size=settings.sam2_crop_size,
        )
    locate_engine = get_locate_engine(settings.locate_model_id)
    text_grounder = text_selector
    if text_grounder is None:
        text_grounder = TextSelector(
            store,
            engine_provider=lambda: locate_engine,
            max_input_dimension=settings.locate_max_input_dimension,
        )
    tracker = track_runner
    if tracker is None:
        tracker = VideoTracker(
            store,
            engine_provider=lambda: sam_video_engine,
            rescue_engine_provider=(
                (lambda: locate_engine) if settings.locate_rescue_enabled else None
            ),
            rescue_after=settings.locate_rescue_after,
            rescue_min_score=settings.locate_rescue_min_score,
            rescue_max_input_dimension=settings.locate_max_input_dimension,
        )
    jobs = job_registry or JobRegistry()
    exporter = video_exporter or export_video
    export_root = exports_dir if exports_dir is not None else settings.exports_dir

    app = FastAPI(title="FindMe", version="0.1.0")
    app.state.video_store = store
    app.state.click_selector = selector
    app.state.text_selector = text_grounder
    app.state.track_runner = tracker
    app.state.job_registry = jobs
    app.state.video_exporter = exporter
    app.state.exports_dir = export_root
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/features")
    def features() -> dict[str, object]:
        enabled, reason = text_grounder.availability
        return {
            "textSelection": {
                "enabled": enabled,
                "reason": reason,
            }
        }

    @app.post(
        "/api/videos",
        response_model=VideoResponse,
        status_code=201,
        openapi_extra={
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "required": ["path"],
                            "properties": {"path": {"type": "string"}},
                        }
                    },
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "required": ["file"],
                            "properties": {"file": {"type": "string", "format": "binary"}},
                        }
                    },
                },
                "required": True,
            }
        },
    )
    async def register_video(request: Request) -> dict[str, Any]:
        try:
            content_type = request.headers.get("content-type", "").lower()
            if content_type.startswith("multipart/form-data"):
                form = await request.form()
                upload = form.get("file")
                if not isinstance(upload, UploadFile):
                    raise HTTPException(422, "Multipart request must include a file")
                await upload.seek(0)
                record = store.register_upload(upload.file, upload.filename)
            elif content_type.startswith("application/json"):
                try:
                    payload = VideoPathRequest.model_validate(await request.json())
                except (ValidationError, ValueError) as exc:
                    raise HTTPException(422, "JSON request must include a path") from exc
                record = store.register_path(payload.path)
            else:
                raise HTTPException(
                    415, "Use application/json or multipart/form-data"
                )
            return metadata_dict(record)
        except VideoNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except InvalidVideoError as exc:
            raise HTTPException(422, str(exc)) from exc
        except VideoToolError as exc:
            raise HTTPException(503, str(exc)) from exc

    @app.get("/api/videos/{video_id}/file", response_class=FileResponse)
    def video_file(video_id: str) -> FileResponse:
        try:
            record = store.get(video_id)
        except VideoNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        return FileResponse(record.path, media_type="video/mp4", filename=None)

    @app.get("/api/videos/{video_id}/frames/{frame_idx}", response_class=FileResponse)
    def video_frame(video_id: str, frame_idx: int) -> FileResponse:
        try:
            frame = store.extract_frame(video_id, frame_idx)
        except VideoNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except InvalidFrameError as exc:
            raise HTTPException(422, str(exc)) from exc
        except VideoToolError as exc:
            raise HTTPException(503, str(exc)) from exc
        return FileResponse(
            frame.path,
            media_type="image/jpeg",
            headers={
                "X-Frame-Width": str(frame.width),
                "X-Frame-Height": str(frame.height),
                "X-Source-Scale-X": f"{frame.scale_x:.6f}",
                "X-Source-Scale-Y": f"{frame.scale_y:.6f}",
            },
        )

    @app.post("/api/select/click", response_model=ClickSelectionResponse)
    def select_click(payload: ClickSelectionRequest) -> dict[str, object]:
        try:
            if locate_engine.is_loaded:
                locate_engine.unload()
            result: ClickSelection = selector.select_click(
                payload.videoId,
                payload.frameIdx,
                payload.x,
                payload.y,
            )
        except VideoNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (InvalidFrameError, SelectionInputError, EmptySelectionError) as exc:
            raise HTTPException(422, str(exc)) from exc
        except (VideoToolError, SelectionUnavailableError) as exc:
            raise HTTPException(503, str(exc)) from exc
        return {
            "box": result.box,
            "maskPng": result.mask_png,
            "score": result.score,
        }

    @app.post("/api/select/text", response_model=TextSelectionResponse)
    def select_text(payload: TextSelectionRequest) -> dict[str, object]:
        try:
            if sam_image_engine.is_loaded:
                sam_image_engine.unload()
            if sam_video_engine.is_loaded:
                sam_video_engine.unload()
            candidates = text_grounder.select_text(
                payload.videoId,
                payload.frameIdx,
                payload.prompt,
            )
        except VideoNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except (InvalidFrameError, SelectionInputError) as exc:
            raise HTTPException(422, str(exc)) from exc
        except TextSelectionUnavailableError as exc:
            raise HTTPException(501, str(exc)) from exc
        except VideoToolError as exc:
            raise HTTPException(503, str(exc)) from exc
        return {
            "candidates": [
                {"box": candidate.box, "score": candidate.score}
                for candidate in candidates
            ]
        }

    @app.post("/api/track", response_model=TrackJobResponse, status_code=202)
    def start_track(payload: TrackRequest) -> dict[str, str]:
        try:
            record = store.get(payload.videoId)
        except VideoNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        if payload.frameIdx >= record.metadata.nb_frames:
            raise HTTPException(
                422,
                f"Frame index must be between 0 and {record.metadata.nb_frames - 1}",
            )
        x1, y1, x2, y2 = payload.box
        if not (
            0 <= x1 < x2 <= record.metadata.width
            and 0 <= y1 < y2 <= record.metadata.height
        ):
            raise HTTPException(422, "Track box must be inside the source frame")
        if locate_engine.is_loaded:
            locate_engine.unload()
        if sam_image_engine.is_loaded:
            sam_image_engine.unload()
        box = tuple(payload.box)
        job_id = jobs.submit(
            lambda report: tracker.track(
                payload.videoId,
                payload.frameIdx,
                box,
                on_update=report,
            )
        )
        return {"jobId": job_id}

    @app.get("/api/track/{job_id}")
    def get_track(job_id: str) -> dict[str, object]:
        try:
            return jobs.get(job_id).to_dict()
        except JobNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc

    def build_export_plan(
        *,
        video_id: str,
        track_job_id: str,
        out_width: int,
        out_height: int,
        zoom: float,
        window_sec: float,
        dead_zone_px: float,
        max_velocity: float,
    ) -> tuple[Any, list[CropWindow]]:
        try:
            record = store.get(video_id)
        except VideoNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        try:
            track_snapshot = jobs.get(track_job_id)
        except JobNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        if track_snapshot.state != "completed":
            raise HTTPException(409, "Tracking job is not complete")
        if out_width % 2 or out_height % 2:
            raise HTTPException(422, "Output dimensions must be even")

        centers: list[tuple[float, float] | None] = [
            None
        ] * record.metadata.nb_frames
        for frame in track_snapshot.track:
            if (
                0 <= frame.frame_idx < len(centers)
                and not frame.lost
                and frame.center is not None
            ):
                centers[frame.frame_idx] = frame.center
        try:
            windows = plan_crop_windows(
                centers,
                source_width=record.metadata.width,
                source_height=record.metadata.height,
                output_width=out_width,
                output_height=out_height,
                fps=record.metadata.fps,
                zoom=zoom,
                smoothing=SmoothingOptions(
                    window_sec=window_sec,
                    dead_zone_px=dead_zone_px,
                    max_velocity=max_velocity,
                ),
            )
        except CropPlanningError as exc:
            raise HTTPException(422, str(exc)) from exc
        return record, windows

    @app.get("/api/export/plan")
    def export_plan(
        videoId: str,
        trackJobId: str,
        outWidth: int,
        outHeight: int,
        zoom: float = 1.0,
        windowSec: float = 0.8,
        deadZonePx: float = 30.0,
        maxVelPxPerFrame: float = 28.0,
    ) -> dict[str, object]:
        _record, windows = build_export_plan(
            video_id=videoId,
            track_job_id=trackJobId,
            out_width=outWidth,
            out_height=outHeight,
            zoom=zoom,
            window_sec=windowSec,
            dead_zone_px=deadZonePx,
            max_velocity=maxVelPxPerFrame,
        )
        return {
            "videoId": videoId,
            "trackJobId": trackJobId,
            "windows": [window.to_dict() for window in windows],
        }

    @app.post("/api/export", response_model=TrackJobResponse, status_code=202)
    def start_export(payload: ExportRequest) -> dict[str, str]:
        record, windows = build_export_plan(
            video_id=payload.videoId,
            track_job_id=payload.trackJobId,
            out_width=payload.outWidth,
            out_height=payload.outHeight,
            zoom=payload.zoom,
            window_sec=payload.smoothing.windowSec,
            dead_zone_px=payload.smoothing.deadZonePx,
            max_velocity=payload.smoothing.maxVelPxPerFrame,
        )

        def run_export(job_id: str, report: Any) -> None:
            exporter(
                record.path,
                export_root / f"{job_id}.mp4",
                windows,
                output_width=payload.outWidth,
                output_height=payload.outHeight,
                fps=record.metadata.fps,
                on_progress=report,
            )

        job_id = jobs.submit_progress(
            run_export,
            completion_message="Export complete",
        )
        return {"jobId": job_id}

    @app.get("/api/exports/{job_id}.mp4", response_class=FileResponse)
    def exported_video(job_id: str) -> FileResponse:
        try:
            snapshot = jobs.get(job_id)
        except JobNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        if snapshot.state not in ("completed", "failed"):
            raise HTTPException(409, "Export is not complete")
        destination = export_root / f"{job_id}.mp4"
        if snapshot.state == "failed" or not destination.is_file():
            raise HTTPException(404, "Exported video not found")
        return FileResponse(
            destination,
            media_type="video/mp4",
            filename=f"findme-{job_id}.mp4",
        )

    @app.websocket("/ws/jobs/{job_id}")
    async def track_updates(websocket: WebSocket, job_id: str) -> None:
        try:
            snapshot = jobs.get(job_id)
        except JobNotFoundError:
            await websocket.close(code=4404, reason="Tracking job not found")
            return
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(snapshot.to_dict())
                if snapshot.state in ("completed", "failed"):
                    return
                snapshot = await asyncio.to_thread(
                    jobs.wait_for_update,
                    job_id,
                    snapshot.version,
                    30.0,
                )
        except WebSocketDisconnect:
            return

    static_dir = frontend_dist if frontend_dist is not None else settings.frontend_dist
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    return app


app = create_app()
