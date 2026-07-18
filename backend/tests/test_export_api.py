from __future__ import annotations

import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import app.library as library_module
import app.main as main_module
import pytest
from fastapi.testclient import TestClient

from app.crop_planner import CropWindow
from app.jobs import JobRegistry
from app.main import create_app
from app.tracking import TrackFrame
from app.videos import VideoStore


def completed_track(registry: JobRegistry) -> str:
    frames = [
        TrackFrame(
            frame_idx=index,
            box=(80 + index, 50, 120 + index, 110),
            center=(100.0 + index, 80.0),
            lost=False,
        )
        for index in range(4)
    ]
    job_id = registry.submit(lambda _report: frames)
    registry.wait_until_terminal(job_id, timeout=2)
    return job_id


@dataclass
class FakeExporter:
    calls: list[dict[str, object]] = field(default_factory=list)

    def __call__(
        self,
        source_path: Path,
        destination: Path,
        windows: list[CropWindow],
        *,
        output_width: int,
        output_height: int,
        fps: float,
        source_start_frame: int = 0,
        source_total_frames: int | None = None,
        on_progress: object,
    ) -> Path:
        self.calls.append(
            {
                "source": source_path,
                "destination": destination,
                "windows": windows,
                "size": (output_width, output_height),
                "fps": fps,
                "source_start_frame": source_start_frame,
                "source_total_frames": source_total_frames,
            }
        )
        on_progress(0.5, "Exporting frame 2 of 4")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fake-mp4")
        on_progress(1.0, "Exporting frame 4 of 4")
        return destination


def make_client(
    tmp_path: Path, tiny_video: Path
) -> tuple[TestClient, str, str, JobRegistry, FakeExporter, Path]:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    record = store.register_path(tiny_video)
    jobs = JobRegistry()
    track_job_id = completed_track(jobs)
    track = jobs.get(track_job_id).track
    store.library.save_track(
        record.video_id,
        track_job_id,
        0,
        track[0].box,
        track,
        start_frame_idx=0,
        end_frame_exclusive=record.metadata.nb_frames,
    )
    exporter = FakeExporter()
    exports_dir = tmp_path / "exports"
    app = create_app(
        store,
        job_registry=jobs,
        video_exporter=exporter,
        exports_dir=exports_dir,
    )
    return (
        TestClient(app),
        record.video_id,
        track_job_id,
        jobs,
        exporter,
        exports_dir,
    )


