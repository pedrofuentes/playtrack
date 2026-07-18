from __future__ import annotations

from collections.abc import Iterator
import hashlib
import json
import logging
import math
import shutil
import subprocess
import threading
import uuid
from dataclasses import asdict, dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import Any, BinaryIO, Callable

from .library import LibraryStore, _clean_name

logger = logging.getLogger(__name__)


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
    source_kind: str = "path"
    display_name: str | None = None
    source_key: str = ""

    @property
    def name(self) -> str:
        return self.display_name or self.path.name


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


@dataclass(frozen=True, slots=True)
class TrackingFrameSequence:
    path: Path
    width: int
    height: int
    frame_count: int
    scale_x: float
    scale_y: float
    start_frame_idx: int = 0


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
        tracking_max_dimension: int = 2048,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.data_dir = data_dir.resolve()
        self.upload_dir = self.data_dir / "uploads"
        self.frame_cache_root = self.data_dir / "frames"
        self.selection_crop_root = self.data_dir / "selection-crops"
        self.tracking_frame_root = self.data_dir / "tracking-frames"
        self.ffmpeg_binary = ffmpeg_binary
        self.ffprobe_binary = ffprobe_binary
        self.frame_cache_max_dimension = frame_cache_max_dimension
        self.tracking_max_dimension = tracking_max_dimension
        self._records: dict[str, VideoRecord] = {}
        self._lock = threading.RLock()
        self.library = LibraryStore(self.data_dir)
        self._retry_pending_file_deletions()
        self.library.consolidate_sources(self.upload_dir)
        self._rehydrate()

    def register_path(
        self, raw_path: str | Path, display_name: str | None = None
    ) -> VideoRecord:
        name = _clean_name(display_name, label="Source name")
        requested_path = Path(raw_path).expanduser()
        path = requested_path if requested_path.is_absolute() else self.repo_root / requested_path
        path = path.resolve()
        if not path.is_file():
            raise VideoNotFoundError(f"Video file not found: {raw_path}")
        source_key = _path_source_key(path)
        existing = self._reuse_source(
            "path", source_key, display_name=name
        )
        if existing is not None:
            return existing
        return self._register(
            path,
            source_kind="path",
            display_name=name,
            source_key=source_key,
            reuse_display_name=name,
        )

    def register_upload(
        self,
        source: BinaryIO,
        filename: str | None = None,
        display_name: str | None = None,
    ) -> VideoRecord:
        name = _clean_name(display_name, label="Source name")
        suffix = Path(filename or "upload.mp4").suffix.lower() or ".mp4"
        upload_id = uuid.uuid4().hex
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.upload_dir / f".{upload_id}.tmp"
        destination = self.upload_dir / f"{upload_id}{suffix}"
        try:
            digest = hashlib.sha256()
            with temporary.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    output.write(chunk)
            source_key = _upload_source_key(digest.hexdigest())
            existing = self._reuse_source(
                "upload", source_key, display_name=name
            )
            if existing is not None:
                temporary.unlink()
                return existing
            temporary.replace(destination)
            record = self._register(
                destination,
                source_kind="upload",
                display_name=(
                    name
                    or sanitize_display_name(filename)
                ),
                source_key=source_key,
                reuse_display_name=name,
            )
            if record.path != destination:
                destination.unlink(missing_ok=True)
            return record
        except Exception:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise

    def get(self, video_id: str) -> VideoRecord:
        with self._lock:
            try:
                return self._records[video_id]
            except KeyError as exc:
                raise VideoNotFoundError("Video not found") from exc

    def rename(self, video_id: str, raw_name: str) -> VideoRecord:
        with self._lock:
            record = self.get(video_id)
            name = self.library.rename_video(video_id, raw_name)
            if name is None:
                raise VideoNotFoundError("Video not found")
            renamed = replace(record, display_name=name)
            self._records[video_id] = renamed
        return renamed

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

    def prepare_tracking_frames(
        self,
        video_id: str,
        *,
        start_frame_idx: int = 0,
        end_frame_exclusive: int | None = None,
        frame_limit: int | None = None,
    ) -> TrackingFrameSequence:
        """Extract a dedicated sequential JPEG cache for SAM 2 propagation."""
        record = self.get(video_id)
        if frame_limit is not None and frame_limit <= 0:
            raise InvalidFrameError("Tracking frame limit must be positive")
        source_frame_count = record.metadata.nb_frames
        requested_end = (
            source_frame_count
            if end_frame_exclusive is None
            else end_frame_exclusive
        )
        if not 0 <= start_frame_idx < requested_end <= source_frame_count:
            raise InvalidFrameError(
                "Tracking range must contain at least one source frame and stay inside the video"
            )
        effective_end = requested_end
        if frame_limit is not None:
            effective_end = min(effective_end, start_frame_idx + frame_limit)
        requested_count = effective_end - start_frame_idx
        cache_name = (
            f"max-{self.tracking_max_dimension}"
            f"-range-{start_frame_idx}-{effective_end}"
        )
        destination = self.tracking_frame_root / video_id / cache_name

        with self._lock:
            cached = self._load_tracking_sequence(record, destination)
            if (
                cached is not None
                and cached.frame_count == requested_count
                and cached.start_frame_idx == start_frame_idx
            ):
                return cached
            if destination.exists():
                shutil.rmtree(destination)
            self._extract_tracking_frame_sequence(
                record,
                destination,
                start_frame_idx=start_frame_idx,
                end_frame_exclusive=effective_end,
            )
            cached = self._load_tracking_sequence(record, destination)
            if cached is None:
                raise VideoToolError("Could not read tracking frame cache")
            return cached

    def records(self) -> tuple[VideoRecord, ...]:
        with self._lock:
            return tuple(self._records.values())

    def remove(self, video_id: str) -> VideoRecord:
        with self._lock:
            record = self.get(video_id)
            self.library.remove_video(
                video_id, pending_paths=self._managed_deletion_paths(record)
            )
            self._records.pop(video_id)
        self._retry_pending_file_deletions(video_id)
        return record

    def remove_with_dependents(
        self,
        video_id: str,
        *,
        export_deletion_path: Callable[[dict[str, Any]], Path | None],
    ) -> tuple[VideoRecord, list[str], list[dict[str, Any]]]:
        with self._lock:
            record = self.get(video_id)
            found, track_ids, exported = self.library.remove_video_with_dependents(
                video_id,
                pending_paths=self._managed_deletion_paths(record),
                export_deletion_path=export_deletion_path,
            )
            if not found:
                raise VideoNotFoundError("Video not found")
            self._records.pop(video_id)
        self._retry_pending_file_deletions(video_id)
        return record, track_ids, exported

    def remove_catalog_entry(self, video_id: str) -> bool:
        with self._lock:
            if not any(
                item.get("videoId") == video_id
                for item in self.library.videos()
            ):
                return False
            self.library.remove_video(video_id)
            return True

    def _register(
        self,
        path: Path,
        *,
        source_kind: str,
        display_name: str | None = None,
        source_key: str = "",
        reuse_display_name: str | None = None,
    ) -> VideoRecord:
        metadata = self._probe_video(path)
        with self._lock:
            existing = self._reuse_source_locked(
                source_kind,
                source_key,
                display_name=reuse_display_name,
            )
            if existing is not None:
                return existing
            video_id = uuid.uuid4().hex
            record = VideoRecord(
                video_id=video_id,
                path=path,
                metadata=metadata,
                frame_cache_dir=self.frame_cache_root / video_id,
                source_kind=source_kind,
                display_name=display_name,
                source_key=source_key,
            )
            self.library.save_video(record, source_kind=source_kind)
            self._records[video_id] = record
        return record

    def _reuse_source(
        self,
        source_kind: str,
        source_key: str,
        *,
        display_name: str | None,
    ) -> VideoRecord | None:
        with self._lock:
            return self._reuse_source_locked(
                source_kind,
                source_key,
                display_name=display_name,
            )

    def _reuse_source_locked(
        self,
        source_kind: str,
        source_key: str,
        *,
        display_name: str | None,
    ) -> VideoRecord | None:
        record = next(
            (
                candidate
                for candidate in self._records.values()
                if candidate.source_kind == source_kind
                and candidate.source_key == source_key
            ),
            None,
        )
        if record is None:
            saved = next(
                (
                    entry
                    for entry in self.library.videos()
                    if str(entry.get("sourceKind", "path")) == source_kind
                    and str(entry.get("sourceKey", "")) == source_key
                ),
                None,
            )
            if saved is not None:
                record = self._record_from_saved(saved)
        if record is None:
            return None
        if display_name is not None:
            renamed = self.library.rename_video(record.video_id, display_name)
            if renamed is None:
                raise VideoNotFoundError("Video not found")
            record = replace(record, display_name=renamed)
        self._records[record.video_id] = record
        return record

    def _rehydrate(self) -> None:
        for saved in self.library.videos():
            record = self._record_from_saved(saved)
            if record is not None:
                self._records[record.video_id] = record

    def _retry_pending_file_deletions(self, target_id: str | None = None) -> None:
        allowed_cache_roots = (
            self.frame_cache_root,
            self.tracking_frame_root,
            self.selection_crop_root,
        )
        for deletion in self.library.pending_deletions(target_id=target_id):
            path = deletion.path
            if deletion.kind not in {"upload", "cache"}:
                continue
            if path is None:
                self.library.fail_pending_deletion(
                    deletion.deletion_id, "Pending deletion has no path"
                )
                continue
            if deletion.kind == "upload":
                allowed = self._is_under(path, self.upload_dir)
            else:
                allowed = any(self._is_under(path, root) for root in allowed_cache_roots)
            if not allowed:
                self.library.fail_pending_deletion(
                    deletion.deletion_id,
                    "Pending deletion path is outside its managed runtime directory",
                )
                continue
            try:
                if deletion.kind == "cache":
                    if path.exists():
                        shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
            except OSError as exc:
                self.library.fail_pending_deletion(
                    deletion.deletion_id, str(exc) or type(exc).__name__
                )
                logger.warning(
                    "Could not finish pending %s deletion %s: %s",
                    deletion.kind,
                    path,
                    exc,
                )
            else:
                self.library.complete_pending_deletion(deletion.deletion_id)

    def _managed_deletion_paths(
        self, record: VideoRecord
    ) -> list[tuple[str, str, Path]]:
        video_id = record.video_id
        pending_paths = [
            ("cache", video_id, record.frame_cache_dir),
            ("cache", video_id, self.tracking_frame_root / video_id),
            ("cache", video_id, self.selection_crop_root / video_id),
        ]
        if record.source_kind == "upload" and self._is_under(
            record.path, self.upload_dir
        ):
            pending_paths.append(("upload", video_id, record.path))
        return pending_paths

    def _record_from_saved(self, saved: dict[str, object]) -> VideoRecord | None:
        try:
            path = Path(str(saved["path"])).resolve()
            metadata = saved["metadata"]
            if not path.is_file() or not isinstance(metadata, dict):
                return None
            video_id = str(saved["videoId"])
            return VideoRecord(
                video_id=video_id,
                path=path,
                metadata=VideoMetadata(
                    width=int(metadata["width"]),
                    height=int(metadata["height"]),
                    fps=float(metadata["fps"]),
                    nb_frames=int(metadata["nbFrames"]),
                    duration=float(metadata["duration"]),
                ),
                frame_cache_dir=self.frame_cache_root / video_id,
                source_kind=str(saved.get("sourceKind", "path")),
                display_name=_clean_name(
                    saved.get("name"),
                    label="Source name",
                    validate_length=False,
                ),
                source_key=str(saved.get("sourceKey", "")),
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _is_under(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except ValueError:
            return False

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
        self._validate_constant_frame_rate(path)
        return VideoMetadata(width, height, fps, nb_frames, duration)

    def _validate_constant_frame_rate(self, path: Path) -> None:
        intervals = _StreamingMedian()
        minimum = math.inf
        maximum = -math.inf
        previous: float | None = None
        timestamp_count = 0
        timestamps = self._frame_timestamps(path)
        try:
            for timestamp in timestamps:
                timestamp_count += 1
                if previous is not None:
                    interval = timestamp - previous
                    if not math.isfinite(interval) or interval <= 0:
                        raise InvalidVideoError(
                            "Video frame timestamps are missing or non-monotonic"
                        )
                    intervals.add(interval)
                    minimum = min(minimum, interval)
                    maximum = max(maximum, interval)
                previous = timestamp
        finally:
            close = getattr(timestamps, "close", None)
            if close is not None:
                close()
        if timestamp_count < 2:
            raise InvalidVideoError("Video has too few timestamped frames")
        median = intervals.value()
        tolerance = max(0.0001, median * 0.005)
        if minimum < median - tolerance or maximum > median + tolerance:
            raise InvalidVideoError(
                "Variable frame rate video is not supported; convert it to constant frame rate"
            )

    def _frame_timestamps(self, path: Path) -> Iterator[float]:
        command = [
            self.ffprobe_binary,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "frame=best_effort_timestamp_time",
            "-of",
            "csv=p=0",
            str(path),
        ]
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
            assert process.stdout is not None
            for line in process.stdout:
                raw = line.strip().split(",", 1)[0]
                if not raw or raw == "N/A":
                    raise InvalidVideoError(
                        "Video contains a frame without a timestamp"
                    )
                try:
                    timestamp = float(raw)
                except ValueError as exc:
                    raise InvalidVideoError(
                        "ffprobe returned an invalid frame timestamp"
                    ) from exc
                if not math.isfinite(timestamp):
                    raise InvalidVideoError(
                        "ffprobe returned an invalid frame timestamp"
                    )
                yield timestamp
            if process.wait() != 0:
                raise InvalidVideoError("Could not probe video frame timestamps")
        except FileNotFoundError as exc:
            raise VideoToolError(
                f"Required video tool not found: {self.ffprobe_binary}"
            ) from exc
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                if process.stdout is not None:
                    process.stdout.close()

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

    def _extract_tracking_frame_sequence(
        self,
        record: VideoRecord,
        destination: Path,
        *,
        start_frame_idx: int,
        end_frame_exclusive: int,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.parent / f".{destination.name}-{uuid.uuid4().hex}.tmp"
        temporary.mkdir(parents=True)
        metadata = record.metadata
        maximum = self.tracking_max_dimension
        if maximum <= 0:
            raise VideoToolError("Tracking maximum dimension must be positive")
        if max(metadata.width, metadata.height) <= maximum:
            scale_filter = "null"
        elif metadata.width >= metadata.height:
            scale_filter = f"scale={maximum}:-2"
        else:
            scale_filter = f"scale=-2:{maximum}"
        frame_count = end_frame_exclusive - start_frame_idx
        video_filter = (
            f"select=between(n\\,{start_frame_idx}\\,{end_frame_exclusive - 1}),"
            f"{scale_filter}"
        )
        command = [
            self.ffmpeg_binary,
            "-v",
            "error",
            "-i",
            str(record.path),
            "-vf",
            video_filter,
            "-frames:v",
            str(frame_count),
            "-fps_mode",
            "passthrough",
            "-q:v",
            "2",
            "-start_number",
            "0",
            "-y",
            str(temporary / "%08d.jpg"),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
            frames = sorted(temporary.glob("*.jpg"))
            if len(frames) != frame_count:
                raise VideoToolError(
                    f"Expected {frame_count} tracking frames, got {len(frames)}"
                )
            payload = self._run_ffprobe(frames[0], "stream=width,height")
            stream = payload["streams"][0]
            descriptor = {
                "width": int(stream["width"]),
                "height": int(stream["height"]),
                "frame_count": len(frames),
                "start_frame_idx": start_frame_idx,
            }
            (temporary / "sequence.json").write_text(
                json.dumps(descriptor), encoding="utf-8"
            )
            temporary.replace(destination)
        except FileNotFoundError as exc:
            raise VideoToolError(
                f"Required video tool not found: {self.ffmpeg_binary}"
            ) from exc
        except subprocess.CalledProcessError as exc:
            message = exc.stderr.strip() or "unknown ffmpeg error"
            raise VideoToolError(
                f"Could not extract tracking frames: {message}"
            ) from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise VideoToolError("Could not inspect tracking frame dimensions") from exc
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    @staticmethod
    def _load_tracking_sequence(
        record: VideoRecord, destination: Path
    ) -> TrackingFrameSequence | None:
        descriptor_path = destination / "sequence.json"
        if not descriptor_path.is_file():
            return None
        try:
            descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
            width = int(descriptor["width"])
            height = int(descriptor["height"])
            frame_count = int(descriptor["frame_count"])
            start_frame_idx = int(descriptor.get("start_frame_idx", 0))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None
        if width <= 0 or height <= 0 or frame_count <= 0:
            return None
        if len(list(destination.glob("*.jpg"))) != frame_count:
            return None
        return TrackingFrameSequence(
            path=destination,
            width=width,
            height=height,
            frame_count=frame_count,
            scale_x=width / record.metadata.width,
            scale_y=height / record.metadata.height,
            start_frame_idx=start_frame_idx,
        )

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


class _StreamingMedian:
    """P² median estimator with constant memory after five observations."""

    def __init__(self) -> None:
        self._initial: list[float] = []
        self._heights: list[float] | None = None
        self._positions = [1, 2, 3, 4, 5]
        self._desired = [1.0, 2.0, 3.0, 4.0, 5.0]
        self._increments = [0.0, 0.25, 0.5, 0.75, 1.0]

    def add(self, value: float) -> None:
        if self._heights is None:
            self._initial.append(value)
            if len(self._initial) == 5:
                self._initial.sort()
                self._heights = self._initial.copy()
            return

        heights = self._heights
        if value < heights[0]:
            heights[0] = value
            bucket = 0
        elif value < heights[1]:
            bucket = 0
        elif value < heights[2]:
            bucket = 1
        elif value < heights[3]:
            bucket = 2
        elif value <= heights[4]:
            bucket = 3
        else:
            heights[4] = value
            bucket = 3

        for index in range(bucket + 1, 5):
            self._positions[index] += 1
        for index, increment in enumerate(self._increments):
            self._desired[index] += increment
        for index in range(1, 4):
            difference = self._desired[index] - self._positions[index]
            can_move_up = difference >= 1 and (
                self._positions[index + 1] - self._positions[index] > 1
            )
            can_move_down = difference <= -1 and (
                self._positions[index - 1] - self._positions[index] < -1
            )
            if not (can_move_up or can_move_down):
                continue
            direction = 1 if difference > 0 else -1
            candidate = self._parabolic(index, direction)
            neighbor = heights[index + direction]
            if heights[index - 1] < candidate < heights[index + 1]:
                heights[index] = candidate
            else:
                distance = self._positions[index + direction] - self._positions[index]
                heights[index] += direction * (neighbor - heights[index]) / distance
            self._positions[index] += direction

    def _parabolic(self, index: int, direction: int) -> float:
        assert self._heights is not None
        heights = self._heights
        positions = self._positions
        left_distance = positions[index] - positions[index - 1]
        right_distance = positions[index + 1] - positions[index]
        span = positions[index + 1] - positions[index - 1]
        return heights[index] + direction / span * (
            (left_distance + direction)
            * (heights[index + 1] - heights[index])
            / right_distance
            + (right_distance - direction)
            * (heights[index] - heights[index - 1])
            / left_distance
        )

    def value(self) -> float:
        if self._heights is not None:
            return self._heights[2]
        if not self._initial:
            raise ValueError("median requires at least one observation")
        ordered = sorted(self._initial)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2


def _path_source_key(path: Path) -> str:
    return f"path:{path.resolve()}"


def _upload_source_key(digest: str) -> str:
    return f"sha256:{digest.lower()}"


def sanitize_display_name(value: object) -> str | None:
    """Keep only a client filename, never a client-supplied path."""
    if not isinstance(value, str):
        return None
    name = Path(value.replace("\\", "/")).name
    return name or None


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
        "name": record.name,
        "width": metadata["width"],
        "height": metadata["height"],
        "fps": metadata["fps"],
        "nbFrames": metadata["nb_frames"],
        "duration": metadata["duration"],
    }
