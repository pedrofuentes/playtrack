from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path

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
    calls: list[tuple[str, int, tuple[int, int, int, int]]] = field(
        default_factory=list
    )

    def track(
        self,
        video_id: str,
        frame_idx: int,
        box: tuple[int, int, int, int],
        on_update: object,
    ) -> list[TrackFrame]:
        self.calls.append((video_id, frame_idx, box))
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
    assert tracker.calls == [(video_id, 1, (100, 50, 140, 100))]


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
