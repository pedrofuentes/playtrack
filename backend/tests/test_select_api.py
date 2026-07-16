from __future__ import annotations

from dataclasses import dataclass, field

from fastapi.testclient import TestClient

from app.main import create_app
from app.selection import (
    ClickSelection,
    SelectionInputError,
    SelectionUnavailableError,
)
from app.videos import VideoNotFoundError, VideoStore


@dataclass
class FakeSelector:
    result: ClickSelection | None = None
    error: Exception | None = None
    calls: list[tuple[str, int, int, int]] = field(default_factory=list)

    def select_click(
        self, video_id: str, frame_idx: int, x: int, y: int
    ) -> ClickSelection:
        self.calls.append((video_id, frame_idx, x, y))
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def test_click_selection_route_returns_contract(video_store: VideoStore) -> None:
    selector = FakeSelector(
        result=ClickSelection(
            box=(100, 200, 140, 260),
            mask_png="iVBORw0KGgo=",
            score=0.875,
        )
    )
    with TestClient(create_app(video_store, click_selector=selector)) as client:
        response = client.post(
            "/api/select/click",
            json={"videoId": "video-1", "frameIdx": 12, "x": 2048, "y": 512},
        )

    assert response.status_code == 200
    assert response.json() == {
        "box": [100, 200, 140, 260],
        "maskPng": "iVBORw0KGgo=",
        "score": 0.875,
    }
    assert selector.calls == [("video-1", 12, 2048, 512)]


def test_click_selection_maps_input_errors_to_422(video_store: VideoStore) -> None:
    selector = FakeSelector(error=SelectionInputError("bad click"))
    with TestClient(create_app(video_store, click_selector=selector)) as client:
        response = client.post(
            "/api/select/click",
            json={"videoId": "video-1", "frameIdx": 0, "x": 10, "y": 20},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "bad click"


def test_click_selection_maps_missing_video_to_404(video_store: VideoStore) -> None:
    selector = FakeSelector(error=VideoNotFoundError("Video not found"))
    with TestClient(create_app(video_store, click_selector=selector)) as client:
        response = client.post(
            "/api/select/click",
            json={"videoId": "missing", "frameIdx": 0, "x": 10, "y": 20},
        )

    assert response.status_code == 404


def test_click_selection_maps_unavailable_model_to_503(
    video_store: VideoStore,
) -> None:
    selector = FakeSelector(error=SelectionUnavailableError("checkpoint missing"))
    with TestClient(create_app(video_store, click_selector=selector)) as client:
        response = client.post(
            "/api/select/click",
            json={"videoId": "video-1", "frameIdx": 0, "x": 10, "y": 20},
        )

    assert response.status_code == 503
    assert response.json()["detail"] == "checkpoint missing"

