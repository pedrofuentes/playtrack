from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from app.tracking import LossDetector, TrackFrame, VideoTracker
from app.videos import TrackingFrameSequence, VideoMetadata


def rectangle_mask(
    *, width: int = 100, height: int = 50, x1: int, y1: int, x2: int, y2: int
) -> np.ndarray:
    mask = np.zeros((height, width), dtype=bool)
    mask[y1:y2, x1:x2] = True
    return mask


def test_loss_detector_marks_empty_and_tiny_masks_lost() -> None:
    detector = LossDetector(window_size=5, loss_ratio=0.2)

    assert detector.observe(100) is False
    assert detector.observe(120) is False
    assert detector.observe(19) is True
    assert detector.observe(22) is False
    assert detector.observe(0) is True


def test_lost_areas_do_not_lower_the_rolling_baseline() -> None:
    detector = LossDetector(window_size=3, loss_ratio=0.2)

    assert [detector.observe(area) for area in (100, 100, 1, 1, 19)] == [
        False,
        False,
        True,
        True,
        True,
    ]


@dataclass
class FakeStore:
    sequence: TrackingFrameSequence

    def get(self, video_id: str) -> object:
        assert video_id == "video-1"
        return SimpleNamespace(
            metadata=VideoMetadata(
                width=200,
                height=100,
                fps=30.0,
                nb_frames=5,
                duration=5 / 30,
            )
        )

    def prepare_tracking_frames(
        self, video_id: str, *, frame_limit: int | None = None
    ) -> TrackingFrameSequence:
        assert video_id == "video-1"
        assert frame_limit is None
        return self.sequence


class FakeVideoEngine:
    def __init__(self) -> None:
        self.calls: list[tuple[int, tuple[int, int, int, int], bool]] = []

    def propagate(
        self,
        frame_directory: Path,
        anchor_frame_idx: int,
        box: tuple[int, int, int, int],
        *,
        reverse: bool,
    ) -> object:
        assert frame_directory == Path("/tmp/tracking-frames")
        self.calls.append((anchor_frame_idx, box, reverse))
        frame_indices = (2, 1, 0) if reverse else (2, 3, 4)
        for frame_idx in frame_indices:
            yield frame_idx, rectangle_mask(x1=10, y1=10, x2=20, y2=20)


def test_tracker_runs_both_directions_and_merges_source_space_results() -> None:
    sequence = TrackingFrameSequence(
        path=Path("/tmp/tracking-frames"),
        width=100,
        height=50,
        frame_count=5,
        scale_x=0.5,
        scale_y=0.5,
    )
    engine = FakeVideoEngine()
    updates: list[tuple[float, str, TrackFrame]] = []
    tracker = VideoTracker(FakeStore(sequence), engine_provider=lambda: engine)

    result = tracker.track(
        "video-1",
        frame_idx=2,
        box=(20, 20, 40, 40),
        on_update=lambda progress, message, frame: updates.append(
            (progress, message, frame)
        ),
    )

    assert engine.calls == [
        (2, (10, 10, 20, 20), False),
        (2, (10, 10, 20, 20), True),
    ]
    assert [frame.frame_idx for frame in result] == [0, 1, 2, 3, 4]
    assert all(frame.box == (20, 20, 40, 40) for frame in result)
    assert all(frame.center == (29.0, 29.0) for frame in result)
    assert all(frame.lost is False for frame in result)
    assert [update[2].frame_idx for update in updates] == [2, 3, 4, 1, 0]
    assert updates[-1][0] == 1.0
    assert "backward" in updates[-1][1].lower()


class TinyMaskEngine(FakeVideoEngine):
    def propagate(
        self,
        frame_directory: Path,
        anchor_frame_idx: int,
        box: tuple[int, int, int, int],
        *,
        reverse: bool,
    ) -> object:
        self.calls.append((anchor_frame_idx, box, reverse))
        if reverse:
            yield 2, rectangle_mask(x1=10, y1=10, x2=20, y2=20)
            yield 1, rectangle_mask(x1=10, y1=10, x2=11, y2=11)
            yield 0, np.zeros((50, 100), dtype=bool)
        else:
            yield 2, rectangle_mask(x1=10, y1=10, x2=20, y2=20)
            yield 3, rectangle_mask(x1=10, y1=10, x2=11, y2=11)
            yield 4, np.zeros((50, 100), dtype=bool)


def test_tracker_emits_null_geometry_for_lost_frames() -> None:
    sequence = TrackingFrameSequence(
        path=Path("/tmp/tracking-frames"),
        width=100,
        height=50,
        frame_count=5,
        scale_x=0.5,
        scale_y=0.5,
    )
    tracker = VideoTracker(
        FakeStore(sequence),
        engine_provider=TinyMaskEngine,
        loss_window_size=5,
    )

    result = tracker.track("video-1", frame_idx=2, box=(20, 20, 40, 40))

    assert [frame.lost for frame in result] == [True, True, False, True, True]
    assert all(
        frame.box is None and frame.center is None
        for frame in result
        if frame.lost
    )
