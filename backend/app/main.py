from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError
from starlette.datastructures import UploadFile

from .config import settings
from .models.sam2_engine import get_sam2_engine
from .selection import (
    ClickSelection,
    ClickSelector,
    EmptySelectionError,
    SelectionInputError,
    SelectionUnavailableError,
)
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


def create_app(
    video_store: VideoStore | None = None,
    *,
    frontend_dist: Path | None = None,
    click_selector: Any | None = None,
) -> FastAPI:
    store = video_store or VideoStore(
        repo_root=settings.repo_root,
        data_dir=settings.data_dir,
        ffmpeg_binary=settings.ffmpeg_binary,
        ffprobe_binary=settings.ffprobe_binary,
        frame_cache_max_dimension=settings.frame_cache_max_dimension,
    )
    selector = click_selector
    if selector is None:
        selector = ClickSelector(
            store,
            engine_provider=lambda: get_sam2_engine(
                settings.sam2_checkpoint, settings.sam2_model_config
            ),
            crop_size=settings.sam2_crop_size,
        )

    app = FastAPI(title="FindMe", version="0.1.0")
    app.state.video_store = store
    app.state.click_selector = selector
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

    static_dir = frontend_dist if frontend_dist is not None else settings.frontend_dist
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    return app


app = create_app()
