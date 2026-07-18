from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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
