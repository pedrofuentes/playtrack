from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.videos import VideoStore


def test_registers_local_video_and_returns_metadata(
    client: TestClient, tiny_video: Path
) -> None:
    response = client.post("/api/videos", json={"path": str(tiny_video)})

    assert response.status_code == 201
    payload = response.json()
    assert payload.keys() == {
        "videoId",
        "width",
        "height",
        "fps",
        "nbFrames",
        "duration",
    }
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
