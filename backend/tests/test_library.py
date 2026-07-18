from __future__ import annotations

import json
import sqlite3
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.jobs import JobRegistry
from app.library import LibraryStore
from app.main import create_app
from app.tracking import TrackFrame, persist_completed_track
from app.videos import VideoStore


def _track() -> list[TrackFrame]:
    return [
        TrackFrame(0, (10, 10, 30, 30), (20.0, 20.0), False),
        TrackFrame(1, None, None, True),
    ]


def _seed_video_rows(
    library: LibraryStore, entries: list[dict[str, object]]
) -> None:
    for entry in entries:
        metadata = entry["metadata"]
        assert isinstance(metadata, dict)
        record = SimpleNamespace(
            video_id=entry["videoId"],
            source_key=entry.get("sourceKey", ""),
            path=Path(str(entry["path"])),
            name=entry.get("name"),
            metadata=SimpleNamespace(
                width=metadata["width"],
                height=metadata["height"],
                fps=metadata["fps"],
                nb_frames=metadata["nbFrames"],
                duration=metadata["duration"],
            ),
        )
        library.save_video(record, source_kind=str(entry.get("sourceKind", "path")))
        with sqlite3.connect(library.database_path) as connection:
            connection.execute(
                "UPDATE videos SET opened_at = ? WHERE video_id = ?",
                (entry.get("openedAt", ""), entry["videoId"]),
            )


def _duplicate_upload_library(
    tmp_path: Path, tiny_video: Path
) -> tuple[LibraryStore, Path, Path]:
    data_dir = tmp_path / "data"
    library = LibraryStore(data_dir)
    upload_dir = data_dir / "uploads"
    upload_dir.mkdir(parents=True)
    first_upload = upload_dir / "first.mp4"
    duplicate_upload = upload_dir / "duplicate.mp4"
    first_upload.write_bytes(tiny_video.read_bytes())
    duplicate_upload.write_bytes(tiny_video.read_bytes())
    metadata = {
        "width": 320,
        "height": 180,
        "fps": 10.0,
        "nbFrames": 4,
        "duration": 0.4,
    }
    _seed_video_rows(
        library,
        [
            {
                "videoId": "upload-survivor",
                "sourceKind": "upload",
                "path": str(first_upload),
                "metadata": metadata,
                "openedAt": "2026-01-01T00:00:00+00:00",
            },
            {
                "videoId": "upload-duplicate",
                "sourceKind": "upload",
                "path": str(duplicate_upload),
                "metadata": metadata,
                "openedAt": "2026-01-02T00:00:00+00:00",
            },
        ],
    )
    return library, first_upload, duplicate_upload


def test_library_persists_videos_tracks_and_restores_completed_jobs(
    tmp_path: Path, tiny_video: Path
) -> None:
    data_dir = tmp_path / "data"
    store = VideoStore(repo_root=tmp_path, data_dir=data_dir)
    record = store.register_path(tiny_video)
    library = LibraryStore(data_dir)
    library.save_track(record.video_id, "saved-track", 0, (10, 10, 30, 30), _track())

    restarted_store = VideoStore(repo_root=tmp_path, data_dir=data_dir)
    jobs = JobRegistry()
    for saved in restarted_store.library.iter_tracks():
        jobs.restore_completed(saved.job_id, saved.track)

    assert restarted_store.get(record.video_id).path == tiny_video
    assert jobs.get("saved-track").to_dict()["state"] == "completed"


