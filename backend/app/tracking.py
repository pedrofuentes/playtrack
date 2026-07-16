from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence

from .videos import InvalidFrameError, TrackingFrameSequence, VideoStore


class TrackingError(RuntimeError):
    """Raised when a tracking request cannot be completed."""


@dataclass(frozen=True, slots=True)
class TrackFrame:
    frame_idx: int
    box: tuple[int, int, int, int] | None
    center: tuple[float, float] | None
    lost: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "frameIdx": self.frame_idx,
            "box": self.box,
            "center": self.center,
            "lost": self.lost,
        }


class VideoPropagationEngine(Protocol):
    def propagate(
        self,
        frame_directory: Path,
        anchor_frame_idx: int,
        box: tuple[int, int, int, int],
        *,
        reverse: bool,
    ) -> object: ...


TrackUpdate = Callable[[float, str, TrackFrame], None]


class LossDetector:
    """Detect masks that are empty or below a rolling accepted-area baseline."""

    def __init__(self, *, window_size: int = 15, loss_ratio: float = 0.2) -> None:
        if window_size <= 0:
            raise ValueError("window_size must be positive")
        if not 0 < loss_ratio < 1:
            raise ValueError("loss_ratio must be between zero and one")
        self._areas: deque[int] = deque(maxlen=window_size)
        self.loss_ratio = loss_ratio

    def observe(self, area: int) -> bool:
        if area <= 0:
            return True
        if self._areas:
            baseline = statistics.median(self._areas)
            if area < baseline * self.loss_ratio:
                return True
        self._areas.append(area)
        return False


class VideoTracker:
    """Run SAM 2 from an anchor in both directions and merge source-space results."""

    def __init__(
        self,
        video_store: VideoStore,
        *,
        engine_provider: Callable[[], VideoPropagationEngine],
        loss_window_size: int = 15,
        loss_ratio: float = 0.2,
        frame_limit: int | None = None,
    ) -> None:
        self.video_store = video_store
        self.engine_provider = engine_provider
        self.loss_window_size = loss_window_size
        self.loss_ratio = loss_ratio
        self.frame_limit = frame_limit

    def track(
        self,
        video_id: str,
        frame_idx: int,
        box: tuple[int, int, int, int],
        on_update: TrackUpdate | None = None,
    ) -> list[TrackFrame]:
        record = self.video_store.get(video_id)
        frame_count = record.metadata.nb_frames
        if self.frame_limit is not None:
            frame_count = min(frame_count, self.frame_limit)
        if frame_idx < 0 or frame_idx >= frame_count:
            raise InvalidFrameError(
                f"Frame index must be between 0 and {frame_count - 1}"
            )
        _validate_source_box(
            box,
            source_width=record.metadata.width,
            source_height=record.metadata.height,
        )

        sequence = self.video_store.prepare_tracking_frames(
            video_id, frame_limit=self.frame_limit
        )
        if frame_idx >= sequence.frame_count:
            raise InvalidFrameError("Anchor frame is not present in tracking cache")
        tracking_box = _scale_box_to_tracking(box, sequence)
        engine = self.engine_provider()
        merged: dict[int, TrackFrame] = {}

        self._run_direction(
            engine,
            sequence,
            frame_idx,
            tracking_box,
            reverse=False,
            merged=merged,
            total_frames=frame_count,
            on_update=on_update,
        )
        if frame_idx > 0:
            self._run_direction(
                engine,
                sequence,
                frame_idx,
                tracking_box,
                reverse=True,
                merged=merged,
                total_frames=frame_count,
                on_update=on_update,
            )

        for missing_idx in range(frame_count):
            merged.setdefault(
                missing_idx,
                TrackFrame(missing_idx, box=None, center=None, lost=True),
            )
        return [merged[index] for index in sorted(merged)]

    def _run_direction(
        self,
        engine: VideoPropagationEngine,
        sequence: TrackingFrameSequence,
        frame_idx: int,
        tracking_box: tuple[int, int, int, int],
        *,
        reverse: bool,
        merged: dict[int, TrackFrame],
        total_frames: int,
        on_update: TrackUpdate | None,
    ) -> None:
        detector = LossDetector(
            window_size=self.loss_window_size,
            loss_ratio=self.loss_ratio,
        )
        direction = "backward" if reverse else "forward"
        observations = engine.propagate(
            sequence.path,
            frame_idx,
            tracking_box,
            reverse=reverse,
        )
        for observed_idx, mask in observations:
            if observed_idx < 0 or observed_idx >= total_frames:
                continue
            frame = _frame_from_mask(observed_idx, mask, sequence, detector)
            if observed_idx == frame_idx and observed_idx in merged:
                continue
            merged[observed_idx] = frame
            if on_update is not None:
                on_update(
                    len(merged) / total_frames,
                    f"Tracking {direction}",
                    frame,
                )


def _frame_from_mask(
    frame_idx: int,
    mask: object,
    sequence: TrackingFrameSequence,
    detector: LossDetector,
) -> TrackFrame:
    try:
        import numpy as np
    except ModuleNotFoundError as exc:
        raise TrackingError("NumPy is required for video tracking") from exc

    array = np.asarray(mask, dtype=bool).squeeze()
    if array.ndim != 2:
        raise TrackingError("SAM 2 returned a video mask with invalid dimensions")
    ys, xs = np.nonzero(array)
    area = int(xs.size)
    if detector.observe(area):
        return TrackFrame(frame_idx, box=None, center=None, lost=True)

    source_x1 = max(0, math.floor(int(xs.min()) / sequence.scale_x))
    source_y1 = max(0, math.floor(int(ys.min()) / sequence.scale_y))
    source_x2 = min(
        round(sequence.width / sequence.scale_x),
        math.ceil((int(xs.max()) + 1) / sequence.scale_x),
    )
    source_y2 = min(
        round(sequence.height / sequence.scale_y),
        math.ceil((int(ys.max()) + 1) / sequence.scale_y),
    )
    return TrackFrame(
        frame_idx=frame_idx,
        box=(source_x1, source_y1, source_x2, source_y2),
        center=(float(xs.mean() / sequence.scale_x), float(ys.mean() / sequence.scale_y)),
        lost=False,
    )


def _scale_box_to_tracking(
    box: tuple[int, int, int, int], sequence: TrackingFrameSequence
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    return (
        max(0, min(sequence.width - 1, math.floor(x1 * sequence.scale_x))),
        max(0, min(sequence.height - 1, math.floor(y1 * sequence.scale_y))),
        max(1, min(sequence.width, math.ceil(x2 * sequence.scale_x))),
        max(1, min(sequence.height, math.ceil(y2 * sequence.scale_y))),
    )


def _validate_source_box(
    box: Sequence[int], *, source_width: int, source_height: int
) -> None:
    if len(box) != 4:
        raise TrackingError("Track box must contain four coordinates")
    x1, y1, x2, y2 = box
    if not (0 <= x1 < x2 <= source_width and 0 <= y1 < y2 <= source_height):
        raise TrackingError("Track box must be inside the source frame")
