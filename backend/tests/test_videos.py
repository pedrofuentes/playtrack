from __future__ import annotations

import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.videos import VideoStore


def test_registers_local_video_and_returns_metadata(
    client: TestClient, tiny_video: Path
) -> None:
    response = client.post("/api/videos", json={"path": str(tiny_video)})

    assert response.status_code == 201
    payload = response.json()
    assert payload.keys() == {
        "videoId",
        "name",
        "width",
        "height",
        "fps",
        "nbFrames",
        "duration",
    }
    assert payload["name"] == tiny_video.name
    assert payload["width"] == 320
    assert payload["height"] == 180
    assert payload["fps"] == 10.0
    assert payload["nbFrames"] == 4
    assert payload["duration"] == 0.4


def test_registers_multipart_upload(
    client: TestClient, video_store: VideoStore, tiny_video: Path
) -> None:
    with tiny_video.open("rb") as source:
        response = client.post(
            "/api/videos",
            files={"file": (r"C:\matches\Opening Match.mp4", source, "video/mp4")},
        )

    assert response.status_code == 201
    assert response.json()["width"] == 320
    record = video_store.get(response.json()["videoId"])
    assert record.display_name == "Opening Match.mp4"
    assert record.path.name != record.display_name
    assert video_store.library.videos()[0]["name"] == "Opening Match.mp4"


def test_registration_accepts_source_names_and_blank_names_use_filenames(
    client: TestClient, tiny_video: Path
) -> None:
    named = client.post(
        "/api/videos",
        json={"path": str(tiny_video), "name": "  Championship Game  "},
    )
    blank_path = tiny_video.with_name("Blank Name.mp4")
    shutil.copyfile(tiny_video, blank_path)
    fallback = client.post(
        "/api/videos", json={"path": str(blank_path), "name": "   "}
    )

    with tiny_video.open("rb") as source:
        uploaded = client.post(
            "/api/videos",
            data={"name": "  Opening Night  "},
            files={"file": (r"C:\matches\Opening Match.mp4", source, "video/mp4")},
        )

    assert named.status_code == 201
    assert named.json()["name"] == "Championship Game"
    assert fallback.status_code == 201
    assert fallback.json()["name"] == "Blank Name.mp4"
    assert uploaded.status_code == 201
    assert uploaded.json()["name"] == "Opening Night"


def test_explicit_names_rename_reused_sources_and_blank_names_preserve_them(
    tmp_path: Path, tiny_video: Path
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    path_record = store.register_path(tiny_video, "First path name")
    reused_path = store.register_path(tiny_video, "  Renamed / path  ")
    preserved_path = store.register_path(tiny_video, "   ")

    with tiny_video.open("rb") as source:
        upload_record = store.register_upload(source, "clip.mp4", "First upload name")
    with tiny_video.open("rb") as source:
        reused_upload = store.register_upload(source, "duplicate.mp4", " Renamed upload ")
    with tiny_video.open("rb") as source:
        preserved_upload = store.register_upload(source, "ignored.mp4", "")

    assert reused_path.video_id == path_record.video_id
    assert preserved_path.name == "Renamed / path"
    assert reused_upload.video_id == upload_record.video_id
    assert preserved_upload.name == "Renamed upload"
    assert {item["videoId"]: item["name"] for item in store.library.videos()} == {
        path_record.video_id: "Renamed / path",
        upload_record.video_id: "Renamed upload",
    }
    restarted = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    assert restarted.get(path_record.video_id).name == "Renamed / path"
    assert restarted.get(upload_record.video_id).name == "Renamed upload"


def test_filename_fallbacks_over_80_characters_survive_listing_and_restart(
    tmp_path: Path, tiny_video: Path
) -> None:
    long_path = tiny_video.with_name(f"{'p' * 81}.mp4")
    shutil.copyfile(tiny_video, long_path)
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    path_record = store.register_path(long_path)
    upload_filename = f"{'u' * 81}.mp4"
    with tiny_video.open("rb") as source:
        upload_record = store.register_upload(source, upload_filename)

    with TestClient(
        create_app(store), raise_server_exceptions=False
    ) as long_name_client:
        listing = long_name_client.get("/api/library")

    assert listing.status_code == 200
    assert {item["videoId"]: item["name"] for item in listing.json()["videos"]} == {
        path_record.video_id: long_path.name,
        upload_record.video_id: upload_filename,
    }
    restarted = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    assert restarted.get(path_record.video_id).name == long_path.name
    assert restarted.get(upload_record.video_id).name == upload_filename


def test_concurrent_video_renames_are_serialized(
    tmp_path: Path, tiny_video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    record = store.register_path(tiny_video, "Original")
    original_rename = store.library.rename_video
    rendezvous = threading.Barrier(2)
    counter_lock = threading.Lock()
    active = 0
    max_active = 0

    def synchronized_rename(video_id: str, raw_name: str) -> str | None:
        nonlocal active, max_active
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            try:
                rendezvous.wait(timeout=0.2)
            except threading.BrokenBarrierError:
                pass
            return original_rename(video_id, raw_name)
        finally:
            with counter_lock:
                active -= 1

    monkeypatch.setattr(store.library, "rename_video", synchronized_rename)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda name: store.rename(record.video_id, name), ("Alpha", "Beta")))

    persisted_name = store.library.videos()[0]["name"]
    assert max_active == 1
    assert store.get(record.video_id).name == persisted_name


