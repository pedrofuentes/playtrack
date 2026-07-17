from __future__ import annotations

import hashlib
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
    name: str | None = None


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
                "sourceKey": record.source_key,
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

    def consolidate_sources(self, upload_root: Path) -> None:
        videos = self.videos()
        if not videos:
            return

        keyed_entries: list[dict[str, Any]] = []
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for original in videos:
            entry = dict(original)
            source_kind = str(entry.get("sourceKind", "path"))
            raw_path = entry.get("path")
            source_key: str | None = None
            if isinstance(raw_path, str):
                path = Path(raw_path)
                if source_kind == "path":
                    source_key = f"path:{path.resolve()}"
                elif source_kind == "upload" and path.is_file():
                    source_key = f"sha256:{_sha256_file(path)}"
            if source_key is not None:
                entry["sourceKey"] = source_key
                video_id = entry.get("videoId")
                if isinstance(video_id, str) and video_id:
                    groups.setdefault((source_kind, source_key), []).append(entry)
            keyed_entries.append(entry)

        replacements: dict[str, str] = {}
        redundant_uploads: list[tuple[Path, Path]] = []
        redundant_ids: set[str] = set()
        for (source_kind, _source_key), entries in groups.items():
            if len(entries) < 2:
                continue
            survivor = min(
                entries,
                key=lambda item: (
                    str(item.get("openedAt") or ""),
                    str(item.get("videoId") or ""),
                ),
            )
            survivor_id = str(survivor["videoId"])
            survivor_path = Path(str(survivor.get("path", "")))
            for duplicate in entries:
                duplicate_id = str(duplicate["videoId"])
                if duplicate_id == survivor_id:
                    continue
                replacements[duplicate_id] = survivor_id
                redundant_ids.add(duplicate_id)
                if source_kind == "upload":
                    redundant_uploads.append(
                        (Path(str(duplicate.get("path", ""))), survivor_path)
                    )

        consolidated_videos = [
            entry
            for entry in keyed_entries
            if str(entry.get("videoId", "")) not in redundant_ids
        ]
        if replacements:
            self._rewrite_track_video_ids(replacements)
            exports = self._read_list_strict(self.exports_path, missing_as_empty=True)
            for entry in exports:
                video_id = str(entry.get("videoId", ""))
                if video_id in replacements:
                    entry["videoId"] = replacements[video_id]
            self._write_list(self.exports_path, exports)

        if consolidated_videos != videos:
            self._write_list(self.videos_path, consolidated_videos)

        for redundant_path, survivor_path in redundant_uploads:
            if (
                _is_under(redundant_path, upload_root)
                and redundant_path.resolve() != survivor_path.resolve()
            ):
                redundant_path.unlink(missing_ok=True)

    def remove_video(self, video_id: str) -> None:
        self._write_list(self.videos_path, [v for v in self.videos() if v.get("videoId") != video_id])

    def rename_video(self, video_id: str, raw_name: str) -> str | None:
        name = _clean_name(raw_name, label="Source name")
        if name is None:
            raise ValueError("Source name cannot be blank")
        entries = self.videos()
        entry = next(
            (item for item in entries if item.get("videoId") == video_id), None
        )
        if entry is None:
            return None
        entry["name"] = name
        self._write_list(self.videos_path, entries)
        return name

    def save_track(
        self,
        video_id: str,
        job_id: str,
        anchor_frame_idx: int,
        box: tuple[int, int, int, int],
        track: Sequence["TrackFrame"],
        *,
        name: str | None = None,
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
                "name": name,
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
                        name=_clean_name(raw.get("name"), label="Player name"),
                    )
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("Ignoring corrupt library track %s: %s", path, exc)
        return saved

    def resolve_player_name(self, video_id: str, requested: str | None) -> str:
        cleaned = _clean_name(requested, label="Player name")
        if cleaned is not None:
            return cleaned
        used = {
            track.name.casefold()
            for track in self.iter_tracks()
            if track.video_id == video_id and track.name is not None
        }
        index = 1
        while f"player {index}" in used:
            index += 1
        return f"Player {index}"

    def rename_track(self, job_id: str, raw_name: str) -> SavedTrack | None:
        name = _clean_name(raw_name, label="Player name")
        if name is None:
            raise ValueError("Player name cannot be blank")
        path = self.tracks_dir / f"{job_id}.json"
        if not path.is_file():
            return None
        raw = self._read_object(path)
        raw["name"] = name
        self._write_object(path, raw)
        return next(
            (track for track in self.iter_tracks() if track.job_id == job_id), None
        )

    def backfill_track_names(self) -> None:
        tracks = self.iter_tracks()
        by_video: dict[str, list[SavedTrack]] = {}
        for track in tracks:
            by_video.setdefault(track.video_id, []).append(track)
        for video_tracks in by_video.values():
            ordered = sorted(video_tracks, key=lambda item: (item.created_at, item.job_id))
            used = {
                track.name.casefold()
                for track in ordered
                if track.name is not None
            }
            next_index = 1
            for track in ordered:
                if track.name is not None:
                    continue
                while f"player {next_index}" in used:
                    next_index += 1
                name = f"Player {next_index}"
                path = self.tracks_dir / f"{track.job_id}.json"
                raw = self._read_object(path)
                raw["name"] = name
                self._write_object(path, raw)
                used.add(name.casefold())
                next_index += 1

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

    def _read_list_strict(
        self, path: Path, *, missing_as_empty: bool = False
    ) -> list[dict[str, Any]]:
        try:
            value = self._read_object(path)
        except FileNotFoundError:
            if missing_as_empty:
                return []
            raise
        if not isinstance(value, list) or any(
            not isinstance(entry, dict) for entry in value
        ):
            raise ValueError(f"Malformed library catalog: {path}")
        return value

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

    def _rewrite_track_video_ids(self, replacements: dict[str, str]) -> None:
        if not self.tracks_dir.is_dir():
            return
        for path in sorted(self.tracks_dir.glob("*.json")):
            value = self._read_object(path)
            if not isinstance(value, dict) or not isinstance(
                value.get("videoId"), str
            ):
                raise ValueError(f"Malformed library track: {path}")
            video_id = value["videoId"]
            if video_id in replacements:
                value["videoId"] = replacements[video_id]
                self._write_object(path, value)


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


def _clean_name(
    value: Any, *, label: str, validate_length: bool = True
) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if validate_length and len(cleaned) > 80:
        raise ValueError(f"{label} must be 80 characters or fewer")
    return cleaned or None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _now() -> str:
    return datetime.now(UTC).isoformat()
