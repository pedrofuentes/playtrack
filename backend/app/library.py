from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Sequence, TypeVar

if TYPE_CHECKING:
    from .tracking import TrackFrame

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class SavedTrack:
    job_id: str
    video_id: str
    anchor_frame_idx: int
    start_frame_idx: int
    end_frame_exclusive: int
    box: tuple[int, int, int, int]
    track: tuple["TrackFrame", ...]
    created_at: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class SavedTrackSummary:
    job_id: str
    video_id: str
    anchor_frame_idx: int
    start_frame_idx: int
    end_frame_exclusive: int
    box: tuple[int, int, int, int]
    frame_count: int
    lost_count: int
    created_at: str
    name: str | None = None


@dataclass(frozen=True, slots=True)
class PendingDeletion:
    deletion_id: int
    kind: str
    target_id: str
    path: Path | None
    created_at: str
    attempts: int
    last_error: str | None


class LibraryStore:
    """Transactional SQLite catalog for videos, jobs, tracks, and exports."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.root = self.data_dir / "library"
        self.database_path = self.root / "findme.sqlite3"
        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def _initialize_database(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.database_path, timeout=5.0) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.execute("PRAGMA foreign_keys = ON")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version not in (0, _SCHEMA_VERSION):
                raise RuntimeError(
                    f"Unsupported library database version {version}; expected {_SCHEMA_VERSION}"
                )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS videos (
                    video_id TEXT PRIMARY KEY,
                    source_kind TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    path TEXT NOT NULL,
                    name TEXT,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    fps REAL NOT NULL,
                    nb_frames INTEGER NOT NULL,
                    duration REAL NOT NULL,
                    opened_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS videos_source_idx
                    ON videos(source_kind, source_key);

                CREATE TABLE IF NOT EXISTS tracks (
                    job_id TEXT PRIMARY KEY,
                    video_id TEXT NOT NULL,
                    anchor_frame_idx INTEGER NOT NULL,
                    start_frame_idx INTEGER NOT NULL,
                    end_frame_exclusive INTEGER NOT NULL,
                    box_json TEXT NOT NULL,
                    track_json TEXT NOT NULL,
                    frame_count INTEGER NOT NULL,
                    lost_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    name TEXT
                );
                CREATE INDEX IF NOT EXISTS tracks_video_idx
                    ON tracks(video_id, created_at, job_id);

                CREATE TABLE IF NOT EXISTS exports (
                    export_id TEXT PRIMARY KEY,
                    video_id TEXT NOT NULL,
                    track_job_id TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    path TEXT NOT NULL,
                    size INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS exports_video_idx
                    ON exports(video_id, created_at, export_id);
                CREATE INDEX IF NOT EXISTS exports_track_idx
                    ON exports(track_job_id, created_at, export_id);

                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    state TEXT NOT NULL,
                    progress REAL NOT NULL,
                    message TEXT NOT NULL,
                    track_json TEXT NOT NULL DEFAULT '[]',
                    resources_json TEXT NOT NULL DEFAULT '[]',
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    terminal_at TEXT
                );
                CREATE INDEX IF NOT EXISTS jobs_state_idx
                    ON jobs(kind, state, created_at);

                CREATE TABLE IF NOT EXISTS pending_deletions (
                    deletion_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    path TEXT,
                    created_at TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT
                );
                CREATE INDEX IF NOT EXISTS pending_deletions_target_idx
                    ON pending_deletions(kind, target_id);
                """
            )
            connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

    def _write(self, operation: Callable[[sqlite3.Connection], _T]) -> _T:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            result = operation(connection)
            connection.commit()
            return result
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def videos(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM videos ORDER BY opened_at, video_id"
            ).fetchall()
        return [_video_dict(row) for row in rows]

    def get_video(self, video_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM videos WHERE video_id = ?", (video_id,)
            ).fetchone()
        return _video_dict(row) if row is not None else None

    def save_video(self, record: Any, *, source_kind: str) -> None:
        opened_at = _now()

        def save(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO videos (
                    video_id, source_kind, source_key, path, name, width, height,
                    fps, nb_frames, duration, opened_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(video_id) DO UPDATE SET
                    source_kind = excluded.source_kind,
                    source_key = excluded.source_key,
                    path = excluded.path,
                    name = excluded.name,
                    width = excluded.width,
                    height = excluded.height,
                    fps = excluded.fps,
                    nb_frames = excluded.nb_frames,
                    duration = excluded.duration,
                    opened_at = excluded.opened_at
                """,
                (
                    record.video_id,
                    source_kind,
                    record.source_key,
                    str(record.path),
                    record.name,
                    record.metadata.width,
                    record.metadata.height,
                    record.metadata.fps,
                    record.metadata.nb_frames,
                    record.metadata.duration,
                    opened_at,
                ),
            )

        self._write(save)

    def consolidate_sources(self, upload_root: Path) -> None:
        videos = self.videos()
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
                if source_kind == "upload":
                    redundant_uploads.append(
                        (Path(str(duplicate.get("path", ""))), survivor_path)
                    )

        def consolidate(connection: sqlite3.Connection) -> None:
            for entry in keyed_entries:
                connection.execute(
                    "UPDATE videos SET source_key = ? WHERE video_id = ?",
                    (str(entry.get("sourceKey", "")), str(entry["videoId"])),
                )
            for duplicate_id, survivor_id in replacements.items():
                connection.execute(
                    "UPDATE tracks SET video_id = ? WHERE video_id = ?",
                    (survivor_id, duplicate_id),
                )
                connection.execute(
                    "UPDATE exports SET video_id = ? WHERE video_id = ?",
                    (survivor_id, duplicate_id),
                )
                connection.execute(
                    "DELETE FROM videos WHERE video_id = ?", (duplicate_id,)
                )

        self._write(consolidate)
        for redundant_path, survivor_path in redundant_uploads:
            if (
                _is_under(redundant_path, upload_root)
                and redundant_path.resolve() != survivor_path.resolve()
            ):
                redundant_path.unlink(missing_ok=True)

    def remove_video(
        self,
        video_id: str,
        *,
        pending_paths: Sequence[tuple[str, str, Path]] = (),
    ) -> None:
        def remove(connection: sqlite3.Connection) -> None:
            connection.execute("DELETE FROM videos WHERE video_id = ?", (video_id,))
            for kind, target_id, path in pending_paths:
                connection.execute(
                    """
                    INSERT INTO pending_deletions (
                        kind, target_id, path, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (kind, target_id, str(path), _now()),
                )

        self._write(remove)

    def remove_video_with_dependents(
        self,
        video_id: str,
        *,
        pending_paths: Sequence[tuple[str, str, Path]] = (),
        export_deletion_path: Callable[[dict[str, Any]], Path | None] | None = None,
    ) -> tuple[bool, list[str], list[dict[str, Any]]]:
        def remove(
            connection: sqlite3.Connection,
        ) -> tuple[bool, list[str], list[dict[str, Any]]]:
            exists = connection.execute(
                "SELECT 1 FROM videos WHERE video_id = ?", (video_id,)
            ).fetchone()
            if exists is None:
                return False, [], []
            track_ids = [
                str(row["job_id"])
                for row in connection.execute(
                    "SELECT job_id FROM tracks WHERE video_id = ?", (video_id,)
                ).fetchall()
            ]
            export_rows = connection.execute(
                "SELECT * FROM exports WHERE video_id = ?", (video_id,)
            ).fetchall()
            exported = [_export_dict(row, tolerate_corrupt=True) for row in export_rows]
            job_ids = track_ids + [str(entry["exportId"]) for entry in exported]
            connection.execute("DELETE FROM exports WHERE video_id = ?", (video_id,))
            connection.execute("DELETE FROM tracks WHERE video_id = ?", (video_id,))
            connection.execute("DELETE FROM videos WHERE video_id = ?", (video_id,))
            connection.executemany(
                "DELETE FROM jobs WHERE job_id = ?",
                ((job_id,) for job_id in job_ids),
            )
            for kind, target_id, path in pending_paths:
                self._insert_pending_deletion(
                    connection, kind=kind, target_id=target_id, path=path
                )
            if export_deletion_path is not None:
                for entry in exported:
                    path = export_deletion_path(entry)
                    if path is not None:
                        self._insert_pending_deletion(
                            connection,
                            kind="export",
                            target_id=str(entry["exportId"]),
                            path=path,
                        )
            return True, track_ids, exported

        return self._write(remove)

    def rename_video(self, video_id: str, raw_name: str) -> str | None:
        name = _clean_name(raw_name, label="Source name")
        if name is None:
            raise ValueError("Source name cannot be blank")

        def rename(connection: sqlite3.Connection) -> bool:
            cursor = connection.execute(
                "UPDATE videos SET name = ? WHERE video_id = ?", (name, video_id)
            )
            return cursor.rowcount > 0

        return name if self._write(rename) else None

    def save_track(
        self,
        video_id: str,
        job_id: str,
        anchor_frame_idx: int,
        box: tuple[int, int, int, int],
        track: Sequence["TrackFrame"],
        *,
        start_frame_idx: int | None = None,
        end_frame_exclusive: int | None = None,
        name: str | None = None,
    ) -> None:
        if start_frame_idx is None:
            start_frame_idx = min(
                (frame.frame_idx for frame in track), default=anchor_frame_idx
            )
        if end_frame_exclusive is None:
            end_frame_exclusive = max(
                (frame.frame_idx for frame in track), default=anchor_frame_idx
            ) + 1
        track_payload = [frame.to_dict() for frame in track]
        created_at = _now()

        def save(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO tracks (
                    job_id, video_id, anchor_frame_idx, start_frame_idx,
                    end_frame_exclusive, box_json, track_json, frame_count,
                    lost_count, created_at, name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    video_id = excluded.video_id,
                    anchor_frame_idx = excluded.anchor_frame_idx,
                    start_frame_idx = excluded.start_frame_idx,
                    end_frame_exclusive = excluded.end_frame_exclusive,
                    box_json = excluded.box_json,
                    track_json = excluded.track_json,
                    frame_count = excluded.frame_count,
                    lost_count = excluded.lost_count,
                    created_at = excluded.created_at,
                    name = excluded.name
                """,
                (
                    job_id,
                    video_id,
                    anchor_frame_idx,
                    start_frame_idx,
                    end_frame_exclusive,
                    _json(list(box)),
                    _json(track_payload),
                    len(track_payload),
                    sum(bool(frame.lost) for frame in track),
                    created_at,
                    name,
                ),
            )

        self._write(save)

    def iter_tracks(self) -> list[SavedTrack]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tracks ORDER BY created_at, job_id"
            ).fetchall()
        saved: list[SavedTrack] = []
        for row in rows:
            try:
                saved.append(_saved_track(row))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                logger.warning(
                    "Ignoring corrupt library track %s: %s", row["job_id"], exc
                )
        return saved

    def track_summaries(self) -> list[SavedTrackSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT job_id, video_id, anchor_frame_idx, start_frame_idx,
                       end_frame_exclusive, box_json, frame_count, lost_count,
                       created_at, name
                FROM tracks
                ORDER BY created_at, job_id
                """
            ).fetchall()
        summaries: list[SavedTrackSummary] = []
        for row in rows:
            try:
                summaries.append(_saved_track_summary(row))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                logger.warning(
                    "Ignoring corrupt library track summary %s: %s",
                    row["job_id"],
                    exc,
                )
        return summaries

    def get_track_summary(self, job_id: str) -> SavedTrackSummary | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT job_id, video_id, anchor_frame_idx, start_frame_idx,
                       end_frame_exclusive, box_json, frame_count, lost_count,
                       created_at, name
                FROM tracks
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            return _saved_track_summary(row)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning(
                "Ignoring corrupt library track summary %s: %s", job_id, exc
            )
            return None

    def get_track(self, job_id: str) -> SavedTrack | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM tracks WHERE job_id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        try:
            return _saved_track(row)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Ignoring corrupt library track %s: %s", job_id, exc)
            return None

    def resolve_player_name(self, video_id: str, requested: str | None) -> str:
        cleaned = _clean_name(requested, label="Player name")
        if cleaned is not None:
            return cleaned
        with self._connect() as connection:
            names = connection.execute(
                "SELECT name FROM tracks WHERE video_id = ? AND name IS NOT NULL",
                (video_id,),
            ).fetchall()
        used = {str(row["name"]).casefold() for row in names}
        index = 1
        while f"player {index}" in used:
            index += 1
        return f"Player {index}"

    def rename_track(self, job_id: str, raw_name: str) -> SavedTrack | None:
        name = _clean_name(raw_name, label="Player name")
        if name is None:
            raise ValueError("Player name cannot be blank")

        def rename(connection: sqlite3.Connection) -> sqlite3.Row | None:
            cursor = connection.execute(
                "UPDATE tracks SET name = ? WHERE job_id = ?", (name, job_id)
            )
            if cursor.rowcount == 0:
                return None
            return connection.execute(
                "SELECT * FROM tracks WHERE job_id = ?", (job_id,)
            ).fetchone()

        row = self._write(rename)
        return _saved_track(row) if row is not None else None

    def backfill_track_names(self) -> None:
        def backfill(connection: sqlite3.Connection) -> None:
            rows = connection.execute(
                "SELECT job_id, video_id, name FROM tracks ORDER BY video_id, created_at, job_id"
            ).fetchall()
            used_by_video: dict[str, set[str]] = {}
            next_by_video: dict[str, int] = {}
            for row in rows:
                name = row["name"]
                if name is not None:
                    used_by_video.setdefault(row["video_id"], set()).add(
                        str(name).casefold()
                    )
            for row in rows:
                if row["name"] is not None:
                    continue
                video_id = str(row["video_id"])
                used = used_by_video.setdefault(video_id, set())
                index = next_by_video.get(video_id, 1)
                while f"player {index}" in used:
                    index += 1
                name = f"Player {index}"
                connection.execute(
                    "UPDATE tracks SET name = ? WHERE job_id = ?",
                    (name, row["job_id"]),
                )
                used.add(name.casefold())
                next_by_video[video_id] = index + 1

        self._write(backfill)

    def remove_track(self, job_id: str) -> SavedTrack | None:
        def remove(connection: sqlite3.Connection) -> sqlite3.Row | None:
            row = connection.execute(
                "SELECT * FROM tracks WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is not None:
                connection.execute("DELETE FROM tracks WHERE job_id = ?", (job_id,))
            return row

        row = self._write(remove)
        if row is None:
            return None
        try:
            return _saved_track(row)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def remove_track_with_exports(
        self,
        job_id: str,
        *,
        export_deletion_path: Callable[[dict[str, Any]], Path | None] | None = None,
    ) -> tuple[SavedTrack | None, list[dict[str, Any]]]:
        def remove(
            connection: sqlite3.Connection,
        ) -> tuple[sqlite3.Row | None, list[dict[str, Any]]]:
            track_row = connection.execute(
                "SELECT * FROM tracks WHERE job_id = ?", (job_id,)
            ).fetchone()
            if track_row is None:
                return None, []
            export_rows = connection.execute(
                "SELECT * FROM exports WHERE track_job_id = ?", (job_id,)
            ).fetchall()
            exported = [_export_dict(row, tolerate_corrupt=True) for row in export_rows]
            connection.execute(
                "DELETE FROM exports WHERE track_job_id = ?", (job_id,)
            )
            connection.execute("DELETE FROM tracks WHERE job_id = ?", (job_id,))
            job_identifiers = [
                job_id,
                *(str(entry["exportId"]) for entry in exported),
            ]
            connection.executemany(
                "DELETE FROM jobs WHERE job_id = ?",
                ((identifier,) for identifier in job_identifiers),
            )
            if export_deletion_path is not None:
                for entry in exported:
                    path = export_deletion_path(entry)
                    if path is not None:
                        self._insert_pending_deletion(
                            connection,
                            kind="export",
                            target_id=str(entry["exportId"]),
                            path=path,
                        )
            return track_row, exported

        row, exported = self._write(remove)
        if row is None:
            return None, exported
        try:
            return _saved_track(row), exported
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None, exported

    def save_export(
        self,
        export_id: str,
        video_id: str,
        track_job_id: str,
        params: dict[str, Any],
        path: Path,
    ) -> None:
        created_at = _now()
        size = path.stat().st_size if path.is_file() else 0

        def save(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO exports (
                    export_id, video_id, track_job_id, params_json, path, size, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(export_id) DO UPDATE SET
                    video_id = excluded.video_id,
                    track_job_id = excluded.track_job_id,
                    params_json = excluded.params_json,
                    path = excluded.path,
                    size = excluded.size,
                    created_at = excluded.created_at
                """,
                (
                    export_id,
                    video_id,
                    track_job_id,
                    _json(params),
                    str(path),
                    size,
                    created_at,
                ),
            )

        self._write(save)

    def exports(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM exports ORDER BY created_at, export_id"
            ).fetchall()
        entries: list[dict[str, Any]] = []
        for row in rows:
            try:
                params = json.loads(row["params_json"])
                if not isinstance(params, dict):
                    raise ValueError("export params must be an object")
                entries.append(
                    {
                        "exportId": row["export_id"],
                        "videoId": row["video_id"],
                        "trackJobId": row["track_job_id"],
                        "params": params,
                        "path": row["path"],
                        "size": row["size"],
                        "createdAt": row["created_at"],
                    }
                )
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                logger.warning(
                    "Ignoring corrupt library export %s: %s", row["export_id"], exc
                )
        return entries

    def get_export(self, export_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM exports WHERE export_id = ?", (export_id,)
            ).fetchone()
        if row is None:
            return None
        try:
            params = json.loads(row["params_json"])
            if not isinstance(params, dict):
                raise ValueError("export params must be an object")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Ignoring corrupt library export %s: %s", export_id, exc)
            return None
        return {
            "exportId": row["export_id"],
            "videoId": row["video_id"],
            "trackJobId": row["track_job_id"],
            "params": params,
            "path": row["path"],
            "size": row["size"],
            "createdAt": row["created_at"],
        }

    def remove_export(
        self,
        export_id: str,
        *,
        deletion_path: Callable[[dict[str, Any]], Path | None] | None = None,
    ) -> dict[str, Any] | None:
        def remove(connection: sqlite3.Connection) -> dict[str, Any] | None:
            row = connection.execute(
                "SELECT * FROM exports WHERE export_id = ?", (export_id,)
            ).fetchone()
            if row is None:
                return None
            entry = _export_dict(row, tolerate_corrupt=True)
            connection.execute(
                "DELETE FROM exports WHERE export_id = ?", (export_id,)
            )
            connection.execute("DELETE FROM jobs WHERE job_id = ?", (export_id,))
            if deletion_path is not None:
                path = deletion_path(entry)
                if path is not None:
                    self._insert_pending_deletion(
                        connection,
                        kind="export",
                        target_id=export_id,
                        path=path,
                    )
            return entry

        return self._write(remove)

    def pending_deletions(
        self, *, kind: str | None = None, target_id: str | None = None
    ) -> list[PendingDeletion]:
        clauses: list[str] = []
        parameters: list[str] = []
        if kind is not None:
            clauses.append("kind = ?")
            parameters.append(kind)
        if target_id is not None:
            clauses.append("target_id = ?")
            parameters.append(target_id)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM pending_deletions{where} ORDER BY deletion_id",
                parameters,
            ).fetchall()
        return [
            PendingDeletion(
                deletion_id=int(row["deletion_id"]),
                kind=str(row["kind"]),
                target_id=str(row["target_id"]),
                path=Path(str(row["path"])) if row["path"] is not None else None,
                created_at=str(row["created_at"]),
                attempts=int(row["attempts"]),
                last_error=(
                    str(row["last_error"])
                    if row["last_error"] is not None
                    else None
                ),
            )
            for row in rows
        ]

    def complete_pending_deletion(self, deletion_id: int) -> None:
        self._write(
            lambda connection: connection.execute(
                "DELETE FROM pending_deletions WHERE deletion_id = ?",
                (deletion_id,),
            )
        )

    @staticmethod
    def _insert_pending_deletion(
        connection: sqlite3.Connection,
        *,
        kind: str,
        target_id: str,
        path: Path,
    ) -> None:
        connection.execute(
            """
            INSERT INTO pending_deletions (kind, target_id, path, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (kind, target_id, str(path), _now()),
        )

    def fail_pending_deletion(self, deletion_id: int, error: str) -> None:
        self._write(
            lambda connection: connection.execute(
                """
                UPDATE pending_deletions
                SET attempts = attempts + 1, last_error = ?
                WHERE deletion_id = ?
                """,
                (error, deletion_id),
            )
        )

    def save_job(
        self,
        *,
        job_id: str,
        kind: str,
        state: str,
        progress: float,
        message: str,
        track: Sequence["TrackFrame"],
        resources: Sequence[str],
        version: int,
        created_at: str,
        updated_at: str,
        terminal_at: str | None,
    ) -> None:
        track_json = _json([frame.to_dict() for frame in track])
        resources_json = _json(sorted(set(resources)))

        def save(connection: sqlite3.Connection) -> None:
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, kind, state, progress, message, track_json,
                    resources_json, version, created_at, updated_at, terminal_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    kind = excluded.kind,
                    state = excluded.state,
                    progress = excluded.progress,
                    message = excluded.message,
                    track_json = excluded.track_json,
                    resources_json = excluded.resources_json,
                    version = excluded.version,
                    updated_at = excluded.updated_at,
                    terminal_at = excluded.terminal_at
                """,
                (
                    job_id,
                    kind,
                    state,
                    progress,
                    message,
                    track_json,
                    resources_json,
                    version,
                    created_at,
                    updated_at,
                    terminal_at,
                ),
            )

        self._write(save)

    def load_jobs(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at, job_id"
            ).fetchall()
        jobs: list[dict[str, Any]] = []
        for row in rows:
            try:
                raw_track = json.loads(row["track_json"])
                raw_resources = json.loads(row["resources_json"])
                if not isinstance(raw_track, list) or not isinstance(
                    raw_resources, list
                ):
                    raise TypeError("job payloads must be JSON arrays")
                jobs.append(
                    {
                        "jobId": str(row["job_id"]),
                        "kind": str(row["kind"]),
                        "state": str(row["state"]),
                        "progress": float(row["progress"]),
                        "message": str(row["message"]),
                        "track": tuple(_track_frame(item) for item in raw_track),
                        "resources": frozenset(str(item) for item in raw_resources),
                        "version": int(row["version"]),
                        "createdAt": str(row["created_at"]),
                        "updatedAt": str(row["updated_at"]),
                        "terminalAt": (
                            str(row["terminal_at"])
                            if row["terminal_at"] is not None
                            else None
                        ),
                    }
                )
            except (TypeError, ValueError, json.JSONDecodeError, KeyError) as exc:
                logger.warning("Ignoring corrupt job %s: %s", row["job_id"], exc)
        return jobs

    def remove_job(self, job_id: str) -> None:
        self._write(
            lambda connection: connection.execute(
                "DELETE FROM jobs WHERE job_id = ?", (job_id,)
            )
        )

    def prune_terminal_jobs(self, retention: int) -> list[str]:
        def prune(connection: sqlite3.Connection) -> list[str]:
            rows = connection.execute(
                """
                SELECT job_id FROM jobs
                WHERE state IN ('completed', 'failed', 'canceled')
                ORDER BY terminal_at DESC, updated_at DESC, job_id DESC
                LIMIT -1 OFFSET ?
                """,
                (retention,),
            ).fetchall()
            identifiers = [str(row["job_id"]) for row in rows]
            connection.executemany(
                "DELETE FROM jobs WHERE job_id = ?",
                ((identifier,) for identifier in identifiers),
            )
            return identifiers

        return self._write(prune)

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


def _video_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "videoId": row["video_id"],
        "sourceKind": row["source_kind"],
        "sourceKey": row["source_key"],
        "path": row["path"],
        "name": row["name"],
        "metadata": {
            "width": row["width"],
            "height": row["height"],
            "fps": row["fps"],
            "nbFrames": row["nb_frames"],
            "duration": row["duration"],
        },
        "openedAt": row["opened_at"],
    }


def _export_dict(
    row: sqlite3.Row, *, tolerate_corrupt: bool = False
) -> dict[str, Any]:
    try:
        params = json.loads(row["params_json"])
        if not isinstance(params, dict):
            raise ValueError("export params must be an object")
    except (TypeError, ValueError, json.JSONDecodeError):
        if not tolerate_corrupt:
            raise
        params = {}
    return {
        "exportId": row["export_id"],
        "videoId": row["video_id"],
        "trackJobId": row["track_job_id"],
        "params": params,
        "path": row["path"],
        "size": row["size"],
        "createdAt": row["created_at"],
    }


def _saved_track(row: sqlite3.Row) -> SavedTrack:
    raw_track = json.loads(row["track_json"])
    raw_box = json.loads(row["box_json"])
    if not isinstance(raw_track, list) or not isinstance(raw_box, list):
        raise TypeError("track payload must contain JSON arrays")
    frames = tuple(_track_frame(item) for item in raw_track)
    box = tuple(int(value) for value in raw_box)
    if len(box) != 4:
        raise ValueError("track box must contain four coordinates")
    return SavedTrack(
        job_id=str(row["job_id"]),
        video_id=str(row["video_id"]),
        anchor_frame_idx=int(row["anchor_frame_idx"]),
        start_frame_idx=int(row["start_frame_idx"]),
        end_frame_exclusive=int(row["end_frame_exclusive"]),
        box=box,  # type: ignore[arg-type]
        track=frames,
        created_at=str(row["created_at"]),
        name=_clean_name(row["name"], label="Player name", validate_length=False),
    )


def _saved_track_summary(row: sqlite3.Row) -> SavedTrackSummary:
    raw_box = json.loads(row["box_json"])
    if not isinstance(raw_box, list):
        raise TypeError("track box must be a JSON array")
    box = tuple(int(value) for value in raw_box)
    if len(box) != 4:
        raise ValueError("track box must contain four coordinates")
    frame_count = int(row["frame_count"])
    lost_count = int(row["lost_count"])
    if frame_count < 0 or lost_count < 0 or lost_count > frame_count:
        raise ValueError("track counts are invalid")
    return SavedTrackSummary(
        job_id=str(row["job_id"]),
        video_id=str(row["video_id"]),
        anchor_frame_idx=int(row["anchor_frame_idx"]),
        start_frame_idx=int(row["start_frame_idx"]),
        end_frame_exclusive=int(row["end_frame_exclusive"]),
        box=box,  # type: ignore[arg-type]
        frame_count=frame_count,
        lost_count=lost_count,
        created_at=str(row["created_at"]),
        name=_clean_name(row["name"], label="Player name", validate_length=False),
    )


def _track_frame(value: Any) -> "TrackFrame":
    from .tracking import TrackFrame

    if not isinstance(value, dict):
        raise TypeError("track frame must be a JSON object")
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


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), allow_nan=False)


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
