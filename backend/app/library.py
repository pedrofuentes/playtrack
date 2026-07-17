from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    from .tracking import TrackFrame

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SavedTrack:
    job_id: str
    video_id: str
    anchor_frame_idx: int
    box: tuple[int, int, int, int]
    track: tuple["TrackFrame", ...]
    created_at: str


class LibraryStore:
    """Small, crash-tolerant JSON catalog for reusable videos, tracks, and exports."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.root = self.data_dir / "library"
        self.tracks_dir = self.root / "tracks"
        self.videos_path = self.root / "videos.json"
        self.exports_path = self.root / "exports.json"

    def videos(self) -> list[dict[str, Any]]:
        return self._read_list(self.videos_path)

    def save_video(self, record: Any, *, source_kind: str) -> None:
        entries = [entry for entry in self.videos() if entry.get("videoId") != record.video_id]
        entries.append(
            {
                "videoId": record.video_id,
                "sourceKind": source_kind,
                "path": str(record.path),
                "name": record.name,
                "metadata": {
                    "width": record.metadata.width,
                    "height": record.metadata.height,
                    "fps": record.metadata.fps,
                    "nbFrames": record.metadata.nb_frames,
                    "duration": record.metadata.duration,
                },
                "openedAt": _now(),
            }
        )
        self._write_list(self.videos_path, entries)

    def remove_video(self, video_id: str) -> None:
        self._write_list(self.videos_path, [v for v in self.videos() if v.get("videoId") != video_id])

    def save_track(
        self,
        video_id: str,
        job_id: str,
        anchor_frame_idx: int,
        box: tuple[int, int, int, int],
        track: Sequence["TrackFrame"],
    ) -> None:
        self._write_object(
            self.tracks_dir / f"{job_id}.json",
            {
                "jobId": job_id,
                "videoId": video_id,
                "anchorFrameIdx": anchor_frame_idx,
                "box": list(box),
                "track": [frame.to_dict() for frame in track],
                "createdAt": _now(),
            },
        )

    def iter_tracks(self) -> list[SavedTrack]:
        if not self.tracks_dir.is_dir():
            return []
        saved: list[SavedTrack] = []
        for path in sorted(self.tracks_dir.glob("*.json")):
            try:
                raw = self._read_object(path)
                frames = tuple(_track_frame(item) for item in raw["track"])
                saved.append(
                    SavedTrack(
                        job_id=str(raw["jobId"]),
                        video_id=str(raw["videoId"]),
                        anchor_frame_idx=int(raw["anchorFrameIdx"]),
                        box=tuple(int(value) for value in raw["box"]),  # type: ignore[arg-type]
                        track=frames,
                        created_at=str(raw["createdAt"]),
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("Ignoring corrupt library track %s: %s", path, exc)
        return saved

    def remove_track(self, job_id: str) -> SavedTrack | None:
        found = next((track for track in self.iter_tracks() if track.job_id == job_id), None)
        (self.tracks_dir / f"{job_id}.json").unlink(missing_ok=True)
        return found

    def save_export(
        self,
        export_id: str,
        video_id: str,
        track_job_id: str,
        params: dict[str, Any],
        path: Path,
    ) -> None:
        entries = [entry for entry in self.exports() if entry.get("exportId") != export_id]
        entries.append(
            {
                "exportId": export_id,
                "videoId": video_id,
                "trackJobId": track_job_id,
                "params": params,
                "path": str(path),
                "size": path.stat().st_size if path.is_file() else 0,
                "createdAt": _now(),
            }
        )
        self._write_list(self.exports_path, entries)

    def exports(self) -> list[dict[str, Any]]:
        return self._read_list(self.exports_path)

    def remove_exports(self, predicate: Any) -> list[dict[str, Any]]:
        removed = [entry for entry in self.exports() if predicate(entry)]
        self._write_list(self.exports_path, [entry for entry in self.exports() if not predicate(entry)])
        return removed

    def clear_caches(self) -> int:
        freed = 0
        for name in ("frames", "tracking-frames", "selection-crops"):
            path = self.data_dir / name
            if path.exists():
                freed += _directory_size(path)
                shutil.rmtree(path)
        return freed

    def cache_bytes(self) -> int:
        return sum(
            _directory_size(self.data_dir / name)
            for name in ("frames", "tracking-frames", "selection-crops")
            if (self.data_dir / name).exists()
        )

    def _read_list(self, path: Path) -> list[dict[str, Any]]:
        try:
            value = self._read_object(path)
            if not isinstance(value, list):
                raise ValueError("expected a JSON array")
            return [entry for entry in value if isinstance(entry, dict)]
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            if path.exists():
                logger.warning("Ignoring corrupt library catalog %s: %s", path, exc)
            return []

    @staticmethod
    def _read_object(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write_object(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, path)

    def _write_list(self, path: Path, entries: list[dict[str, Any]]) -> None:
        self._write_object(path, entries)


def _track_frame(value: Any) -> "TrackFrame":
    from .tracking import TrackFrame
    box = value.get("box")
    center = value.get("center")
    return TrackFrame(
        frame_idx=int(value["frameIdx"]),
        box=tuple(int(item) for item in box) if box is not None else None,
        center=tuple(float(item) for item in center) if center is not None else None,
        lost=bool(value["lost"]),
    )


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _now() -> str:
    return datetime.now(UTC).isoformat()