def test_library_endpoints_cascade_temp_files_and_clear_only_caches(
    tmp_path: Path, tiny_video: Path
) -> None:
    data_dir = tmp_path / "data"
    store = VideoStore(repo_root=tmp_path, data_dir=data_dir)
    record = store.register_path(tiny_video)
    library = store.library
    library.save_track(record.video_id, "track-1", 0, (10, 10, 30, 30), _track())
    exported = tmp_path / "exports" / "export-1.mp4"
    exported.parent.mkdir()
    exported.write_bytes(b"mp4")
    library.save_export(
        "export-1", record.video_id, "track-1", {"outWidth": 128, "outHeight": 72}, exported
    )
    cache_file = data_dir / "frames" / record.video_id / "frame.jpg"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"cache")
    app = create_app(store, job_registry=JobRegistry(), exports_dir=tmp_path / "exports")

    with TestClient(app) as client:
        listing = client.get("/api/library")
        assert listing.status_code == 200
        assert listing.json()["videos"][0]["tracks"][0]["jobId"] == "track-1"
        cleared = client.post("/api/library/maintenance/clear-caches")
        assert cleared.status_code == 200
        assert cleared.json()["bytesFreed"] == len(b"cache")
        deleted = client.delete("/api/library/tracks/track-1")

    assert deleted.status_code == 204
    assert not exported.exists()
    assert library.iter_tracks() == []


def test_library_tolerates_corrupt_catalog_and_skips_missing_video(tmp_path: Path) -> None:
    library_dir = tmp_path / "data" / "library"
    library_dir.mkdir(parents=True)
    (library_dir / "videos.json").write_text("not-json", encoding="utf-8")
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    assert list(store.records()) == []


def test_library_skips_track_with_non_object_frame(tmp_path: Path) -> None:
    library = LibraryStore(tmp_path / "data")
    library.save_track("video-1", "bad", 0, (0, 0, 1, 1), _track())
    with sqlite3.connect(library.database_path) as connection:
        connection.execute(
            "UPDATE tracks SET track_json = ? WHERE job_id = ?", ("[7]", "bad")
        )

    assert library.iter_tracks() == []


def test_library_api_skips_malformed_video_rows(tmp_path: Path) -> None:
    library_dir = tmp_path / "data" / "library"
    library_dir.mkdir(parents=True)
    (library_dir / "videos.json").write_text(
        json.dumps(
            [
                7,
                {},
                {
                    "videoId": "non-finite",
                    "path": "/missing.mp4",
                    "metadata": {
                        "width": 320,
                        "height": 180,
                        "fps": "nan",
                        "nbFrames": 4,
                        "duration": 0.4,
                    },
                },
            ]
        ),
        encoding="utf-8",
    )
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")

    with TestClient(create_app(store)) as client:
        response = client.get("/api/library")

    assert response.status_code == 200
    assert response.json()["videos"] == []


def test_library_api_skips_malformed_export_rows(tmp_path: Path) -> None:
    library_dir = tmp_path / "data" / "library"
    library_dir.mkdir(parents=True)
    (library_dir / "exports.json").write_text(
        json.dumps([7, None, "bad"]),
        encoding="utf-8",
    )
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")

    with TestClient(create_app(store)) as client:
        response = client.get("/api/library")

    assert response.status_code == 200
    assert response.json()["videos"] == []


def test_concurrent_export_saves_preserve_both_catalog_rows(
    tmp_path: Path,
) -> None:
    library = LibraryStore(tmp_path / "data")
    export_paths = []
    for export_id in ("first", "second"):
        path = tmp_path / f"{export_id}.mp4"
        path.write_bytes(export_id.encode())
        export_paths.append(path)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            library.save_export, "first", "video", "track", {}, export_paths[0]
        )
        second = pool.submit(
            library.save_export, "second", "video", "track", {}, export_paths[1]
        )
        first.result(timeout=2)
        second.result(timeout=2)

    assert {entry["exportId"] for entry in library.exports()} == {"first", "second"}


