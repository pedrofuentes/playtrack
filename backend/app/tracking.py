from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Protocol, Sequence

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


PropagationDirection = Literal["forward", "backward"]


class VideoPropagationEngine(Protocol):
    def propagate_directions(
        self,
        frame_directory: Path,
        anchor_frame_idx: int,
        box: tuple[int, int, int, int],
        *,
        directions: tuple[PropagationDirection, ...],
    ) -> object: ...


TrackUpdate = Callable[[float, str, TrackFrame], None]


def persist_completed_track(
    library: Any,
    *,
    video_id: str,
    job_id: str,
    anchor_frame_idx: int,
    box: tuple[int, int, int, int],
    track: Sequence[TrackFrame],
    start_frame_idx: int | None = None,
    end_frame_exclusive: int | None = None,
    name: str | None = None,
) -> None:
    """Write a completed tracker result through to the durable library."""
    library.save_track(
        video_id,
        job_id,
        anchor_frame_idx,
        box,
        track,
        start_frame_idx=start_frame_idx,
        end_frame_exclusive=end_frame_exclusive,
        name=name,
    )


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
        *,
        start_frame_idx: int = 0,
        end_frame_exclusive: int | None = None,
        on_update: TrackUpdate | None = None,
    ) -> list[TrackFrame]:
        record = self.video_store.get(video_id)
        source_frame_count = record.metadata.nb_frames
        requested_end = (
            source_frame_count
            if end_frame_exclusive is None
            else end_frame_exclusive
        )
        if not 0 <= start_frame_idx < requested_end <= source_frame_count:
            raise InvalidFrameError(
                "Tracking range must contain at least one source frame and stay inside the video"
            )
        effective_end = requested_end
        if self.frame_limit is not None:
            effective_end = min(effective_end, start_frame_idx + self.frame_limit)
        if frame_idx < start_frame_idx or frame_idx >= effective_end:
            raise InvalidFrameError(
                f"Anchor frame must be between {start_frame_idx} and {effective_end - 1}"
            )
        _validate_source_box(
            box,
            source_width=record.metadata.width,
            source_height=record.metadata.height,
        )

        sequence = self.video_store.prepare_tracking_frames(
            video_id,
            start_frame_idx=start_frame_idx,
            end_frame_exclusive=requested_end,
            frame_limit=self.frame_limit,
        )
        local_anchor = frame_idx - sequence.start_frame_idx
        if local_anchor < 0 or local_anchor >= sequence.frame_count:
            raise InvalidFrameError("Anchor frame is not present in tracking cache")
        tracking_box = _scale_box_to_tracking(box, sequence)
        engine = self.engine_provider()
        merged: dict[int, TrackFrame] = {}

        directions: tuple[PropagationDirection, ...] = ("forward",)
        if local_anchor > 0:
            directions = ("forward", "backward")
        self._run_directions(
            engine,
            sequence,
            local_anchor,
            tracking_box,
            directions=directions,
            merged=merged,
            total_frames=sequence.frame_count,
            on_update=on_update,
            source_anchor_frame_idx=frame_idx,
        )

        for missing_idx in range(
            sequence.start_frame_idx,
            sequence.start_frame_idx + sequence.frame_count,
        ):
            merged.setdefault(
                missing_idx,
                TrackFrame(missing_idx, box=None, center=None, lost=True),
            )
        return [merged[index] for index in sorted(merged)]

    def _run_directions(
        self,
        engine: VideoPropagationEngine,
        sequence: TrackingFrameSequence,
        local_anchor_frame_idx: int,
        tracking_box: tuple[int, int, int, int],
        *,
        directions: tuple[PropagationDirection, ...],
        merged: dict[int, TrackFrame],
        total_frames: int,
        on_update: TrackUpdate | None,
        source_anchor_frame_idx: int,
    ) -> None:
        detectors = {
            direction: LossDetector(
                window_size=self.loss_window_size,
                loss_ratio=self.loss_ratio,
            )
            for direction in directions
        }
        propagation = engine.propagate_directions(
            sequence.path,
            local_anchor_frame_idx,
            tracking_box,
            directions=directions,
        )
        try:
            for direction, observed_local_idx, mask in propagation:
                if observed_local_idx < 0 or observed_local_idx >= total_frames:
                    continue
                observed_source_idx = sequence.start_frame_idx + observed_local_idx
                frame = _frame_from_mask(
                    observed_source_idx,
                    mask,
                    sequence,
                    detectors[direction],
                )
                if (
                    observed_source_idx == source_anchor_frame_idx
                    and observed_source_idx in merged
                ):
                    continue
                merged[observed_source_idx] = frame
                if on_update is not None:
                    on_update(
                        len(merged) / total_frames,
                        f"Tracking {direction}",
                        frame,
                    )
        finally:
            close = getattr(propagation, "close", None)
            if close is not None:
                close()


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