def test_video_rename_catalog_failure_preserves_memory_and_catalog(
    tmp_path: Path, tiny_video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    record = store.register_path(tiny_video, "Original")

    def fail_catalog_write(
        path: Path, entries: list[dict[str, object]]
    ) -> None:
        raise OSError("catalog write failed")

    monkeypatch.setattr(store.library, "_write_list", fail_catalog_write)

    with pytest.raises(OSError, match="catalog write failed"):
        store.rename(record.video_id, "Replacement")

    assert store.get(record.video_id).name == "Original"
    assert store.library.videos()[0]["name"] == "Original"


def test_reuses_canonical_path_registration(
    tmp_path: Path, tiny_video: Path
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")

    first = store.register_path(tiny_video.relative_to(tmp_path))
    second = store.register_path(tiny_video.resolve())

    assert second.video_id == first.video_id
    assert len(store.library.videos()) == 1
    assert len(store.records()) == 1


def test_discards_duplicate_uploaded_content(
    tmp_path: Path, tiny_video: Path
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")

    with tiny_video.open("rb") as source:
        first = store.register_upload(source, "one.mp4")
    with tiny_video.open("rb") as source:
        second = store.register_upload(source, "two.mp4")

    assert second.video_id == first.video_id
    assert list(store.upload_dir.iterdir()) == [first.path]


def test_path_registration_does_not_publish_after_catalog_write_failure(
    tmp_path: Path, tiny_video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    original_write_list = store.library._write_list

    def fail_catalog_write(
        path: Path, entries: list[dict[str, object]]
    ) -> None:
        raise OSError("catalog write failed")

    monkeypatch.setattr(store.library, "_write_list", fail_catalog_write)

    with pytest.raises(OSError, match="catalog write failed"):
        store.register_path(tiny_video)
    records_after_failure = store.records()

    monkeypatch.setattr(store.library, "_write_list", original_write_list)
    retried = store.register_path(tiny_video)

    assert records_after_failure == ()
    assert store.records() == (retried,)
    assert store.library.videos()[0]["videoId"] == retried.video_id


def test_upload_registration_cleans_up_and_retries_after_catalog_write_failure(
    tmp_path: Path, tiny_video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    original_write_list = store.library._write_list

    def fail_catalog_write(
        path: Path, entries: list[dict[str, object]]
    ) -> None:
        raise OSError("catalog write failed")

    monkeypatch.setattr(store.library, "_write_list", fail_catalog_write)

    with tiny_video.open("rb") as source:
        with pytest.raises(OSError, match="catalog write failed"):
            store.register_upload(source, "failed.mp4")
    records_after_failure = store.records()
    files_after_failure = tuple(store.upload_dir.iterdir())

    monkeypatch.setattr(store.library, "_write_list", original_write_list)
    with tiny_video.open("rb") as source:
        retried = store.register_upload(source, "retried.mp4")

    assert records_after_failure == ()
    assert files_after_failure == ()
    assert retried.path.is_file()
    assert store.records() == (retried,)
    assert list(store.upload_dir.iterdir()) == [retried.path]
    assert store.library.videos()[0]["videoId"] == retried.video_id


def test_rejects_missing_local_video(client: TestClient) -> None:
    response = client.post("/api/videos", json={"path": "missing.mp4"})

    assert response.status_code == 404
    assert response.json()["detail"] == "Video file not found: missing.mp4"


def test_video_file_supports_byte_ranges(
    client: TestClient, registered_video: dict[str, object]
) -> None:
    response = client.get(
        f"/api/videos/{registered_video['videoId']}/file",
        headers={"Range": "bytes=0-31"},
    )

    assert response.status_code == 206
    assert len(response.content) == 32
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"].startswith("bytes 0-31/")
    assert response.headers["content-type"] == "video/mp4"


def test_unknown_video_returns_404(client: TestClient) -> None:
    response = client.get("/api/videos/not-registered/file")

    assert response.status_code == 404
    assert response.json()["detail"] == "Video not found"


def test_frame_extraction_is_cached(
    client: TestClient,
    video_store: VideoStore,
    registered_video: dict[str, object],
) -> None:
    video_id = str(registered_video["videoId"])
    first = client.get(f"/api/videos/{video_id}/frames/2")
    cache_path = video_store.get(video_id).frame_cache_dir / "00000002.jpg"
    first_mtime = cache_path.stat().st_mtime_ns
    second = client.get(f"/api/videos/{video_id}/frames/2")

    assert first.status_code == second.status_code == 200
    assert first.content == second.content
    assert first.headers["content-type"] == "image/jpeg"
    assert first.headers["x-frame-width"] == "320"
    assert first.headers["x-frame-height"] == "180"
    assert first.headers["x-source-scale-x"] == "1.000000"
    assert first.headers["x-source-scale-y"] == "1.000000"
    assert cache_path.stat().st_mtime_ns == first_mtime


def test_frame_extraction_validates_index(
    client: TestClient, registered_video: dict[str, object]
) -> None:
    video_id = registered_video["videoId"]

    response = client.get(f"/api/videos/{video_id}/frames/4")

    assert response.status_code == 422
    assert response.json()["detail"] == "Frame index must be between 0 and 3"
