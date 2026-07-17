from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from app.models.locate_engine import LocateCandidate
from app.tracking import (
    ConsecutiveLossTrigger,
    LossDetector,
    TrackFrame,
    VideoTracker,
    merge_track_segments,
)
from app.videos import ExtractedSourceCrop, TrackingFrameSequence, VideoMetadata


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


def test_rescue_trigger_reports_first_lost_frame_and_resets_on_recovery() -> None:
    trigger = ConsecutiveLossTrigger(rescue_after=3)

    assert trigger.observe(10, lost=True) is None
    assert trigger.observe(11, lost=True) is None
    assert trigger.observe(12, lost=True) == 10
    assert trigger.observe(13, lost=True) is None
    assert trigger.observe(14, lost=False) is None
    assert trigger.observe(15, lost=True) is None
    assert trigger.observe(16, lost=True) is None
    assert trigger.observe(17, lost=True) == 15


def test_rescue_segment_replaces_lost_frames_in_the_original_segment() -> None:
    lost = TrackFrame(4, box=None, center=None, lost=True)
    recovered = TrackFrame(4, box=(20, 30, 40, 60), center=(30, 45), lost=False)
    tail = TrackFrame(5, box=(22, 30, 42, 60), center=(32, 45), lost=False)

    merged = merge_track_segments([lost], [recovered, tail])

    assert merged == [recovered, tail]


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


@dataclass
class RescueStore(FakeStore):
    image_path: Path

    def extract_source_crop(
        self,
        video_id: str,
        *,
        frame_idx: int,
        x: int,
        y: int,
        width: int,
        height: int,
    ) -> ExtractedSourceCrop:
        assert video_id == "video-1"
        from PIL import Image

        output_path = self.image_path.with_name(
            f"frame-{frame_idx}-{x}-{y}-{width}-{height}.png"
        )
        with Image.open(self.image_path) as image:
            image.crop((x, y, x + width, y + height)).save(output_path)
        return ExtractedSourceCrop(
            path=output_path,
            x=x,
            y=y,
            width=width,
            height=height,
        )


class RescueVideoEngine:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls: list[tuple[int, tuple[int, int, int, int], bool]] = []

    def propagate(
        self,
        frame_directory: Path,
        anchor_frame_idx: int,
        box: tuple[int, int, int, int],
        *,
        reverse: bool,
    ) -> object:
        self.events.append(f"sam-propagate-{anchor_frame_idx}")
        self.calls.append((anchor_frame_idx, box, reverse))
        if anchor_frame_idx == 0:
            yield 0, rectangle_mask(x1=10, y1=10, x2=20, y2=20)
            yield 1, np.zeros((50, 100), dtype=bool)
            yield 2, np.zeros((50, 100), dtype=bool)
            raise AssertionError("the lost segment should be interrupted for rescue")
        for frame_idx in range(anchor_frame_idx, 5):
            yield frame_idx, rectangle_mask(x1=30, y1=10, x2=40, y2=20)

    def unload(self) -> None:
        self.events.append("sam-unload")


class FakeRescueEngine:
    available = True
    unavailable_reason = ""

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls: list[tuple[tuple[int, int], tuple[int, int]]] = []

    def detect_visual_prompt(
        self, image: object, *, visual_prompt: object
    ) -> list[LocateCandidate]:
        self.events.append("locate-detect")
        self.calls.append((image.size, visual_prompt.size))
        return [LocateCandidate(box=(60, 20, 80, 40), score=0.9)]

    def unload(self) -> None:
        self.events.append("locate-unload")


def test_tracker_reseeds_from_first_lost_frame_and_swaps_model_residency(
    tmp_path: Path,
) -> None:
    from PIL import Image

    image_path = tmp_path / "source.png"
    Image.new("RGB", (200, 100), "black").save(image_path)
    sequence = TrackingFrameSequence(
        path=Path("/tmp/tracking-frames"),
        width=100,
        height=50,
        frame_count=5,
        scale_x=0.5,
        scale_y=0.5,
    )
    events: list[str] = []
    sam = RescueVideoEngine(events)
    locate = FakeRescueEngine(events)
    tracker = VideoTracker(
        RescueStore(sequence, image_path),
        engine_provider=lambda: sam,
        rescue_engine_provider=lambda: locate,
        rescue_after=2,
        rescue_min_score=0.5,
        rescue_max_input_dimension=2500,
    )

    result = tracker.track("video-1", frame_idx=0, box=(20, 20, 40, 40))

    assert sam.calls == [
        (0, (10, 10, 20, 20), False),
        (1, (30, 10, 40, 20), False),
    ]
    assert locate.calls == [((200, 100), (20, 20))]
    assert events == [
        "locate-unload",
        "sam-propagate-0",
        "sam-unload",
        "locate-detect",
        "locate-unload",
        "sam-propagate-1",
    ]
    assert [frame.lost for frame in result] == [False, False, False, False, False]
    assert result[1].box == (60, 20, 80, 40)
