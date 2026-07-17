from __future__ import annotations

import json
from pathlib import Path

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