def test_crop_plan_preview_returns_source_windows(
    tmp_path: Path, tiny_video: Path
) -> None:
    client, video_id, track_job_id, _jobs, _exporter, _exports = make_client(
        tmp_path, tiny_video
    )

    with client:
        response = client.get(
            "/api/export/plan",
            params={
                "videoId": video_id,
                "trackJobId": track_job_id,
                "outWidth": 128,
                "outHeight": 72,
                "zoom": 1.5,
                "windowSec": 0.8,
                "deadZonePx": 30,
                "maxVelPxPerFrame": 28,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["videoId"] == video_id
    assert payload["trackJobId"] == track_job_id
    assert len(payload["windows"]) == 4
    assert payload["windows"][0].keys() == {"frameIdx", "x", "y", "w", "h"}


def test_export_job_reports_progress_and_serves_finished_file(
    tmp_path: Path, tiny_video: Path
) -> None:
    client, video_id, track_job_id, jobs, exporter, exports_dir = make_client(
        tmp_path, tiny_video
    )
    request = {
        "videoId": video_id,
        "trackJobId": track_job_id,
        "outWidth": 128,
        "outHeight": 72,
        "zoom": 1.5,
        "smoothing": {
            "windowSec": 0.8,
            "deadZonePx": 30,
            "maxVelPxPerFrame": 28,
        },
    }

    with client:
        started = client.post("/api/export", json=request)
        assert started.status_code == 202
        job_id = started.json()["jobId"]
        snapshot = jobs.wait_until_terminal(job_id, timeout=2)
        downloaded = client.get(f"/api/exports/{job_id}.mp4")

    assert snapshot.state == "completed"
    assert snapshot.message == "Export complete"
    assert downloaded.status_code == 200
    assert downloaded.content == b"fake-mp4"
    assert downloaded.headers["content-type"] == "video/mp4"
    assert exporter.calls[0]["destination"] == exports_dir / f"{job_id}.mp4"
    assert exporter.calls[0]["size"] == (128, 72)


def test_export_uses_saved_track_range_and_output_local_windows(
    tmp_path: Path, tiny_video: Path
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    record = store.register_path(tiny_video)
    track_job_id = "saved-range-track"
    frames = [
        TrackFrame(
            frame_idx=index,
            box=(80 + index, 50, 120 + index, 110),
            center=(100.0 + index, 80.0),
            lost=False,
        )
        for index in range(1, 4)
    ]
    store.library.save_track(
        record.video_id,
        track_job_id,
        2,
        frames[1].box,
        frames,
        start_frame_idx=1,
        end_frame_exclusive=4,
    )
    jobs = JobRegistry()
    exporter = FakeExporter()
    app = create_app(
        store,
        job_registry=jobs,
        video_exporter=exporter,
        exports_dir=tmp_path / "exports",
    )

    with TestClient(app) as client:
        started = client.post(
            "/api/export",
            json={
                "videoId": record.video_id,
                "trackJobId": track_job_id,
                "outWidth": 128,
                "outHeight": 72,
                "zoom": 1.5,
                "smoothing": {},
            },
        )
        assert started.status_code == 202
        snapshot = jobs.wait_until_terminal(started.json()["jobId"], timeout=2)

    assert snapshot.state == "completed"
    assert exporter.calls[0]["source_start_frame"] == 1
    assert exporter.calls[0]["source_total_frames"] == record.metadata.nb_frames
    windows = exporter.calls[0]["windows"]
    assert [window.frame_idx for window in windows] == [0, 1, 2]
    saved_export = store.library.exports()[0]
    assert saved_export["trackJobId"] == track_job_id


def test_crop_plan_preview_reports_source_start_with_local_range_windows(
    tmp_path: Path, tiny_video: Path
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    record = store.register_path(tiny_video)
    track_job_id = "preview-range-track"
    frames = [
        TrackFrame(index, (80, 50, 120, 110), (100.0, 80.0), False)
        for index in range(1, 4)
    ]
    store.library.save_track(
        record.video_id,
        track_job_id,
        2,
        frames[1].box,
        frames,
        start_frame_idx=1,
        end_frame_exclusive=4,
    )

    with TestClient(create_app(store, job_registry=JobRegistry())) as client:
        response = client.get(
            "/api/export/plan",
            params={
                "videoId": record.video_id,
                "trackJobId": track_job_id,
                "outWidth": 128,
                "outHeight": 72,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sourceStartFrame"] == 1
    assert [window["frameIdx"] for window in payload["windows"]] == [0, 1, 2]


def test_export_rejects_saved_track_video_range_mismatch(
    tmp_path: Path, tiny_video: Path
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    first = store.register_path(tiny_video)
    second_path = tmp_path / "second.mp4"
    second_path.write_bytes(tiny_video.read_bytes())
    second = store.register_path(second_path)
    track_job_id = "first-video-track"
    frames = [
        TrackFrame(index, (80, 50, 120, 110), (100.0, 80.0), False)
        for index in range(1, 4)
    ]
    store.library.save_track(
        first.video_id,
        track_job_id,
        2,
        frames[1].box,
        frames,
        start_frame_idx=1,
        end_frame_exclusive=4,
    )

    with TestClient(create_app(store, job_registry=JobRegistry())) as client:
        response = client.post(
            "/api/export",
            json={
                "videoId": second.video_id,
                "trackJobId": track_job_id,
                "outWidth": 128,
                "outHeight": 72,
                "smoothing": {},
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Track does not belong to the selected video"


def test_export_rejects_saved_track_job_content_mismatch(
    tmp_path: Path, tiny_video: Path
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    record = store.register_path(tiny_video)
    track_job_id = "mismatched-job-track"
    saved_frames = [
        TrackFrame(index, (80, 50, 120, 110), (100.0, 80.0), False)
        for index in range(1, 4)
    ]
    store.library.save_track(
        record.video_id,
        track_job_id,
        2,
        saved_frames[1].box,
        saved_frames,
        start_frame_idx=1,
        end_frame_exclusive=4,
    )
    jobs = JobRegistry()
    exporter = FakeExporter()
    app = create_app(store, job_registry=jobs, video_exporter=exporter)
    jobs.restore_completed(
        track_job_id,
        [
            TrackFrame(index, (1, 1, 2, 2), (1.5, 1.5), False)
            for index in range(1, 4)
        ],
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/export",
            json={
                "videoId": record.video_id,
                "trackJobId": track_job_id,
                "outWidth": 128,
                "outHeight": 72,
                "smoothing": {},
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "Tracking job does not match the saved track"
    assert exporter.calls == []


def test_export_download_disposition_uses_current_names_and_unique_suffixes(
    tmp_path: Path, tiny_video: Path, monkeypatch: object
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    record = store.register_path(tiny_video, "Championship Game!!!")
    track_job_id = "saved-track"
    store.library.save_track(
        record.video_id,
        track_job_id,
        0,
        (80, 50, 120, 110),
        [TrackFrame(0, (80, 50, 120, 110), (100.0, 80.0), False)],
        name="White #19",
    )
    monkeypatch.setattr(
        library_module, "_now", lambda: "2026-07-17T14:30:22+00:00"
    )
    export_ids = ("first-export-a1b2c3", "second-export-d4e5f6")
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    jobs = JobRegistry()
    for export_id in export_ids:
        path = exports_dir / f"{export_id}.mp4"
        path.write_bytes(b"fake-mp4")
        store.library.save_export(
            export_id,
            record.video_id,
            track_job_id,
            {"outWidth": 128, "outHeight": 72},
            path,
        )
        jobs.restore_completed(export_id, [])
    store.rename(record.video_id, "  Championship Final!!!  ")
    app = create_app(store, job_registry=jobs, exports_dir=exports_dir)

    with TestClient(app) as client:
        first = client.get(f"/api/exports/{export_ids[0]}.mp4")
        second = client.get(f"/api/exports/{export_ids[1]}.mp4")

    assert first.headers["content-disposition"].endswith(
        'filename="championship-final-white-19-128x72-20260717-143022-a1b2c3.mp4"'
    )
    assert second.headers["content-disposition"].endswith(
        'filename="championship-final-white-19-128x72-20260717-143022-d4e5f6.mp4"'
    )


def test_download_filename_uses_legacy_fallbacks_and_preserves_suffix_when_capped() -> None:
    legacy = main_module.download_filename(
        None,
        object(),
        None,
        "bad",
        "2026-07-17T14:30:22Z",
        "legacy-export-123xyz",
    )
    capped = main_module.download_filename(
        "A" * 200,
        "B" * 200,
        1920,
        1080,
        "2026-07-17T14:30:22+00:00",
        "export-abc123",
    )
    invalid_dimensions = main_module.download_filename(
        "Source",
        "Player",
        int("9" * 200),
        1080,
        "2026-07-17T14:30:22+00:00",
        "export-abc123",
    )
    short_id = main_module.download_filename(
        "Source",
        "Player",
        128,
        72,
        "2026-07-17T14:30:22+00:00",
        "x",
    )
    balanced_prefix = main_module.download_filename(
        "A" * 200,
        "White 19",
        1920,
        1080,
        "2026-07-17T14:30:22+00:00",
        "export-abc123",
    )

    assert legacy == "source-player-video-20260717-143022-123xyz.mp4"
    assert len(capped) <= 180
    assert capped.endswith("-1920x1080-20260717-143022-abc123.mp4")
    assert invalid_dimensions == "source-player-video-20260717-143022-abc123.mp4"
    assert short_id == "source-player-128x72-20260717-143022-2d7116.mp4"
    assert len(balanced_prefix) <= 180
    assert balanced_prefix.startswith("a")
    assert balanced_prefix.endswith(
        "-white-19-1920x1080-20260717-143022-abc123.mp4"
    )


def test_export_download_disposition_falls_back_for_legacy_catalog(
    tmp_path: Path, tiny_video: Path
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    record = store.register_path(tiny_video)
    with sqlite3.connect(store.library.database_path) as connection:
        connection.execute(
            "UPDATE videos SET name = NULL WHERE video_id = ?", (record.video_id,)
        )
    export_id = "legacy-export-123xyz"
    exports_dir = tmp_path / "exports"
    exports_dir.mkdir()
    destination = exports_dir / f"{export_id}.mp4"
    destination.write_bytes(b"fake-mp4")
    created_at = datetime(2026, 7, 17, 14, 30, 22, tzinfo=UTC)
    os.utime(destination, (created_at.timestamp(), created_at.timestamp()))
    store.library.save_export(
        export_id, record.video_id, "missing-track", {}, destination
    )
    with sqlite3.connect(store.library.database_path) as connection:
        connection.execute(
            "UPDATE exports SET created_at = ? WHERE export_id = ?",
            ("invalid", export_id),
        )
    jobs = JobRegistry()
    jobs.restore_completed(export_id, [])

    with TestClient(
        create_app(store, job_registry=jobs, exports_dir=exports_dir)
    ) as client:
        response = client.get(f"/api/exports/{export_id}.mp4")

    assert response.headers["content-disposition"].endswith(
        'filename="source-player-video-20260717-143022-123xyz.mp4"'
    )


def test_export_rejects_incomplete_track_and_odd_output_dimensions(
    tmp_path: Path, tiny_video: Path
) -> None:
    client, video_id, _track_job_id, jobs, _exporter, _exports = make_client(
        tmp_path, tiny_video
    )
    incomplete_id = jobs.submit_progress(
        lambda _job_id, _report: None,
        completion_message="Export complete",
    )

    with client:
        odd = client.post(
            "/api/export",
            json={
                "videoId": video_id,
                "trackJobId": completed_track(jobs),
                "outWidth": 127,
                "outHeight": 72,
                "zoom": 1,
                "smoothing": {},
            },
        )
        missing_file = client.get(f"/api/exports/{incomplete_id}.mp4")

    assert odd.status_code == 422
    assert missing_file.status_code in (404, 409)


def test_export_route_serializes_submission_and_persistence_against_deletion(
    tmp_path: Path, tiny_video: Path, monkeypatch: object
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    record = store.register_path(tiny_video)
    track_id = "export-barrier-track"
    frames = [
        TrackFrame(index, (80, 50, 120, 110), (100.0, 80.0), False)
        for index in range(record.metadata.nb_frames)
    ]
    store.library.save_track(
        record.video_id,
        track_id,
        0,
        frames[0].box,
        frames,
        start_frame_idx=0,
        end_frame_exclusive=record.metadata.nb_frames,
    )
    jobs = JobRegistry()
    submit_entered = threading.Event()
    allow_submit = threading.Event()
    export_release = threading.Event()
    persistence_entered = threading.Event()
    persistence_release = threading.Event()
    real_submit = jobs.submit_progress
    real_save_export = store.library.save_export

    def delayed_submit(worker: object, **kwargs: object) -> str:
        submit_entered.set()
        assert allow_submit.wait(timeout=2)
        return real_submit(worker, **kwargs)

    def blocked_export(
        _source: Path, destination: Path, _windows: object, **kwargs: object
    ) -> Path:
        assert export_release.wait(timeout=2)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fake-mp4")
        kwargs["on_progress"](1.0, "Export complete")
        return destination

    def blocked_save_export(*args: object, **kwargs: object) -> None:
        real_save_export(*args, **kwargs)
        persistence_entered.set()
        assert persistence_release.wait(timeout=2)

    monkeypatch.setattr(jobs, "submit_progress", delayed_submit)
    monkeypatch.setattr(store.library, "save_export", blocked_save_export)
    app = create_app(
        store,
        job_registry=jobs,
        video_exporter=blocked_export,
        exports_dir=tmp_path / "exports",
    )
    request = {
        "videoId": record.video_id,
        "trackJobId": track_id,
        "outWidth": 128,
        "outHeight": 72,
        "smoothing": {},
    }

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=3) as pool:
        started_future = pool.submit(client.post, "/api/export", json=request)
        assert submit_entered.wait(timeout=2)
        source_delete = pool.submit(
            client.delete, f"/api/library/videos/{record.video_id}"
        )
        track_delete = pool.submit(
            client.delete, f"/api/library/tracks/{track_id}"
        )
        assert not source_delete.done()
        assert not track_delete.done()
        allow_submit.set()
        started = started_future.result(timeout=2)
        assert started.status_code == 202
        assert source_delete.result(timeout=2).status_code == 409
        assert track_delete.result(timeout=2).status_code == 409

        export_release.set()
        assert persistence_entered.wait(timeout=2)
        export_id = started.json()["jobId"]
        assert store.library.exports()[0]["exportId"] == export_id
        assert client.delete(f"/api/library/exports/{export_id}").status_code == 409
        assert client.delete(f"/api/library/videos/{record.video_id}").status_code == 409
        assert client.delete(f"/api/library/tracks/{track_id}").status_code == 409
        persistence_release.set()
        assert jobs.wait_until_terminal(export_id, timeout=2).state == "completed"
        assert client.delete(f"/api/library/exports/{export_id}").status_code == 204
        assert client.delete(f"/api/library/tracks/{track_id}").status_code == 204
        assert client.delete(f"/api/library/videos/{record.video_id}").status_code == 204


def test_completed_export_is_downloadable_after_app_restart(
    tmp_path: Path, tiny_video: Path
) -> None:
    data_dir = tmp_path / "data"
    exports_dir = tmp_path / "exports"
    store = VideoStore(repo_root=tmp_path, data_dir=data_dir)
    record = store.register_path(tiny_video)
    destination = exports_dir / "saved-export.mp4"
    destination.parent.mkdir()
    destination.write_bytes(b"persisted-mp4")
    store.library.save_export(
        "saved-export", record.video_id, "saved-track", {}, destination
    )

    restarted = VideoStore(repo_root=tmp_path, data_dir=data_dir)
    with TestClient(create_app(restarted, exports_dir=exports_dir)) as client:
        response = client.get("/api/exports/saved-export.mp4")

    assert response.status_code == 200
    assert response.content == b"persisted-mp4"


def test_export_delete_never_trusts_catalog_path_outside_export_root(
    tmp_path: Path
) -> None:
    exports_dir = tmp_path / "exports"
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("keep", encoding="utf-8")
    store.library.save_export("outside", "video", "track", {}, unrelated)

    with TestClient(create_app(store, exports_dir=exports_dir)) as client:
        response = client.delete("/api/library/exports/outside")

    assert response.status_code == 204
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_export_catalog_failure_removes_unpublished_output(
    tmp_path: Path, tiny_video: Path, monkeypatch: object
) -> None:
    client, video_id, track_job_id, jobs, _exporter, exports_dir = make_client(
        tmp_path, tiny_video
    )

    def fail_save(*_args: object, **_kwargs: object) -> None:
        raise OSError("catalog is read-only")

    monkeypatch.setattr(client.app.state.video_store.library, "save_export", fail_save)
    with client:
        started = client.post(
            "/api/export",
            json={
                "videoId": video_id,
                "trackJobId": track_job_id,
                "outWidth": 128,
                "outHeight": 72,
                "smoothing": {},
            },
        )
        export_id = started.json()["jobId"]
        snapshot = jobs.wait_until_terminal(export_id, timeout=2)

    assert snapshot.state == "failed"
    assert not (exports_dir / f"{export_id}.mp4").exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("outWidth", 4098),
        ("outHeight", 2162),
        ("zoom", 0.9),
        ("zoom", 4.1),
    ],
)
def test_export_preview_and_submission_share_hard_limits(
    tmp_path: Path,
    tiny_video: Path,
    field: str,
    value: float,
) -> None:
    client, video_id, track_job_id, _jobs, _exporter, _exports_dir = make_client(
        tmp_path, tiny_video
    )
    payload: dict[str, object] = {
        "videoId": video_id,
        "trackJobId": track_job_id,
        "outWidth": 128,
        "outHeight": 72,
        "zoom": 1,
        "smoothing": {},
    }
    payload[field] = value
    query = {
        "videoId": video_id,
        "trackJobId": track_job_id,
        "outWidth": payload["outWidth"],
        "outHeight": payload["outHeight"],
        "zoom": payload["zoom"],
    }

    with client:
        submitted = client.post("/api/export", json=payload)
        previewed = client.get("/api/export/plan", params=query)

    assert submitted.status_code == 422
    assert previewed.status_code == 422


def test_export_accepts_balanced_4k_boundary(
    tmp_path: Path, tiny_video: Path
) -> None:
    client, video_id, track_job_id, _jobs, _exporter, _exports_dir = make_client(
        tmp_path, tiny_video
    )

    with client:
        response = client.post(
            "/api/export",
            json={
                "videoId": video_id,
                "trackJobId": track_job_id,
                "outWidth": 4096,
                "outHeight": 2160,
                "zoom": 4,
                "smoothing": {
                    "responsiveness": 10,
                    "maxAccelPxPerFrame2": 10_000,
                },
            },
        )

    assert response.status_code == 202


@pytest.mark.parametrize(
    "query",
    [
        {"responsiveness": "nan"},
        {"responsiveness": "11"},
        {"maxAccelPxPerFrame2": "inf"},
        {"maxAccelPxPerFrame2": "0.05"},
    ],
)
def test_export_preview_rejects_non_finite_or_unbounded_smoothing(
    tmp_path: Path, tiny_video: Path, query: dict[str, str]
) -> None:
    client, video_id, track_job_id, _jobs, _exporter, _exports_dir = make_client(
        tmp_path, tiny_video
    )
    params = {
        "videoId": video_id,
        "trackJobId": track_job_id,
        "outWidth": "128",
        "outHeight": "72",
        **query,
    }

    with client:
        response = client.get("/api/export/plan", params=params)

    assert response.status_code == 422
