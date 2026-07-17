from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.jobs import JobRegistry
from app.main import create_app
from app.tracking import TrackFrame
from app.videos import VideoStore


def tracked_frame(frame_idx: int) -> TrackFrame:
    return TrackFrame(
        frame_idx=frame_idx,
        box=(100, 200, 140, 260),
        center=(120.0, 230.0),
        lost=False,
    )


@dataclass
class BlockingFakeTracker:
    published: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)
    calls: list[tuple[str, int, tuple[int, int, int, int], int, int | None]] = field(
        default_factory=list
    )

    def track(
        self,
        video_id: str,
        frame_idx: int,
        box: tuple[int, int, int, int],
        *,
        start_frame_idx: int = 0,
        end_frame_exclusive: int | None = None,
        on_update: object,
    ) -> list[TrackFrame]:
        self.calls.append(
            (video_id, frame_idx, box, start_frame_idx, end_frame_exclusive)
        )
        first = tracked_frame(frame_idx)
        on_update(0.5, "Tracking forward", first)
        self.published.set()
        if not self.release.wait(timeout=2):
            raise TimeoutError("test did not release fake tracker")
        second = tracked_frame(frame_idx + 1)
        on_update(1.0, "Tracking backward", second)
        return [first, second]


def make_tracking_client(
    tmp_path: Path, tiny_video: Path
) -> tuple[TestClient, str, BlockingFakeTracker]:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    record = store.register_path(tiny_video)
    tracker = BlockingFakeTracker()
    app = create_app(
        store,
        track_runner=tracker,
        job_registry=JobRegistry(),
    )
    return TestClient(app), record.video_id, tracker


def test_track_post_websocket_partial_updates_and_finished_get(
    tmp_path: Path, tiny_video: Path
) -> None:
    client, video_id, tracker = make_tracking_client(tmp_path, tiny_video)
    with client:
        response = client.post(
            "/api/track",
            json={
                "videoId": video_id,
                "frameIdx": 1,
                "box": [100, 50, 140, 100],
            },
        )
        assert response.status_code == 202
        assert response.json()["playerName"] == "Player 1"
        job_id = response.json()["jobId"]
        assert tracker.published.wait(timeout=2)

        with client.websocket_connect(f"/ws/jobs/{job_id}") as websocket:
            partial = websocket.receive_json()
            assert partial == {
                "jobId": job_id,
                "state": "running",
                "progress": 0.5,
                "message": "Tracking forward",
                "track": [
                    {
                        "frameIdx": 1,
                        "box": [100, 200, 140, 260],
                        "center": [120.0, 230.0],
                        "lost": False,
                    }
                ],
            }
            tracker.release.set()
            finished = websocket.receive_json()

        assert finished["state"] == "completed"
        assert finished["progress"] == 1.0
        assert [item["frameIdx"] for item in finished["track"]] == [1, 2]
        fetched = client.get(f"/api/track/{job_id}")

    assert fetched.status_code == 200
    assert fetched.json() == finished
    assert tracker.calls == [(video_id, 1, (100, 50, 140, 100), 0, 4)]


def test_track_range_is_forwarded_and_persisted_in_library(
    tmp_path: Path, tiny_video: Path
) -> None:
    client, video_id, tracker = make_tracking_client(tmp_path, tiny_video)
    with client:
        response = client.post(
            "/api/track",
            json={
                "videoId": video_id,
                "frameIdx": 2,
                "box": [100, 50, 140, 100],
                "startFrameIdx": 1,
                "endFrameExclusive": 4,
            },
        )
        assert response.status_code == 202
        tracker.release.set()
        snapshot = client.app.state.job_registry.wait_until_terminal(
            response.json()["jobId"], timeout=2
        )
        assert snapshot.state == "completed"
        deadline = time.monotonic() + 2
        while not client.app.state.video_store.library.iter_tracks():
            if time.monotonic() >= deadline:
                raise TimeoutError("completed track was not persisted")
            time.sleep(0.01)
        listing = client.get("/api/library").json()

    assert tracker.calls == [(video_id, 2, (100, 50, 140, 100), 1, 4)]
    saved = listing["videos"][0]["tracks"][0]
    assert saved["startFrameIdx"] == 1
    assert saved["endFrameExclusive"] == 4