@pytest.mark.parametrize("mutation", ["rename", "register"])
def test_missing_file_delete_serializes_with_video_catalog_mutations(
    tmp_path: Path,
    tiny_video: Path,
    mutation: str,
) -> None:
    data_dir = tmp_path / "data"
    initial = VideoStore(repo_root=tmp_path, data_dir=data_dir)
    missing = initial.register_path(tiny_video, "Missing")
    retained_path = tiny_video.with_name("retained.mp4")
    shutil.copyfile(tiny_video, retained_path)
    retained = initial.register_path(retained_path, "Original")
    initial.library.save_track(
        missing.video_id,
        "missing-track",
        0,
        (10, 10, 30, 30),
        _track(),
    )
    exported = tmp_path / "exports" / "missing-export.mp4"
    exported.parent.mkdir()
    exported.write_bytes(b"export")
    initial.library.save_export(
        "missing-export",
        missing.video_id,
        "missing-track",
        {"outWidth": 128, "outHeight": 72},
        exported,
    )
    tiny_video.unlink()
    store = VideoStore(repo_root=tmp_path, data_dir=data_dir)
    app = create_app(
        store, job_registry=JobRegistry(), exports_dir=tmp_path / "exports"
    )
    registered = None
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
        deleted_future = pool.submit(
            client.delete, f"/api/library/videos/{missing.video_id}"
        )
        if mutation == "rename":
            mutation_future = pool.submit(
                store.rename, retained.video_id, "Renamed"
            )
        else:
            third_path = retained_path.with_name("third.mp4")
            shutil.copyfile(retained_path, third_path)
            mutation_future = pool.submit(store.register_path, third_path, "Third")
        deleted_response = deleted_future.result(timeout=8)
        registered = mutation_future.result(timeout=8)

    catalog = {item["videoId"]: item["name"] for item in store.library.videos()}
    memory = {record.video_id: record.name for record in store.records()}
    expected = {
        retained.video_id: "Renamed" if mutation == "rename" else "Original"
    }
    if mutation == "register":
        expected[registered.video_id] = "Third"
    assert deleted_response.status_code == 204
    assert catalog == memory == expected
    assert store.library.iter_tracks() == []
    assert store.library.exports() == []
    assert not exported.exists()


