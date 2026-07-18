from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app import library as library_module
from app.library import LibraryStore
from app.tracking import TrackFrame


def _track() -> list[TrackFrame]:
    return [
        TrackFrame(10, (1, 2, 11, 22), (6.0, 12.0), False),
        TrackFrame(11, None, None, True),
    ]


def test_sqlite_schema_uses_wal_full_sync_and_required_tables(tmp_path: Path) -> None:
    library = LibraryStore(tmp_path / "data")

    with sqlite3.connect(library.database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
        synchronous = connection.execute("PRAGMA synchronous").fetchone()[0]

    assert {"videos", "tracks", "exports", "jobs", "pending_deletions"} <= tables
    assert journal_mode == "wal"
    assert synchronous == 2
    assert library.database_path.name == "playtrack.sqlite3"


def _legacy_database(data_dir: Path, value: str = "legacy") -> Path:
    root = data_dir / "library"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "findme.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE migration_probe (value TEXT NOT NULL)")
        connection.execute("INSERT INTO migration_probe VALUES (?)", (value,))
    return path


def test_legacy_database_is_backed_up_into_canonical_path(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    legacy = _legacy_database(data_dir)
    legacy_bytes = legacy.read_bytes()
    legacy_mtime = legacy.stat().st_mtime_ns

    library = LibraryStore(data_dir)

    with sqlite3.connect(library.database_path) as connection:
        value = connection.execute("SELECT value FROM migration_probe").fetchone()[0]
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    assert value == "legacy"
    assert integrity == "ok"
    assert legacy.is_file()
    assert legacy.read_bytes() == legacy_bytes
    assert legacy.stat().st_mtime_ns == legacy_mtime


def test_legacy_migration_includes_committed_wal_records(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    root = data_dir / "library"
    root.mkdir(parents=True)
    legacy = root / "findme.sqlite3"
    writer = sqlite3.connect(legacy)
    try:
        writer.execute("PRAGMA journal_mode = WAL")
        writer.execute("PRAGMA wal_autocheckpoint = 0")
        writer.execute("CREATE TABLE migration_probe (value TEXT NOT NULL)")
        writer.commit()
        writer.execute("INSERT INTO migration_probe VALUES ('from-wal')")
        writer.commit()
        assert legacy.with_name(f"{legacy.name}-wal").is_file()

        library = LibraryStore(data_dir)
        assert legacy.with_name(f"{legacy.name}-wal").is_file()
    finally:
        writer.close()

    with sqlite3.connect(library.database_path) as connection:
        value = connection.execute("SELECT value FROM migration_probe").fetchone()[0]
    assert value == "from-wal"
    assert legacy.is_file()


def test_canonical_database_wins_after_legacy_migration(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    legacy = _legacy_database(data_dir, "first")
    canonical = LibraryStore(data_dir).database_path
    with sqlite3.connect(legacy) as connection:
        connection.execute("UPDATE migration_probe SET value = 'changed legacy'")

    restarted = LibraryStore(data_dir)

    assert restarted.database_path == canonical
    with sqlite3.connect(canonical) as connection:
        value = connection.execute("SELECT value FROM migration_probe").fetchone()[0]
    assert value == "first"


def test_failed_legacy_migration_cleans_partial_database(
    tmp_path: Path, monkeypatch: object
) -> None:
    data_dir = tmp_path / "data"
    _legacy_database(data_dir)
    partial = data_dir / "library" / "playtrack.sqlite3.migrating"
    partial.write_bytes(b"stale")

    def fail_backup(_source: sqlite3.Connection, _target: sqlite3.Connection) -> None:
        raise sqlite3.OperationalError("simulated backup failure")

    monkeypatch.setattr(library_module, "_backup_database", fail_backup)

    with pytest.raises(sqlite3.OperationalError, match="simulated backup failure"):
        LibraryStore(data_dir)

    assert not partial.exists()
    assert not (data_dir / "library" / "playtrack.sqlite3").exists()
    assert (data_dir / "library" / "findme.sqlite3").is_file()


def test_clean_break_ignores_legacy_json_catalogs(tmp_path: Path) -> None:
    root = tmp_path / "data" / "library"
    root.mkdir(parents=True)
    legacy = root / "videos.json"
    legacy.write_text(json.dumps([{"videoId": "legacy"}]), encoding="utf-8")

    library = LibraryStore(tmp_path / "data")

    assert library.videos() == []
    assert legacy.is_file()
    assert json.loads(legacy.read_text(encoding="utf-8"))[0]["videoId"] == "legacy"


def test_track_payload_and_summary_columns_round_trip(tmp_path: Path) -> None:
    library = LibraryStore(tmp_path / "data")
    track = _track()

    library.save_track(
        "video-1",
        "track-1",
        10,
        (1, 2, 11, 22),
        track,
        start_frame_idx=10,
        end_frame_exclusive=12,
        name="Skater",
    )

    with sqlite3.connect(library.database_path) as connection:
        row = connection.execute(
            "SELECT frame_count, lost_count, track_json FROM tracks WHERE job_id = ?",
            ("track-1",),
        ).fetchone()
    saved = library.iter_tracks()

    assert row is not None
    assert row[:2] == (2, 1)
    assert len(json.loads(row[2])) == 2
    assert len(saved) == 1
    assert saved[0].track == tuple(track)
    assert saved[0].start_frame_idx == 10
    assert saved[0].end_frame_exclusive == 12
    assert saved[0].name == "Skater"


def test_malformed_track_payload_is_isolated_to_its_row(tmp_path: Path) -> None:
    library = LibraryStore(tmp_path / "data")
    library.save_track("video-1", "good", 10, (1, 2, 11, 22), _track())
    library.save_track("video-1", "bad", 10, (1, 2, 11, 22), _track())
    with sqlite3.connect(library.database_path) as connection:
        connection.execute(
            "UPDATE tracks SET track_json = ? WHERE job_id = ?", ("{", "bad")
        )

    saved = library.iter_tracks()

    assert [track.job_id for track in saved] == ["good"]


def test_concurrent_export_writers_do_not_lose_rows(tmp_path: Path) -> None:
    library = LibraryStore(tmp_path / "data")
    paths = []
    for export_id in ("first", "second"):
        path = tmp_path / f"{export_id}.mp4"
        path.write_bytes(export_id.encode())
        paths.append(path)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                library.save_export,
                export_id,
                "video-1",
                "track-1",
                {"outWidth": 128},
                path,
            )
            for export_id, path in zip(("first", "second"), paths, strict=True)
        ]
        for future in futures:
            future.result(timeout=2)

    assert {entry["exportId"] for entry in library.exports()} == {"first", "second"}
