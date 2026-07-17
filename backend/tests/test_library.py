from __future__ import annotations

import json
from pathlib import Path

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
    library._write_list(
        library.videos_path,
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
    library._write_list(
        library.videos_path,
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
    library._write_list(
        library.videos_path,
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
    original_write_list = LibraryStore._write_list

    def fail_video_catalog_write(
        self: LibraryStore, path: Path, entries: list[dict[str, object]]
    ) -> None:
        if path == self.videos_path:
            raise OSError("interrupted video catalog write")
        original_write_list(self, path, entries)

    monkeypatch.setattr(LibraryStore, "_write_list", fail_video_catalog_write)

    with pytest.raises(OSError, match="interrupted video catalog write"):
        VideoStore(repo_root=tmp_path, data_dir=data_dir)

    assert set(upload_dir.iterdir()) == {first_upload, duplicate_upload}


def test_duplicate_source_consolidation_aborts_on_corrupt_track(
    tmp_path: Path, tiny_video: Path
) -> None:
    library, first_upload, duplicate_upload = _duplicate_upload_library(
        tmp_path, tiny_video
    )
    library.tracks_dir.mkdir(parents=True)
    (library.tracks_dir / "corrupt.json").write_text("{", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")

    assert {
        item["videoId"]
        for item in json.loads(library.videos_path.read_text(encoding="utf-8"))
    } == {"upload-survivor", "upload-duplicate"}
    assert first_upload.is_file()
    assert duplicate_upload.is_file()


def test_duplicate_source_consolidation_aborts_on_unreadable_exports(
    tmp_path: Path, tiny_video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library, first_upload, duplicate_upload = _duplicate_upload_library(
        tmp_path, tiny_video
    )
    library._write_list(library.exports_path, [])
    original_read_object = LibraryStore._read_object

    def fail_export_read(path: Path) -> object:
        if path.name == "exports.json":
            raise PermissionError("unreadable exports catalog")
        return original_read_object(path)

    monkeypatch.setattr(LibraryStore, "_read_object", staticmethod(fail_export_read))

    with pytest.raises(PermissionError, match="unreadable exports catalog"):
        VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")

    assert {
        item["videoId"]
        for item in json.loads(library.videos_path.read_text(encoding="utf-8"))
    } == {"upload-survivor", "upload-duplicate"}
    assert first_upload.is_file()
    assert duplicate_upload.is_file()


def test_library_uses_saved_upload_name_and_falls_back_for_legacy_catalogs(
    tmp_path: Path, tiny_video: Path
) -> None:
    data_dir = tmp_path / "data"
    store = VideoStore(repo_root=tmp_path, data_dir=data_dir)
    with tiny_video.open("rb") as source:
        uploaded = store.register_upload(source, r"C:\incoming\Championship Final.mp4")
    legacy = store.register_path(tiny_video)
    catalog = store.library.videos()
    for item in catalog:
        if item["videoId"] == legacy.video_id:
            item.pop("name", None)
    (data_dir / "library" / "videos.json").write_text(json.dumps(catalog), encoding="utf-8")

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


def test_library_backfills_legacy_track_names_in_stable_order(tmp_path: Path) -> None:
    library = LibraryStore(tmp_path / "data")
    library.save_track("video-1", "later", 0, (10, 10, 30, 30), _track())
    library.save_track("video-1", "earlier", 0, (10, 10, 30, 30), _track())
    later_path = library.tracks_dir / "later.json"
    earlier_path = library.tracks_dir / "earlier.json"
    later = json.loads(later_path.read_text(encoding="utf-8"))
    earlier = json.loads(earlier_path.read_text(encoding="utf-8"))
    later["createdAt"] = "2026-01-02T00:00:00+00:00"
    earlier["createdAt"] = "2026-01-01T00:00:00+00:00"
    later_path.write_text(json.dumps(later), encoding="utf-8")
    earlier_path.write_text(json.dumps(earlier), encoding="utf-8")

    library.backfill_track_names()

    tracks = {track.job_id: track.name for track in library.iter_tracks()}
    assert tracks == {"earlier": "Player 1", "later": "Player 2"}
    assert json.loads(earlier_path.read_text(encoding="utf-8"))["name"] == "Player 1"
    assert json.loads(later_path.read_text(encoding="utf-8"))["name"] == "Player 2"
