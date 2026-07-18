from __future__ import annotations

import asyncio
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.videos import InvalidVideoError, VideoStore


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


def test_constant_frame_rate_validation_accepts_timestamp_rounding_jitter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    monkeypatch.setattr(
        store,
        "_frame_timestamps",
        lambda _path: iter((0.0, 0.033367, 0.066733, 0.1001)),
    )

    store._validate_constant_frame_rate(tmp_path / "rounded.mp4")


def test_constant_frame_rate_validation_rejects_variable_intervals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    monkeypatch.setattr(
        store,
        "_frame_timestamps",
        lambda _path: iter((0.0, 0.04, 0.08, 0.16, 0.20)),
    )

    with pytest.raises(InvalidVideoError, match="[Vv]ariable frame rate"):
        store._validate_constant_frame_rate(tmp_path / "variable.mp4")


def test_registration_rejects_a_real_variable_frame_rate_clip(
    tmp_path: Path, tiny_video: Path
) -> None:
    variable = tmp_path / "variable.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=64x64:rate=10:duration=0.5",
            "-vf",
            "setpts=if(lt(N\\,2)\\,N/(10*TB)\\,(N-1)/(5*TB))",
            "-fps_mode",
            "vfr",
            "-y",
            str(variable),
        ],
        check=True,
    )
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")

    with pytest.raises(InvalidVideoError, match="[Vv]ariable frame rate"):
        store.register_path(variable)


def test_path_registration_runs_outside_the_async_event_loop(
    tmp_path: Path, tiny_video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    record = store.register_path(tiny_video)
    event_loop_thread = threading.get_ident()
    registration_threads: list[int] = []

    def observe_registration(_path: str, _name: str | None = None) -> object:
        registration_threads.append(threading.get_ident())
        return record

    monkeypatch.setattr(store, "register_path", observe_registration)
    app = create_app(store)

    async def register() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://localhost"
        ) as client:
            return await client.post("/api/videos", json={"path": "ignored.mp4"})

    response = asyncio.run(register())

    assert response.status_code == 201
    assert registration_threads and registration_threads[0] != event_loop_thread


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


