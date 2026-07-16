from __future__ import annotations

import json
import shutil
import subprocess
import threading
import uuid
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import BinaryIO


class VideoStoreError(Exception):
    """Base error for video registration and frame extraction."""


class VideoNotFoundError(VideoStoreError):
    """Raised when a path or registration ID does not exist."""


class InvalidVideoError(VideoStoreError):
    """Raised when ffprobe cannot read a usable video stream."""


class InvalidFrameError(VideoStoreError):
    """Raised when a requested frame index is outside the video."""


class VideoToolError(VideoStoreError):
    """Raised when ffmpeg or ffprobe is unavailable or fails."""


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    width: int
    height: int
    fps: float
    nb_frames: int
    duration: float


@dataclass(frozen=True, slots=True)
class VideoRecord:
    video_id: str
    path: Path
    metadata: VideoMetadata
    frame_cache_dir: Path


@dataclass(frozen=True, slots=True)
class ExtractedFrame:
    path: Path
    width: int
    height: int
    scale_x: float
    scale_y: float


@dataclass(frozen=True, slots=True)
class ExtractedSourceCrop:
    path: Path
    x: int
    y: int
    width: int
    height: int


class VideoStore:
    """In-memory registry backed by persisted uploads and cached JPEG frames."""

    def __init__(
        self,
        *,
        repo_root: Path,
        data_dir: Path,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
        frame_cache_max_dimension: int = 2048,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.data_dir = data_dir.resolve()
        self.upload_dir = self.data_dir / "uploads"
        self.frame_cache_root = self.data_dir / "frames"
        self.selection_crop_root = self.data_dir / "selection-crops"
        self.ffmpeg_binary = ffmpeg_binary
        self.ffprobe_binary = ffprobe_binary
        self.frame_cache_max_dimension = frame_cache_max_dimension
        self._records: dict[str, VideoRecord] = {}
        self._lock = threading.RLock()

    def register_path(self, raw_path: str | Path) -> VideoRecord:
        requested_path = Path(raw_path).expanduser()
        path = requested_path if requested_path.is_absolute() else self.repo_root / requested_path
        path = path.resolve()
        if not path.is_file():
            raise VideoNotFoundError(f"Video file not found: {raw_path}")
        return self._register(path)

    def register_upload(
        self, source: BinaryIO, filename: str | None = None
    ) -> VideoRecord:
        suffix = Path(filename or "upload.mp4").suffix.lower() or ".mp4"
        upload_id = uuid.uuid4().hex
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        destination = self.upload_dir / f"{upload_id}{suffix}"
        try:
            with destination.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
            return self._register(destination)
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    def get(self, video_id: str) -> VideoRecord:
        with self._lock:
            try:
                return self._records[video_id]
            except KeyError as exc:
                raise VideoNotFoundError("Video not found") from exc

    def extract_frame(self, video_id: str, frame_idx: int) -> ExtractedFrame:
        record = self.get(video_id)
        metadata = record.metadata
        self._validate_frame_index(metadata, frame_idx)

        frame_path = record.frame_cache_dir / f"{frame_idx:08d}.jpg"
        metadata_path = frame_path.with_suffix(".json")
        with self._lock:
            if not frame_path.is_file():
                self._extract_frame_file(record, frame_idx, frame_path)
            frame_metadata = self._load_or_probe_frame_metadata(
                frame_path, metadata_path
            )

        width = int(frame_metadata["width"])
        height = int(frame_metadata["height"])
        return ExtractedFrame(
            path=frame_path,
            width=width,
            height=height,
            scale_x=width / metadata.width,
            scale_y=height / metadata.height,
        )

    def extract_source_crop(
        self,
        video_id: str,
        *,
        frame_idx: int,
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> ExtractedSourceCrop:
        """Extract and cache an exact, full-resolution source-pixel crop."""
        record = self.get(video_id)
        metadata = record.metadata
        self._validate_frame_index(metadata, frame_idx)
        if (
            x < 0
            or y < 0
            or width <= 0
            or height <= 0
            or x + width > metadata.width
            or y + height > metadata.height
        ):
            raise InvalidFrameError("Crop must be fully inside the source frame")

        filename = f"{frame_idx:08d}_{x}_{y}_{width}_{height}.png"
        destination = self.selection_crop_root / video_id / filename
        with self._lock:
            if not destination.is_file():
                self._extract_source_crop_file(
                    record,
                    frame_idx=frame_idx,
                    x=x,
                    y=y,
                    width=width,
                    height=height,
                    destination=destination,
                )
        return ExtractedSourceCrop(
            path=destination,
            x=x,
            y=y,
            width=width,
            height=height,
        )

    def _register(self, path: Path) -> VideoRecord:
        metadata = self._probe_video(path)
        video_id = uuid.uuid4().hex
        record = VideoRecord(
            video_id=video_id,
            path=path,
            metadata=metadata,
            frame_cache_dir=self.frame_cache_root / video_id,
        )
        with self._lock:
            self._records[video_id] = record
        return record

    def _probe_video(self, path: Path) -> VideoMetadata:
        payload = self._run_ffprobe(
            path,
            "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames,duration:format=duration",
        )
        streams = payload.get("streams", [])
        if not streams:
            raise InvalidVideoError("No video stream found")

        stream = streams[0]
        try:
            width = int(stream["width"])
            height = int(stream["height"])
            fps = _first_positive_rate(
                stream.get("avg_frame_rate"), stream.get("r_frame_rate")
            )
            duration = _first_positive_float(
                stream.get("duration"), payload.get("format", {}).get("duration")
            )
            raw_frame_count = stream.get("nb_frames")
            nb_frames = (
                int(raw_frame_count)
                if raw_frame_count not in (None, "N/A", "")
                else round(duration * fps)
            )
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            raise InvalidVideoError("Video metadata is incomplete or invalid") from exc

        if width <= 0 or height <= 0 or fps <= 0 or duration <= 0 or nb_frames <= 0:
            raise InvalidVideoError("Video metadata contains non-positive values")
        return VideoMetadata(width, height, fps, nb_frames, duration)

    def _extract_frame_file(
        self, record: VideoRecord, frame_idx: int, destination: Path
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp.jpg")
        maximum = self.frame_cache_max_dimension
        metadata = record.metadata
        if max(metadata.width, metadata.height) <= maximum:
            scale_filter = "null"
        elif metadata.width >= metadata.height:
            scale_filter = f"scale={maximum}:-2"
        else:
            scale_filter = f"scale=-2:{maximum}"
        video_filter = f"select=eq(n\\,{frame_idx}),{scale_filter}"
        command = [
            self.ffmpeg_binary,
            "-v",
            "error",
            "-i",
            str(record.path),
            "-vf",
            video_filter,
            "-frames:v",
            "1",
            "-q:v",
            "2",
            "-y",
            str(temporary),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise VideoToolError(f"Required video tool not found: {self.ffmpeg_binary}") from exc
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.strip() or "unknown ffmpeg error"
            raise VideoToolError(f"Could not extract frame: {message}") from exc
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise VideoToolError("Could not extract frame: ffmpeg produced no image")
        temporary.replace(destination)

    def _extract_source_crop_file(
        self,
        record: VideoRecord,
        *,
        frame_idx: int,
        x: int,
        y: int,
        width: int,
        height: int,
        destination: Path,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp.png")
        crop_filter = (
            f"crop=w={width}:h={height}:x={x}:y={y}:exact=1,format=rgb24"
        )
        video_filter = f"select=eq(n\\,{frame_idx}),{crop_filter}"
        command = [
            self.ffmpeg_binary,
            "-v",
            "error",
            "-i",
            str(record.path),
            "-vf",
            video_filter,
            "-frames:v",
            "1",
            "-compression_level",
            "3",
            "-y",
            str(temporary),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise VideoToolError(
                f"Required video tool not found: {self.ffmpeg_binary}"
            ) from exc
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.strip() or "unknown ffmpeg error"
            raise VideoToolError(f"Could not extract source crop: {message}") from exc
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise VideoToolError(
                "Could not extract source crop: ffmpeg produced no image"
            )
        temporary.replace(destination)

    def _load_or_probe_frame_metadata(
        self, frame_path: Path, metadata_path: Path
    ) -> dict[str, int]:
        if metadata_path.is_file():
            try:
                cached = json.loads(metadata_path.read_text(encoding="utf-8"))
                return {"width": int(cached["width"]), "height": int(cached["height"])}
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                metadata_path.unlink(missing_ok=True)

        try:
            payload = self._run_ffprobe(frame_path, "stream=width,height")
        except InvalidVideoError as exc:
            raise VideoToolError("Could not read extracted frame dimensions") from exc
        try:
            stream = payload["streams"][0]
            dimensions = {"width": int(stream["width"]), "height": int(stream["height"])}
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise VideoToolError("Could not read extracted frame dimensions") from exc
        temporary = metadata_path.with_suffix(".tmp.json")
        temporary.write_text(json.dumps(dimensions), encoding="utf-8")
        temporary.replace(metadata_path)
        return dimensions

    @staticmethod
    def _validate_frame_index(metadata: VideoMetadata, frame_idx: int) -> None:
        if frame_idx < 0 or frame_idx >= metadata.nb_frames:
            raise InvalidFrameError(
                f"Frame index must be between 0 and {metadata.nb_frames - 1}"
            )

    def _run_ffprobe(self, path: Path, entries: str) -> dict[str, object]:
        command = [
            self.ffprobe_binary,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            entries,
            "-of",
            "json",
            str(path),
        ]
        try:
            result = subprocess.run(
                command, check=True, capture_output=True, text=True
            )
        except FileNotFoundError as exc:
            raise VideoToolError(f"Required video tool not found: {self.ffprobe_binary}") from exc
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.strip() or "unknown ffprobe error"
            raise InvalidVideoError(f"Could not probe video: {message}") from exc
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise InvalidVideoError("ffprobe returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise InvalidVideoError("ffprobe returned an invalid response")
        return payload


def _parse_rate(value: object) -> float:
    rate = float(Fraction(str(value)))
    if rate <= 0:
        raise ValueError("frame rate must be positive")
    return rate


def _first_positive_rate(*values: object) -> float:
    for value in values:
        try:
            return _parse_rate(value)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    raise ValueError("no positive frame rate found")


def _parse_positive_float(value: object) -> float:
    parsed = float(str(value))
    if parsed <= 0:
        raise ValueError("value must be positive")
    return parsed


def _first_positive_float(*values: object) -> float:
    for value in values:
        try:
            return _parse_positive_float(value)
        except (TypeError, ValueError):
            continue
    raise ValueError("no positive value found")


def metadata_dict(record: VideoRecord) -> dict[str, int | float | str]:
    metadata = asdict(record.metadata)
    return {
        "videoId": record.video_id,
        "width": metadata["width"],
        "height": metadata["height"],
        "fps": metadata["fps"],
        "nbFrames": metadata["nb_frames"],
        "duration": metadata["duration"],
    }
