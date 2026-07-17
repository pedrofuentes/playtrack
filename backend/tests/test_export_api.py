from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import app.library as library_module
import app.main as main_module
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
    catalog = store.library.videos()
    catalog[0].pop("name", None)
    store.library._write_list(store.library.videos_path, catalog)
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
    exports = store.library.exports()
    exports[0]["createdAt"] = "invalid"
    store.library._write_list(store.library.exports_path, exports)
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