def test_upload_accepts_exact_file_limit_and_rejects_one_byte_over(
    tmp_path: Path, tiny_video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    record = store.register_path(tiny_video)
    observed_sizes: list[int] = []

    def register_upload(source: object, _filename: str | None, _name: str | None) -> object:
        payload = source.read()
        observed_sizes.append(len(payload))
        return record

    monkeypatch.setattr(store, "register_upload", register_upload)
    with TestClient(create_app(store, max_upload_bytes=10)) as client:
        exact = client.post(
            "/api/videos",
            files={"file": ("exact.mp4", b"0123456789", "video/mp4")},
        )
        oversized = client.post(
            "/api/videos",
            files={"file": ("large.mp4", b"01234567890", "video/mp4")},
        )

    assert exact.status_code == 201
    assert oversized.status_code == 413
    assert oversized.json() == {"detail": "Upload exceeds the 10-byte limit"}
    assert observed_sizes == [10]


def test_upload_rejects_impossible_content_length_before_parsing(
    tmp_path: Path, tiny_video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    record = store.register_path(tiny_video)
    called = False

    def register_upload(*_args: object, **_kwargs: object) -> object:
        nonlocal called
        called = True
        return record

    monkeypatch.setattr(store, "register_upload", register_upload)
    with TestClient(create_app(store, max_upload_bytes=10)) as client:
        response = client.post(
            "/api/videos",
            headers={
                "Content-Type": "multipart/form-data; boundary=findme",
                "Content-Length": str(10 + 64 * 1024 + 1),
            },
            content=b"",
        )

    assert response.status_code == 413
    assert called is False


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

    def fail_catalog_write(_operation: object) -> None:
        raise OSError("catalog write failed")

    monkeypatch.setattr(store.library, "_write", fail_catalog_write)

    with pytest.raises(OSError, match="catalog write failed"):
        store.rename(record.video_id, "Replacement")

    assert store.get(record.video_id).name == "Original"
    assert store.library.videos()[0]["name"] == "Original"


def test_registration_and_rename_share_one_catalog_transaction_lock(
    tmp_path: Path,
    tiny_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    original = store.register_path(tiny_video, "Original")
    second_path = tiny_video.with_name("second.mp4")
    shutil.copyfile(tiny_video, second_path)
    original_probe = store._probe_video
    probe_reached = threading.Event()
    release_probe = threading.Event()

    def synchronized_probe(path: Path) -> object:
        if path == second_path:
            probe_reached.set()
            assert release_probe.wait(timeout=3)
        return original_probe(path)

    monkeypatch.setattr(store, "_probe_video", synchronized_probe)

    with ThreadPoolExecutor(max_workers=2) as pool:
        registered_future = pool.submit(store.register_path, second_path, "Second")
        assert probe_reached.wait(timeout=1)
        renamed_future = pool.submit(store.rename, original.video_id, "Renamed")
        renamed_future.result(timeout=2)
        release_probe.set()
        registered = registered_future.result(timeout=8)

    catalog = {item["videoId"]: item["name"] for item in store.library.videos()}
    memory = {record.video_id: record.name for record in store.records()}
    assert catalog == memory == {
        original.video_id: "Renamed",
        registered.video_id: "Second",
    }


def test_delete_and_rename_share_one_catalog_transaction_lock(
    tmp_path: Path,
    tiny_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    deleted = store.register_path(tiny_video, "Delete me")
    retained_path = tiny_video.with_name("retained.mp4")
    shutil.copyfile(tiny_video, retained_path)
    retained = store.register_path(retained_path, "Original")
    original_remove = store.library.remove_video
    delete_write_reached = threading.Event()
    release_delete = threading.Event()

    def synchronized_remove(video_id: str, **kwargs: object) -> None:
        delete_write_reached.set()
        assert release_delete.wait(timeout=2)
        original_remove(video_id, **kwargs)

    monkeypatch.setattr(store.library, "remove_video", synchronized_remove)

    with ThreadPoolExecutor(max_workers=2) as pool:
        deleted_future = pool.submit(store.remove, deleted.video_id)
        assert delete_write_reached.wait(timeout=1)
        renamed_future = pool.submit(store.rename, retained.video_id, "Renamed")
        assert not renamed_future.done()
        release_delete.set()
        deleted_future.result(timeout=8)
        renamed_future.result(timeout=8)

    catalog = {item["videoId"]: item["name"] for item in store.library.videos()}
    memory = {record.video_id: record.name for record in store.records()}
    assert catalog == memory == {retained.video_id: "Renamed"}


def test_video_remove_catalog_failure_preserves_state_media_and_caches(
    tmp_path: Path,
    tiny_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    with tiny_video.open("rb") as source:
        record = store.register_upload(source, "uploaded.mp4")
    cache_dirs = (
        record.frame_cache_dir,
        store.tracking_frame_root / record.video_id,
        store.selection_crop_root / record.video_id,
    )
    for cache_dir in cache_dirs:
        cache_dir.mkdir(parents=True)
        (cache_dir / "cached.bin").write_bytes(b"cache")
    original_write = store.library._write

    def fail_catalog_write(_operation: object) -> None:
        raise OSError("catalog write failed")

    monkeypatch.setattr(store.library, "_write", fail_catalog_write)

    with pytest.raises(OSError, match="catalog write failed"):
        store.remove(record.video_id)

    assert store.get(record.video_id) == record
    assert store.library.videos()[0]["videoId"] == record.video_id
    assert record.path.is_file()
    assert all((cache_dir / "cached.bin").is_file() for cache_dir in cache_dirs)

    monkeypatch.setattr(store.library, "_write", original_write)
    assert store.remove(record.video_id) == record
    assert store.records() == ()
    assert store.library.videos() == []
    assert not record.path.exists()
    assert all(not cache_dir.exists() for cache_dir in cache_dirs)


def test_failed_upload_unlink_is_persisted_and_retried_on_restart(
    tmp_path: Path,
    tiny_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    store = VideoStore(repo_root=tmp_path, data_dir=data_dir)
    with tiny_video.open("rb") as source:
        record = store.register_upload(source, "uploaded.mp4")
    real_unlink = Path.unlink

    def fail_upload_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path == record.path:
            raise PermissionError("file is busy")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_upload_unlink)
    removed = store.remove(record.video_id)

    assert removed == record
    assert record.path.is_file()
    assert store.library.videos() == []
    pending = store.library.pending_deletions(
        kind="upload", target_id=record.video_id
    )
    assert len(pending) == 1
    assert pending[0].attempts == 1

    monkeypatch.setattr(Path, "unlink", real_unlink)
    restarted = VideoStore(repo_root=tmp_path, data_dir=data_dir)

    assert restarted.records() == ()
    assert not record.path.exists()
    assert restarted.library.pending_deletions() == []


def test_reuses_canonical_path_registration(
    tmp_path: Path, tiny_video: Path
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")

    first = store.register_path(tiny_video.relative_to(tmp_path))
    second = store.register_path(tiny_video.resolve())

    assert second.video_id == first.video_id
    assert len(store.library.videos()) == 1
    assert len(store.records()) == 1


def test_concurrent_canonical_path_registrations_commit_one_source(
    tmp_path: Path,
    tiny_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    original_probe = store._probe_video
    probe_rendezvous = threading.Barrier(2)

    def synchronized_probe(path: Path) -> object:
        probe_rendezvous.wait(timeout=3)
        return original_probe(path)

    monkeypatch.setattr(store, "_probe_video", synchronized_probe)

    with ThreadPoolExecutor(max_workers=2) as pool:
        records = list(
            pool.map(
                store.register_path,
                (tiny_video, tiny_video.resolve()),
            )
        )

    assert records[0].video_id == records[1].video_id
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


def test_concurrent_identical_uploads_commit_one_source_and_file(
    tmp_path: Path,
    tiny_video: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    original_probe = store._probe_video
    probe_rendezvous = threading.Barrier(2)

    def synchronized_probe(path: Path) -> object:
        probe_rendezvous.wait(timeout=3)
        return original_probe(path)

    monkeypatch.setattr(store, "_probe_video", synchronized_probe)

    def upload(filename: str) -> object:
        with tiny_video.open("rb") as source:
            return store.register_upload(source, filename)

    with ThreadPoolExecutor(max_workers=2) as pool:
        records = list(pool.map(upload, ("one.mp4", "two.mp4")))

    assert records[0].video_id == records[1].video_id
    assert len(store.library.videos()) == 1
    assert len(store.records()) == 1
    assert list(store.upload_dir.iterdir()) == [records[0].path]


def test_restored_cataloged_path_reuses_original_identity_and_metadata(
    tmp_path: Path, tiny_video: Path
) -> None:
    data_dir = tmp_path / "data"
    original_bytes = tiny_video.read_bytes()
    initial = VideoStore(repo_root=tmp_path, data_dir=data_dir)
    original = initial.register_path(tiny_video, "Championship Game")
    tiny_video.unlink()

    restarted_while_missing = VideoStore(repo_root=tmp_path, data_dir=data_dir)
    assert restarted_while_missing.records() == ()
    tiny_video.write_bytes(original_bytes)

    restored = restarted_while_missing.register_path(tiny_video)

    assert restored.video_id == original.video_id
    assert restored.name == "Championship Game"
    assert restored.metadata == original.metadata
    assert restored.source_kind == "path"
    assert restored.source_key == f"path:{tiny_video.resolve()}"
    assert restarted_while_missing.records() == (restored,)
    assert [item["videoId"] for item in restarted_while_missing.library.videos()] == [
        original.video_id
    ]


def test_path_registration_does_not_publish_after_catalog_write_failure(
    tmp_path: Path, tiny_video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    original_write = store.library._write

    def fail_catalog_write(_operation: object) -> None:
        raise OSError("catalog write failed")

    monkeypatch.setattr(store.library, "_write", fail_catalog_write)

    with pytest.raises(OSError, match="catalog write failed"):
        store.register_path(tiny_video)
    records_after_failure = store.records()

    monkeypatch.setattr(store.library, "_write", original_write)
    retried = store.register_path(tiny_video)

    assert records_after_failure == ()
    assert store.records() == (retried,)
    assert store.library.videos()[0]["videoId"] == retried.video_id


def test_upload_registration_cleans_up_and_retries_after_catalog_write_failure(
    tmp_path: Path, tiny_video: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    original_write = store.library._write

    def fail_catalog_write(_operation: object) -> None:
        raise OSError("catalog write failed")

    monkeypatch.setattr(store.library, "_write", fail_catalog_write)

    with tiny_video.open("rb") as source:
        with pytest.raises(OSError, match="catalog write failed"):
            store.register_upload(source, "failed.mp4")
    records_after_failure = store.records()
    files_after_failure = tuple(store.upload_dir.iterdir())

    monkeypatch.setattr(store.library, "_write", original_write)
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
