from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.selection import (
    ClickSelection,
    TextSelectionUnavailableError,
    TextSelector,
    SelectionInputError,
    SelectionUnavailableError,
)
from app.models.locate_engine import LocateCandidate
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


@dataclass
class FakeTextSelector:
    result: list[LocateCandidate] = field(default_factory=list)
    error: Exception | None = None
    calls: list[tuple[str, int, str]] = field(default_factory=list)

    @property
    def availability(self) -> tuple[bool, str]:
        return (self.error is None, "" if self.error is None else str(self.error))

    def select_text(
        self, video_id: str, frame_idx: int, prompt: str
    ) -> list[LocateCandidate]:
        self.calls.append((video_id, frame_idx, prompt))
        if self.error is not None:
            raise self.error
        return self.result


def test_text_selection_route_returns_candidates(video_store: VideoStore) -> None:
    selector = FakeTextSelector(
        result=[LocateCandidate(box=(10, 20, 40, 80), score=0.9)]
    )
    with TestClient(create_app(video_store, text_selector=selector)) as client:
        response = client.post(
            "/api/select/text",
            json={"videoId": "video-1", "frameIdx": 4, "prompt": "white jersey"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "candidates": [{"box": [10, 20, 40, 80], "score": 0.9}]
    }
    assert selector.calls == [("video-1", 4, "white jersey")]


def test_text_selection_returns_501_when_locate_is_unavailable(
    video_store: VideoStore,
) -> None:
    selector = FakeTextSelector(
        error=TextSelectionUnavailableError(
            "LocateAnything requires an NVIDIA CUDA GPU"
        )
    )
    with TestClient(create_app(video_store, text_selector=selector)) as client:
        response = client.post(
            "/api/select/text",
            json={"videoId": "video-1", "frameIdx": 0, "prompt": "player"},
        )

    assert response.status_code == 501
    assert "CUDA" in response.json()["detail"]


class FakeLocateEngine:
    available = True
    unavailable_reason = ""

    def ground_text(self, image: object, prompt: str) -> list[LocateCandidate]:
        assert image.size == (320, 180)
        assert prompt == "white jersey"
        return [LocateCandidate(box=(10, 20, 40, 80), score=0.9)]


def test_text_selection_api_can_run_with_a_weight_free_fake_engine(
    video_store: VideoStore, tiny_video: Path
) -> None:
    record = video_store.register_path(tiny_video)
    selector = TextSelector(
        video_store,
        engine_provider=FakeLocateEngine,
        max_input_dimension=2500,
    )
    with TestClient(create_app(video_store, text_selector=selector)) as client:
        response = client.post(
            "/api/select/text",
            json={
                "videoId": record.video_id,
                "frameIdx": 0,
                "prompt": "white jersey",
            },
        )

    assert response.status_code == 200
    assert response.json()["candidates"] == [
        {"box": [10, 20, 40, 80], "score": 0.9}
    ]


def test_features_route_exposes_text_selection_availability(
    video_store: VideoStore,
) -> None:
    selector = FakeTextSelector(
        error=TextSelectionUnavailableError("CUDA GPU required")
    )
    with TestClient(create_app(video_store, text_selector=selector)) as client:
        response = client.get("/api/features")

    assert response.status_code == 200
    assert response.json() == {
        "textSelection": {"enabled": False, "reason": "CUDA GPU required"}
    }
