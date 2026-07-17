from __future__ import annotations

import asyncio
import posixpath
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

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
from .tracking import VideoTracker, persist_completed_track
from .videos import (
    InvalidFrameError,
    InvalidVideoError,
    VideoNotFoundError,
    VideoStore,
    VideoToolError,
    metadata_dict,
    sanitize_display_name,
)


class SPAStaticFiles(StaticFiles):
    """Serve static assets normally and route client-side paths to index.html."""

    async def get_response(self, path: str, scope: dict[str, Any]) -> Any:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or not self._is_spa_route(path, scope):
                raise
        return await super().get_response("index.html", scope)

    @staticmethod
    def _is_spa_route(path: str, scope: dict[str, Any]) -> bool:
        if scope.get("method") not in ("GET", "HEAD"):
            return False
        normalized = path.lstrip("/")
        first_segment = normalized.partition("/")[0]
        if first_segment in {"api", "assets", "ws"}:
            return False
        return posixpath.splitext(normalized)[1] == ""


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
    responsiveness: float | None = Field(default=None, ge=0)
    maxAccelPxPerFrame2: float | None = Field(default=None, gt=0)
    windowSec: float | None = Field(default=None, ge=0)
    deadZonePx: float | None = Field(default=None, ge=0)
    maxVelPxPerFrame: float | None = Field(default=None, gt=0)

    @property
    def tau(self) -> float:
        return self.responsiveness if self.responsiveness is not None else (self.windowSec if self.windowSec is not None else 0.5)

    @property
    def max_accel(self) -> float:
        return self.maxAccelPxPerFrame2 if self.maxAccelPxPerFrame2 is not None else 3.0


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
    for saved_track in store.library.iter_tracks():
        try:
            store.get(saved_track.video_id)
        except VideoNotFoundError:
            continue
        jobs.restore_completed(saved_track.job_id, saved_track.track)
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
            ),
            on_completed=lambda completed_id, track: persist_completed_track(
                store.library,
                video_id=payload.videoId,
                job_id=completed_id,
                anchor_frame_idx=payload.frameIdx,
                box=box,
                track=track,
            ),
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
        responsiveness: float,
        max_acceleration: float,
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
                    responsiveness=responsiveness,
                    max_acceleration=max_acceleration,
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
        responsiveness: float | None = None,
        maxAccelPxPerFrame2: float | None = None,
        windowSec: float | None = None,
        deadZonePx: float = 30.0,
        maxVelPxPerFrame: float | None = None,
    ) -> dict[str, object]:
        _record, windows = build_export_plan(
            video_id=videoId,
            track_job_id=trackJobId,
            out_width=outWidth,
            out_height=outHeight,
            zoom=zoom,
            responsiveness=responsiveness if responsiveness is not None else (windowSec if windowSec is not None else 0.5),
            max_acceleration=maxAccelPxPerFrame2 if maxAccelPxPerFrame2 is not None else 3.0,
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
            responsiveness=payload.smoothing.tau,
            max_acceleration=payload.smoothing.max_accel,
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
            on_completed=lambda completed_id: store.library.save_export(
                completed_id,
                payload.videoId,
                payload.trackJobId,
                {
                    "outWidth": payload.outWidth,
                    "outHeight": payload.outHeight,
                    "zoom": payload.zoom,
                    "smoothing": payload.smoothing.model_dump(exclude_none=True),
                },
                export_root / f"{completed_id}.mp4",
            ),
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

    @app.get("/api/library")
    def get_library() -> dict[str, object]:
        tracks = store.library.iter_tracks()
        exports = store.library.exports()
        catalog = store.library.videos()
        by_video_tracks: dict[str, list[dict[str, object]]] = {}
        for track in tracks:
            by_video_tracks.setdefault(track.video_id, []).append(
                {
                    "jobId": track.job_id,
                    "anchorFrameIdx": track.anchor_frame_idx,
                    "box": list(track.box),
                    "frameCount": len(track.track),
                    "lostCount": sum(frame.lost for frame in track.track),
                    "createdAt": track.created_at,
                }
            )
        by_video_exports: dict[str, list[dict[str, object]]] = {}
        for item in exports:
            by_video_exports.setdefault(str(item.get("videoId", "")), []).append(
                {**item, "sourceExists": Path(str(item.get("path", ""))).is_file()}
            )
        return {
            "cacheBytes": store.library.cache_bytes(),
            "videos": [
                {
                    "videoId": str(item["videoId"]),
                    "name": sanitize_display_name(item.get("name"))
                    or Path(str(item.get("path", ""))).name,
                    "sourceKind": item.get("sourceKind", "path"),
                    "path": str(item.get("path", "")),
                    "metadata": {"videoId": str(item["videoId"]), **dict(item.get("metadata", {}))},
                    "size": Path(str(item.get("path", ""))).stat().st_size if Path(str(item.get("path", ""))).is_file() else 0,
                    "openedAt": item.get("openedAt"),
                    "sourceExists": Path(str(item.get("path", ""))).is_file(),
                    "tracks": by_video_tracks.get(str(item["videoId"]), []),
                    "exports": by_video_exports.get(str(item["videoId"]), []),
                }
                for item in catalog
            ]
        }

    def delete_export_file(entry: dict[str, object]) -> None:
        path = Path(str(entry.get("path", "")))
        if path.is_file():
            path.unlink()

    @app.delete("/api/library/tracks/{job_id}", status_code=204)
    def delete_library_track(job_id: str) -> Response:
        saved = store.library.remove_track(job_id)
        if saved is None:
            raise HTTPException(404, "Track not found")
        jobs.remove(job_id)
        for exported in store.library.remove_exports(lambda item: item.get("trackJobId") == job_id):
            delete_export_file(exported)
        return Response(status_code=204)

    @app.delete("/api/library/exports/{export_id}", status_code=204)
    def delete_library_export(export_id: str) -> Response:
        removed = store.library.remove_exports(lambda item: item.get("exportId") == export_id)
        if not removed:
            raise HTTPException(404, "Export not found")
        for exported in removed:
            delete_export_file(exported)
        return Response(status_code=204)

    @app.delete("/api/library/videos/{video_id}", status_code=204)
    def delete_library_video(video_id: str) -> Response:
        try:
            store.remove(video_id)
        except VideoNotFoundError as exc:
            if not any(item.get("videoId") == video_id for item in store.library.videos()):
                raise HTTPException(404, str(exc)) from exc
            store.library.remove_video(video_id)
        for saved in [track for track in store.library.iter_tracks() if track.video_id == video_id]:
            store.library.remove_track(saved.job_id)
            jobs.remove(saved.job_id)
        for exported in store.library.remove_exports(lambda item: item.get("videoId") == video_id):
            delete_export_file(exported)
        return Response(status_code=204)

    @app.post("/api/library/maintenance/clear-caches")
    def clear_library_caches() -> dict[str, int]:
        return {"bytesFreed": store.library.clear_caches()}

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
        app.mount("/", SPAStaticFiles(directory=static_dir, html=True), name="frontend")
    return app


app = create_app()