def test_missing_file_delete_catalog_failure_preserves_row_and_cascades(
    tmp_path: Path,
    tiny_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    initial = VideoStore(repo_root=tmp_path, data_dir=data_dir)
    missing = initial.register_path(tiny_video, "Missing")
    initial.library.save_track(
        missing.video_id,
        "missing-track",
        0,
        (10, 10, 30, 30),
        _track(),
    )
    exported = tmp_path / "exports" / "missing-export.mp4"
    exported.parent.mkdir()
    exported.write_bytes(b"export")
    initial.library.save_export(
        "missing-export",
        missing.video_id,
        "missing-track",
        {"outWidth": 128, "outHeight": 72},
        exported,
    )
    tiny_video.unlink()
    store = VideoStore(repo_root=tmp_path, data_dir=data_dir)
    app = create_app(
        store, job_registry=JobRegistry(), exports_dir=tmp_path / "exports"
    )
    original_write = store.library._write

    def fail_video_catalog_write(_operation: object) -> None:
        raise OSError("catalog write failed")

    monkeypatch.setattr(store.library, "_write", fail_video_catalog_write)

    with TestClient(app, raise_server_exceptions=False) as client:
        failed = client.delete(f"/api/library/videos/{missing.video_id}")
        assert failed.status_code == 500
        assert any(
            item["videoId"] == missing.video_id for item in store.library.videos()
        )
        assert store.library.iter_tracks()[0].job_id == "missing-track"
        assert store.library.exports()[0]["exportId"] == "missing-export"
        assert exported.is_file()

        monkeypatch.setattr(store.library, "_write", original_write)
        deleted = client.delete(f"/api/library/videos/{missing.video_id}")

    assert deleted.status_code == 204
    remove_catalog_entry = getattr(store, "remove_catalog_entry", None)
    assert callable(remove_catalog_entry)
    assert remove_catalog_entry(missing.video_id) is False
    assert store.library.iter_tracks() == []
    assert store.library.exports() == []
    assert not exported.exists()


def test_consolidates_duplicate_sources_and_rewrites_references(
    tmp_path: Path, tiny_video: Path
) -> None:
    data_dir = tmp_path / "data"
    library = LibraryStore(data_dir)
    upload_dir = data_dir / "uploads"
    upload_dir.mkdir(parents=True)
    first_upload = upload_dir / "first.mp4"
    duplicate_upload = upload_dir / "duplicate.mp4"
    unrelated_upload = upload_dir / "unrelated.mp4"
    first_upload.write_bytes(tiny_video.read_bytes())
    duplicate_upload.write_bytes(tiny_video.read_bytes())
    unrelated_upload.write_bytes(b"unrelated")
    metadata = {
        "width": 320,
        "height": 180,
        "fps": 10.0,
        "nbFrames": 4,
        "duration": 0.4,
    }
    _seed_video_rows(
        library,
        [
            {
                "videoId": "path-newer",
                "sourceKind": "path",
                "path": str(tiny_video),
                "name": "Newer path name",
                "metadata": metadata,
                "openedAt": "2026-01-02T00:00:00+00:00",
            },
            {
                "videoId": "path-survivor",
                "sourceKind": "path",
                "path": str(tiny_video.resolve()),
                "name": "Surviving path name",
                "metadata": metadata,
                "openedAt": "2026-01-01T00:00:00+00:00",
            },
            {
                "videoId": "upload-newer",
                "sourceKind": "upload",
                "path": str(duplicate_upload),
                "name": "Newer upload name",
                "metadata": metadata,
                "openedAt": "2026-01-02T00:00:00+00:00",
            },
            {
                "videoId": "upload-survivor",
                "sourceKind": "upload",
                "path": str(first_upload),
                "name": "Surviving upload name",
                "metadata": metadata,
                "openedAt": "2026-01-01T00:00:00+00:00",
            },
        ],
    )
    library.save_track(
        "path-newer", "path-track", 0, (10, 10, 30, 30), _track()
    )
    library.save_track(
        "upload-newer", "upload-track", 0, (10, 10, 30, 30), _track()
    )
    path_export = tmp_path / "exports" / "path.mp4"
    upload_export = tmp_path / "exports" / "upload.mp4"
    path_export.parent.mkdir()
    path_export.write_bytes(b"path export")
    upload_export.write_bytes(b"upload export")
    library.save_export("path-export", "path-newer", "path-track", {}, path_export)
    library.save_export(
        "upload-export", "upload-newer", "upload-track", {}, upload_export
    )

    store = VideoStore(repo_root=tmp_path, data_dir=data_dir)

    videos = {item["videoId"]: item for item in store.library.videos()}
    assert set(videos) == {"path-survivor", "upload-survivor"}
    assert videos["path-survivor"]["sourceKey"] == f"path:{tiny_video.resolve()}"
    assert videos["upload-survivor"]["sourceKey"].startswith("sha256:")
    assert {record.video_id for record in store.records()} == set(videos)
    assert {track.job_id: track.video_id for track in store.library.iter_tracks()} == {
        "path-track": "path-survivor",
        "upload-track": "upload-survivor",
    }
    assert {
        item["exportId"]: item["videoId"] for item in store.library.exports()
    } == {
        "path-export": "path-survivor",
        "upload-export": "upload-survivor",
    }
    assert set(upload_dir.iterdir()) == {first_upload, unrelated_upload}
    assert tiny_video.is_file()

    restarted = VideoStore(repo_root=tmp_path, data_dir=data_dir)
    assert {record.video_id for record in restarted.records()} == set(videos)
    assert set(upload_dir.iterdir()) == {first_upload, unrelated_upload}


def test_duplicate_source_consolidation_keeps_uploads_when_catalog_write_fails(
    tmp_path: Path, tiny_video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    library = LibraryStore(data_dir)
    upload_dir = data_dir / "uploads"
    upload_dir.mkdir(parents=True)
    first_upload = upload_dir / "first.mp4"
    duplicate_upload = upload_dir / "duplicate.mp4"
    first_upload.write_bytes(tiny_video.read_bytes())
    duplicate_upload.write_bytes(tiny_video.read_bytes())
    metadata = {
        "width": 320,
        "height": 180,
        "fps": 10.0,
        "nbFrames": 4,
        "duration": 0.4,
    }
    _seed_video_rows(
        library,
        [
            {
                "videoId": "upload-survivor",
                "sourceKind": "upload",
                "path": str(first_upload),
                "metadata": metadata,
                "openedAt": "2026-01-01T00:00:00+00:00",
            },
            {
                "videoId": "upload-duplicate",
                "sourceKind": "upload",
                "path": str(duplicate_upload),
                "metadata": metadata,
                "openedAt": "2026-01-02T00:00:00+00:00",
            },
        ],
    )
    original_write = LibraryStore._write

    def fail_video_catalog_write(
        self: LibraryStore, operation: object
    ) -> object:
        if self.database_path == library.database_path:
            raise OSError("interrupted video catalog write")
        return original_write(self, operation)  # type: ignore[arg-type]

    monkeypatch.setattr(LibraryStore, "_write", fail_video_catalog_write)

    with pytest.raises(OSError, match="interrupted video catalog write"):
        VideoStore(repo_root=tmp_path, data_dir=data_dir)

    assert set(upload_dir.iterdir()) == {first_upload, duplicate_upload}


def test_duplicate_source_consolidation_rewrites_corrupt_track_relational_key(
    tmp_path: Path, tiny_video: Path
) -> None:
    library, first_upload, duplicate_upload = _duplicate_upload_library(
        tmp_path, tiny_video
    )
    library.save_track(
        "upload-duplicate", "corrupt", 0, (10, 10, 30, 30), _track()
    )
    with sqlite3.connect(library.database_path) as connection:
        connection.execute(
            "UPDATE tracks SET track_json = ? WHERE job_id = ?", ("{", "corrupt")
        )

    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")

    assert {item["videoId"] for item in store.library.videos()} == {
        "upload-survivor"
    }
    with sqlite3.connect(library.database_path) as connection:
        video_id = connection.execute(
            "SELECT video_id FROM tracks WHERE job_id = ?", ("corrupt",)
        ).fetchone()[0]
    assert video_id == "upload-survivor"
    assert store.library.iter_tracks() == []
    assert first_upload.is_file()
    assert not duplicate_upload.exists()


def test_duplicate_source_consolidation_rewrites_export_with_corrupt_params(
    tmp_path: Path, tiny_video: Path
) -> None:
    library, first_upload, duplicate_upload = _duplicate_upload_library(
        tmp_path, tiny_video
    )
    exported = tmp_path / "corrupt.mp4"
    exported.write_bytes(b"export")
    library.save_export(
        "corrupt-export", "upload-duplicate", "track", {}, exported
    )
    with sqlite3.connect(library.database_path) as connection:
        connection.execute(
            "UPDATE exports SET params_json = ? WHERE export_id = ?",
            ("{", "corrupt-export"),
        )

    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")

    with sqlite3.connect(library.database_path) as connection:
        video_id = connection.execute(
            "SELECT video_id FROM exports WHERE export_id = ?", ("corrupt-export",)
        ).fetchone()[0]
    assert video_id == "upload-survivor"
    assert store.library.exports() == []
    assert first_upload.is_file()
    assert not duplicate_upload.exists()


def test_library_uses_saved_upload_name_and_falls_back_for_legacy_catalogs(
    tmp_path: Path, tiny_video: Path
) -> None:
    data_dir = tmp_path / "data"
    store = VideoStore(repo_root=tmp_path, data_dir=data_dir)
    with tiny_video.open("rb") as source:
        uploaded = store.register_upload(source, r"C:\incoming\Championship Final.mp4")
    legacy = store.register_path(tiny_video)
    with sqlite3.connect(store.library.database_path) as connection:
        connection.execute(
            "UPDATE videos SET name = NULL WHERE video_id = ?", (legacy.video_id,)
        )

    restarted = VideoStore(repo_root=tmp_path, data_dir=data_dir)
    with TestClient(create_app(restarted, job_registry=JobRegistry())) as client:
        response = client.get("/api/library")

    assert response.status_code == 200
    by_id = {item["videoId"]: item for item in response.json()["videos"]}
    assert by_id[uploaded.video_id]["name"] == "Championship Final.mp4"
    assert by_id[legacy.video_id]["name"] == tiny_video.name


def test_library_video_rename_updates_memory_and_catalog(
    tmp_path: Path, tiny_video: Path
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    record = store.register_path(tiny_video)

    with TestClient(create_app(store, job_registry=JobRegistry())) as client:
        renamed = client.patch(
            f"/api/library/videos/{record.video_id}",
            json={"name": "  Championship / Game  "},
        )
        listing = client.get("/api/library")

    assert renamed.status_code == 200
    assert renamed.json() == {
        "videoId": record.video_id,
        "name": "Championship / Game",
    }
    assert listing.json()["videos"][0]["name"] == "Championship / Game"
    assert store.get(record.video_id).name == "Championship / Game"
    assert store.library.videos()[0]["name"] == "Championship / Game"


@pytest.mark.parametrize("name", ["   ", "x" * 81])
def test_library_video_rename_rejects_invalid_names(
    tmp_path: Path, tiny_video: Path, name: str
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    record = store.register_path(tiny_video)

    with TestClient(create_app(store, job_registry=JobRegistry())) as client:
        response = client.patch(
            f"/api/library/videos/{record.video_id}", json={"name": name}
        )

    assert response.status_code == 422
    assert store.get(record.video_id).name == tiny_video.name


def test_library_video_rename_returns_404_for_missing_source(tmp_path: Path) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")

    with TestClient(create_app(store, job_registry=JobRegistry())) as client:
        response = client.patch(
            "/api/library/videos/missing", json={"name": "New name"}
        )

    assert response.status_code == 404


def test_tracking_completion_helper_writes_the_completed_track(tmp_path: Path) -> None:
    library = LibraryStore(tmp_path / "data")
    persist_completed_track(
        library,
        video_id="video-1",
        job_id="track-1",
        anchor_frame_idx=0,
        box=(10, 10, 30, 30),
        track=_track(),
    )
    assert library.iter_tracks()[0].job_id == "track-1"


def test_saved_track_range_round_trips_through_sqlite_and_loader(tmp_path: Path) -> None:
    library = LibraryStore(tmp_path / "data")
    track = [
        TrackFrame(100, (10, 10, 30, 30), (20.0, 20.0), False),
        TrackFrame(139, None, None, True),
    ]

    library.save_track(
        "video-1",
        "range-track",
        110,
        (10, 10, 30, 30),
        track,
        start_frame_idx=100,
        end_frame_exclusive=140,
    )

    with sqlite3.connect(library.database_path) as connection:
        raw = connection.execute(
            "SELECT start_frame_idx, end_frame_exclusive FROM tracks WHERE job_id = ?",
            ("range-track",),
        ).fetchone()
    saved = library.iter_tracks()[0]
    assert raw == (100, 140)
    assert saved.start_frame_idx == 100
    assert saved.end_frame_exclusive == 140


def test_track_bounds_are_inferred_from_non_empty_frames(tmp_path: Path) -> None:
    library = LibraryStore(tmp_path / "data")
    library.save_track(
        "video-1",
        "legacy-range",
        101,
        (10, 10, 30, 30),
        [
            TrackFrame(100, (10, 10, 30, 30), (20.0, 20.0), False),
            TrackFrame(139, None, None, True),
        ],
    )

    saved = library.iter_tracks()[0]

    assert saved.start_frame_idx == 100
    assert saved.end_frame_exclusive == 140


def test_library_api_uses_full_source_bounds_for_empty_track(
    tmp_path: Path, tiny_video: Path
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    record = store.register_path(tiny_video)
    store.library.save_track(
        record.video_id,
        "empty-legacy",
        0,
        (10, 10, 30, 30),
        [],
        start_frame_idx=0,
        end_frame_exclusive=record.metadata.nb_frames,
    )
    with TestClient(create_app(store, job_registry=JobRegistry())) as client:
        response = client.get("/api/library")

    track = response.json()["videos"][0]["tracks"][0]
    assert track["startFrameIdx"] == 0
    assert track["endFrameExclusive"] == record.metadata.nb_frames


def test_library_allocates_persists_and_renames_player_names(tmp_path: Path) -> None:
    library = LibraryStore(tmp_path / "data")
    library.save_track(
        "video-1", "track-1", 0, (10, 10, 30, 30), _track(), name="Skater"
    )

    assert library.resolve_player_name("video-1", None) == "Player 1"
    library.save_track(
        "video-1", "track-2", 0, (10, 10, 30, 30), _track(), name="Player 1"
    )
    assert library.resolve_player_name("video-1", "  Skater  ") == "Skater"
    assert library.resolve_player_name("video-1", "") == "Player 2"

    renamed = library.rename_track("track-2", "  Goalie  ")

    assert renamed is not None
    assert renamed.name == "Goalie"
    assert {track.job_id: track.name for track in library.iter_tracks()} == {
        "track-1": "Skater",
        "track-2": "Goalie",
    }


def test_library_keeps_legacy_player_names_over_80_characters(
    tmp_path: Path, tiny_video: Path
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    record = store.register_path(tiny_video, "Game")
    legacy_name = f"Legacy Player {'x' * 80}"
    track_job_id = "legacy-track"
    store.library.save_track(
        record.video_id,
        track_job_id,
        0,
        (10, 10, 30, 30),
        _track(),
        name=legacy_name,
    )
    export_id = "legacy-export-a1b2c3"
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    exported = exports_dir / f"{export_id}.mp4"
    exported.write_bytes(b"fake-mp4")
    store.library.save_export(
        export_id,
        record.video_id,
        track_job_id,
        {"outWidth": 128, "outHeight": 72},
        exported,
    )
    jobs = JobRegistry()
    jobs.restore_completed(export_id, [])

    saved = store.library.iter_tracks()
    with TestClient(
        create_app(store, job_registry=jobs, exports_dir=exports_dir)
    ) as client:
        listing = client.get("/api/library")
        downloaded = client.get(f"/api/exports/{export_id}.mp4")

    assert len(saved) == 1
    assert saved[0].name == legacy_name
    assert listing.json()["videos"][0]["tracks"][0]["name"] == legacy_name
    assert downloaded.headers["content-disposition"].startswith(
        'attachment; filename="game-legacy-player-'
    )


def test_library_backfills_legacy_track_names_in_stable_order(tmp_path: Path) -> None:
    library = LibraryStore(tmp_path / "data")
    library.save_track("video-1", "later", 0, (10, 10, 30, 30), _track())
    library.save_track("video-1", "earlier", 0, (10, 10, 30, 30), _track())
    with sqlite3.connect(library.database_path) as connection:
        connection.execute(
            "UPDATE tracks SET created_at = ? WHERE job_id = ?",
            ("2026-01-02T00:00:00+00:00", "later"),
        )
        connection.execute(
            "UPDATE tracks SET created_at = ? WHERE job_id = ?",
            ("2026-01-01T00:00:00+00:00", "earlier"),
        )

    library.backfill_track_names()

    tracks = {track.job_id: track.name for track in library.iter_tracks()}
    assert tracks == {"earlier": "Player 1", "later": "Player 2"}
    with sqlite3.connect(library.database_path) as connection:
        names = dict(connection.execute("SELECT job_id, name FROM tracks"))
    assert names == {"earlier": "Player 1", "later": "Player 2"}


def test_active_jobs_block_source_track_and_cache_deletion(
    tmp_path: Path, tiny_video: Path
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    record = store.register_path(tiny_video)
    track_id = "saved-track"
    track = [TrackFrame(0, (10, 10, 30, 30), (20.0, 20.0), False)]
    store.library.save_track(record.video_id, track_id, 0, track[0].box, track)
    jobs = JobRegistry()
    tracking_release = threading.Event()
    tracking_id = jobs.submit(
        lambda _report: (tracking_release.wait(timeout=2), track)[1],
        resources={f"video:{record.video_id}", "cache"},
    )

    with TestClient(create_app(store, job_registry=jobs)) as client:
        assert client.delete(f"/api/library/videos/{record.video_id}").status_code == 409
        assert client.post("/api/library/maintenance/clear-caches").status_code == 409
        tracking_release.set()
        assert jobs.wait_until_terminal(tracking_id, timeout=2).state == "completed"
        export_release = threading.Event()
        export_id = jobs.submit_progress(
            lambda _job_id, _report: export_release.wait(timeout=2),
            completion_message="Export complete",
            resources={f"video:{record.video_id}", f"track:{track_id}"},
        )
        assert client.delete(f"/api/library/videos/{record.video_id}").status_code == 409
        assert client.delete(f"/api/library/tracks/{track_id}").status_code == 409
        export_release.set()
        assert jobs.wait_until_terminal(export_id, timeout=2).state == "completed"
        assert client.delete(f"/api/library/tracks/{track_id}").status_code == 204
        assert client.delete(f"/api/library/videos/{record.video_id}").status_code == 204


def test_track_route_serializes_submission_and_persistence_against_deletion(
    tmp_path: Path, tiny_video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    record = store.register_path(tiny_video)
    jobs = JobRegistry()
    submit_entered = threading.Event()
    allow_submit = threading.Event()
    worker_release = threading.Event()
    persistence_entered = threading.Event()
    persistence_release = threading.Event()
    real_submit = jobs.submit
    real_save_track = store.library.save_track

    def delayed_submit(worker: object, **kwargs: object) -> str:
        submit_entered.set()
        assert allow_submit.wait(timeout=2)
        return real_submit(worker, **kwargs)

    def blocked_save_track(*args: object, **kwargs: object) -> None:
        real_save_track(*args, **kwargs)
        persistence_entered.set()
        assert persistence_release.wait(timeout=2)

    class BlockingTracker:
        def track(self, *_args: object, **_kwargs: object) -> list[TrackFrame]:
            assert worker_release.wait(timeout=2)
            return [TrackFrame(0, (10, 10, 30, 30), (20.0, 20.0), False)]

    monkeypatch.setattr(jobs, "submit", delayed_submit)
    monkeypatch.setattr(store.library, "save_track", blocked_save_track)
    app = create_app(store, job_registry=jobs, track_runner=BlockingTracker())
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=3) as pool:
        started_future = pool.submit(
            client.post,
            "/api/track",
            json={
                "videoId": record.video_id,
                "frameIdx": 0,
                "box": [10, 10, 30, 30],
            },
        )
        assert submit_entered.wait(timeout=2)
        delete_future = pool.submit(
            client.delete, f"/api/library/videos/{record.video_id}"
        )
        clear_future = pool.submit(
            client.post, "/api/library/maintenance/clear-caches"
        )
        assert not delete_future.done()
        assert not clear_future.done()
        allow_submit.set()
        started = started_future.result(timeout=2)
        assert started.status_code == 202
        assert delete_future.result(timeout=2).status_code == 409
        assert clear_future.result(timeout=2).status_code == 409

        worker_release.set()
        assert persistence_entered.wait(timeout=2)
        assert store.library.iter_tracks()
        assert client.delete(f"/api/library/tracks/{started.json()['jobId']}").status_code == 409
        assert client.delete(f"/api/library/videos/{record.video_id}").status_code == 409
        persistence_release.set()
        assert jobs.wait_until_terminal(started.json()["jobId"], timeout=2).state == "completed"
        assert client.delete(f"/api/library/tracks/{started.json()['jobId']}").status_code == 204
        assert client.delete(f"/api/library/videos/{record.video_id}").status_code == 204
