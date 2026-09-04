from __future__ import annotations

from dataclasses import dataclass
from inspect import signature
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from app.tracking import (
    LossDetector,
    TrackFrame,
    VideoTracker,
)
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


def test_tracker_constructor_contains_only_sam_propagation_options() -> None:
    assert tuple(signature(VideoTracker).parameters) == (
        "video_store",
        "engine_provider",
        "loss_window_size",
        "loss_ratio",
        "frame_limit",
    )


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
        self,
        video_id: str,
        *,
        start_frame_idx: int = 0,
        end_frame_exclusive: int | None = None,
        frame_limit: int | None = None,
    ) -> TrackingFrameSequence:
        assert video_id == "video-1"
        assert start_frame_idx == 0
        assert end_frame_exclusive == 5
        assert frame_limit is None
        return self.sequence


class FakeVideoEngine:
    def __init__(self) -> None:
        self.calls: list[
            tuple[int, tuple[int, int, int, int], tuple[str, ...]]
        ] = []

    def propagate_directions(
        self,
        frame_directory: Path,
        anchor_frame_idx: int,
        box: tuple[int, int, int, int],
        *,
        directions: tuple[str, ...],
    ) -> object:
        assert frame_directory == Path("/tmp/tracking-frames")
        self.calls.append((anchor_frame_idx, box, directions))
        for direction in directions:
            frame_indices = (2, 1, 0) if direction == "backward" else (2, 3, 4)
            for frame_idx in frame_indices:
                yield direction, frame_idx, rectangle_mask(
                    x1=10, y1=10, x2=20, y2=20
                )


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
        (2, (10, 10, 20, 20), ("forward", "backward")),
    ]
    assert [frame.frame_idx for frame in result] == [0, 1, 2, 3, 4]
    assert all(frame.box == (20, 20, 40, 40) for frame in result)
    assert all(frame.center == (29.0, 29.0) for frame in result)
    assert all(frame.lost is False for frame in result)
    assert [update[2].frame_idx for update in updates] == [2, 3, 4, 1, 0]
    assert updates[-1][0] == 1.0
    assert "backward" in updates[-1][1].lower()


@dataclass
class RangeStore:
    sequence: TrackingFrameSequence
    extracted_frame_indices: list[int]

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
        self,
        video_id: str,
        *,
        start_frame_idx: int = 0,
        end_frame_exclusive: int | None = None,
        frame_limit: int | None = None,
    ) -> TrackingFrameSequence:
        assert video_id == "video-1"
        assert (start_frame_idx, end_frame_exclusive, frame_limit) == (1, 4, None)
        return self.sequence


class RangeVideoEngine:
    def __init__(self) -> None:
        self.calls: list[
            tuple[int, tuple[int, int, int, int], tuple[str, ...]]
        ] = []

    def propagate_directions(
        self,
        frame_directory: Path,
        anchor_frame_idx: int,
        box: tuple[int, int, int, int],
        *,
        directions: tuple[str, ...],
    ) -> object:
        self.calls.append((anchor_frame_idx, box, directions))
        for direction in directions:
            frame_indices = (1, 0) if direction == "backward" else (1, 2)
            for local_frame_idx in frame_indices:
                yield direction, local_frame_idx, rectangle_mask(
                    x1=10, y1=10, x2=20, y2=20
                )


def test_tracker_maps_local_range_frames_to_absolute_source_indices() -> None:
    sequence = TrackingFrameSequence(
        path=Path("/tmp/tracking-frames"),
        width=100,
        height=50,
        frame_count=3,
        scale_x=0.5,
        scale_y=0.5,
        start_frame_idx=1,
    )
    engine = RangeVideoEngine()
    updates: list[tuple[float, str, TrackFrame]] = []
    tracker = VideoTracker(
        RangeStore(sequence, []), engine_provider=lambda: engine
    )

    result = tracker.track(
        "video-1",
        frame_idx=2,
        box=(20, 20, 40, 40),
        start_frame_idx=1,
        end_frame_exclusive=4,
        on_update=lambda progress, message, frame: updates.append(
            (progress, message, frame)
        ),
    )

    assert engine.calls == [
        (1, (10, 10, 20, 20), ("forward", "backward")),
    ]
    assert [frame.frame_idx for frame in result] == [1, 2, 3]
    assert [update[2].frame_idx for update in updates] == [2, 3, 1]
    assert updates[-1][0] == 1.0


class TinyMaskEngine(FakeVideoEngine):
    def propagate_directions(
        self,
        frame_directory: Path,
        anchor_frame_idx: int,
        box: tuple[int, int, int, int],
        *,
        directions: tuple[str, ...],
    ) -> object:
        self.calls.append((anchor_frame_idx, box, directions))
        for direction in directions:
            if direction == "backward":
                yield direction, 2, rectangle_mask(x1=10, y1=10, x2=20, y2=20)
                yield direction, 1, rectangle_mask(x1=10, y1=10, x2=11, y2=11)
                yield direction, 0, np.zeros((50, 100), dtype=bool)
            else:
                yield direction, 2, rectangle_mask(x1=10, y1=10, x2=20, y2=20)
                yield direction, 3, rectangle_mask(x1=10, y1=10, x2=11, y2=11)
                yield direction, 4, np.zeros((50, 100), dtype=bool)


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


class ClosingVideoEngine(FakeVideoEngine):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False

    def propagate_directions(
        self,
        frame_directory: Path,
        anchor_frame_idx: int,
        box: tuple[int, int, int, int],
        *,
        directions: tuple[str, ...],
    ) -> object:
        try:
            yield "forward", anchor_frame_idx, rectangle_mask(
                x1=10, y1=10, x2=20, y2=20
            )
            yield "forward", anchor_frame_idx + 1, rectangle_mask(
                x1=10, y1=10, x2=20, y2=20
            )
        finally:
            self.closed = True


def test_tracker_closes_engine_iterator_when_progress_reporting_stops() -> None:
    sequence = TrackingFrameSequence(
        path=Path("/tmp/tracking-frames"),
        width=100,
        height=50,
        frame_count=5,
        scale_x=0.5,
        scale_y=0.5,
    )
    engine = ClosingVideoEngine()
    tracker = VideoTracker(FakeStore(sequence), engine_provider=lambda: engine)

    def stop_tracking(*_args: object) -> None:
        raise RuntimeError("cancel now")

    with pytest.raises(RuntimeError, match="cancel now"):
        tracker.track(
            "video-1",
            frame_idx=2,
            box=(20, 20, 40, 40),
            on_update=stop_tracking,
        )

    assert engine.closed is True