@pytest.mark.parametrize(
    ("start_frame_idx", "end_frame_exclusive", "anchor_frame_idx"),
    [
        (-1, 3, 1),
        (1, 1, 1),
        (3, 2, 3),
        (0, 5, 1),
        (1, 4, 0),
        (1, 4, 4),
    ],
)
def test_track_rejects_invalid_range_bounds_and_anchor(
    tmp_path: Path,
    tiny_video: Path,
    start_frame_idx: int,
    end_frame_exclusive: int,
    anchor_frame_idx: int,
) -> None:
    client, video_id, tracker = make_tracking_client(tmp_path, tiny_video)
    with client:
        response = client.post(
            "/api/track",
            json={
                "videoId": video_id,
                "frameIdx": anchor_frame_idx,
                "box": [100, 50, 140, 100],
                "startFrameIdx": start_frame_idx,
                "endFrameExclusive": end_frame_exclusive,
            },
        )

    tracker.release.set()
    assert response.status_code == 422
    assert tracker.calls == []


def test_track_persists_trimmed_player_name_and_library_allows_rename(
    tmp_path: Path, tiny_video: Path
) -> None:
    client, video_id, tracker = make_tracking_client(tmp_path, tiny_video)
    with client:
        started = client.post(
            "/api/track",
            json={
                "videoId": video_id,
                "frameIdx": 1,
                "box": [100, 50, 140, 100],
                "playerName": "  White 19  ",
            },
        )
        assert started.status_code == 202
        assert started.json()["playerName"] == "White 19"
        tracker.release.set()
        job_id = started.json()["jobId"]
        assert client.get(f"/api/track/{job_id}").json()["state"] in {
            "running", "completed"
        }
        snapshot = client.app.state.job_registry.wait_until_terminal(job_id, timeout=2)
        assert snapshot.state == "completed"

        listing = client.get("/api/library")
        assert listing.json()["videos"][0]["tracks"][0]["name"] == "White 19"
        renamed = client.patch(
            f"/api/library/tracks/{job_id}", json={"name": "  Goalie  "}
        )

    assert renamed.status_code == 200
    assert renamed.json() == {"jobId": job_id, "name": "Goalie"}


def test_track_rejects_overlong_player_name(
    tmp_path: Path, tiny_video: Path
) -> None:
    client, video_id, tracker = make_tracking_client(tmp_path, tiny_video)
    with client:
        response = client.post(
            "/api/track",
            json={
                "videoId": video_id,
                "frameIdx": 0,
                "box": [100, 50, 140, 100],
                "playerName": "x" * 81,
            },
        )
    tracker.release.set()
    assert response.status_code == 422


def test_track_validates_player_name_after_trimming(
    tmp_path: Path, tiny_video: Path
) -> None:
    client, video_id, tracker = make_tracking_client(tmp_path, tiny_video)
    expected = "x" * 80
    with client:
        response = client.post(
            "/api/track",
            json={
                "videoId": video_id,
                "frameIdx": 0,
                "box": [100, 50, 140, 100],
                "playerName": f"  {expected}  ",
            },
        )
    tracker.release.set()
    assert response.status_code == 202
    assert response.json()["playerName"] == expected


def test_track_endpoints_validate_video_box_and_job(
    tmp_path: Path, tiny_video: Path
) -> None:
    client, video_id, tracker = make_tracking_client(tmp_path, tiny_video)
    with client:
        missing_video = client.post(
            "/api/track",
            json={"videoId": "missing", "frameIdx": 0, "box": [1, 1, 2, 2]},
        )
        invalid_box = client.post(
            "/api/track",
            json={"videoId": video_id, "frameIdx": 0, "box": [1, 1, 999, 999]},
        )
        missing_job = client.get("/api/track/missing")

    tracker.release.set()
    assert missing_video.status_code == 404
    assert invalid_box.status_code == 422
    assert missing_job.status_code == 404
