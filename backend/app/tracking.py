from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from .models.locate_engine import LocateAnythingError, LocateCandidate
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


class RescueEngine(Protocol):
    available: bool

    def detect_visual_prompt(
        self, image: object, *, visual_prompt: object
    ) -> list[LocateCandidate]: ...

    def unload(self) -> None: ...


TrackUpdate = Callable[[float, str, TrackFrame], None]


def persist_completed_track(
    library: Any,
    *,
    video_id: str,
    job_id: str,
    anchor_frame_idx: int,
    box: tuple[int, int, int, int],
    track: Sequence[TrackFrame],
) -> None:
    """Write a completed tracker result through to the durable library."""
    library.save_track(video_id, job_id, anchor_frame_idx, box, track)


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


class ConsecutiveLossTrigger:
    """Emit the first lost frame once per consecutive-loss run."""

    def __init__(self, *, rescue_after: int = 15) -> None:
        if rescue_after <= 0:
            raise ValueError("rescue_after must be positive")
        self.rescue_after = rescue_after
        self._first_lost: int | None = None
        self._count = 0
        self._fired = False

    def observe(self, frame_idx: int, *, lost: bool) -> int | None:
        if not lost:
            self._first_lost = None
            self._count = 0
            self._fired = False
            return None
        if self._count == 0:
            self._first_lost = frame_idx
        self._count += 1
        if self._count >= self.rescue_after and not self._fired:
            self._fired = True
            return self._first_lost
        return None


def merge_track_segments(*segments: Sequence[TrackFrame]) -> list[TrackFrame]:
    """Merge chronological track segments, with later rescue data taking precedence."""
    merged: dict[int, TrackFrame] = {}
    for segment in segments:
        for frame in segment:
            merged[frame.frame_idx] = frame
    return [merged[index] for index in sorted(merged)]


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
        rescue_engine_provider: Callable[[], RescueEngine] | None = None,
        rescue_after: int = 15,
        rescue_min_score: float = 0.5,
        rescue_max_input_dimension: int = 2500,
    ) -> None:
        self.video_store = video_store
        self.engine_provider = engine_provider
        self.loss_window_size = loss_window_size
        self.loss_ratio = loss_ratio
        self.frame_limit = frame_limit
        self.rescue_engine_provider = rescue_engine_provider
        self.rescue_after = rescue_after
        self.rescue_min_score = rescue_min_score
        self.rescue_max_input_dimension = rescue_max_input_dimension
        if rescue_after <= 0:
            raise ValueError("rescue_after must be positive")
        if not 0 <= rescue_min_score <= 1:
            raise ValueError("rescue_min_score must be between zero and one")
        if rescue_max_input_dimension <= 0:
            raise ValueError("rescue_max_input_dimension must be positive")

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
        rescue_engine, visual_prompt = self._prepare_rescue(
            video_id, frame_idx, box
        )
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
            video_id=video_id,
            rescue_engine=rescue_engine,
            visual_prompt=visual_prompt,
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
                video_id=video_id,
                rescue_engine=rescue_engine,
                visual_prompt=visual_prompt,
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
        video_id: str,
        rescue_engine: RescueEngine | None,
        visual_prompt: object | None,
    ) -> None:
        direction = "backward" if reverse else "forward"
        current_anchor = frame_idx
        current_box = tracking_box
        attempted_rescues: set[int] = set()
        while True:
            detector = LossDetector(
                window_size=self.loss_window_size,
                loss_ratio=self.loss_ratio,
            )
            trigger = ConsecutiveLossTrigger(rescue_after=self.rescue_after)
            last_good = (current_anchor, current_box)
            observations = iter(
                engine.propagate(
                    sequence.path,
                    current_anchor,
                    current_box,
                    reverse=reverse,
                )
            )
            restart: tuple[int, tuple[int, int, int, int]] | None = None
            for observed_idx, mask in observations:
                if observed_idx < 0 or observed_idx >= total_frames:
                    continue
                frame = _frame_from_mask(observed_idx, mask, sequence, detector)
                if not (
                    observed_idx == frame_idx
                    and observed_idx in merged
                    and current_anchor == frame_idx
                ):
                    merged[observed_idx] = frame
                    if on_update is not None:
                        on_update(
                            len(merged) / total_frames,
                            f"Tracking {direction}",
                            frame,
                        )
                if not frame.lost and frame.box is not None:
                    last_good = (
                        observed_idx,
                        _scale_box_to_tracking(frame.box, sequence),
                    )
                first_lost = trigger.observe(observed_idx, lost=frame.lost)
                if (
                    first_lost is None
                    or first_lost in attempted_rescues
                    or rescue_engine is None
                    or visual_prompt is None
                ):
                    continue

                attempted_rescues.add(first_lost)
                close = getattr(observations, "close", None)
                if callable(close):
                    close()
                unload_sam = getattr(engine, "unload", None)
                if callable(unload_sam):
                    unload_sam()
                try:
                    candidate = self._rescue_candidate(
                        rescue_engine,
                        video_id=video_id,
                        frame_idx=first_lost,
                        visual_prompt=visual_prompt,
                    )
                finally:
                    # SAM must never restart while LocateAnything occupies VRAM.
                    rescue_engine.unload()
                if candidate is not None:
                    restart = (
                        first_lost,
                        _scale_box_to_tracking(candidate.box, sequence),
                    )
                else:
                    restart = last_good
                break
            if restart is None:
                return
            current_anchor, current_box = restart

    def _prepare_rescue(
        self,
        video_id: str,
        frame_idx: int,
        box: tuple[int, int, int, int],
    ) -> tuple[RescueEngine | None, object | None]:
        if self.rescue_engine_provider is None:
            return None, None
        engine = self.rescue_engine_provider()
        if not engine.available:
            return None, None
        x1, y1, x2, y2 = box
        extracted = self.video_store.extract_source_crop(
            video_id,
            frame_idx=frame_idx,
            x=x1,
            y=y1,
            width=x2 - x1,
            height=y2 - y1,
        )
        visual_prompt = _load_rgb_image(extracted.path)
        # A preceding text selection may have loaded LocateAnything. Release it
        # before the first SAM propagation begins.
        engine.unload()
        return engine, visual_prompt

    def _rescue_candidate(
        self,
        engine: RescueEngine,
        *,
        video_id: str,
        frame_idx: int,
        visual_prompt: object,
    ) -> LocateCandidate | None:
        record = self.video_store.get(video_id)
        extracted = self.video_store.extract_source_crop(
            video_id,
            frame_idx=frame_idx,
            x=0,
            y=0,
            width=record.metadata.width,
            height=record.metadata.height,
        )
        image = _load_rgb_image(extracted.path)
        scale = min(
            1.0,
            self.rescue_max_input_dimension / max(image.size),
        )
        if scale < 1.0:
            from PIL import Image

            model_image = image.resize(
                (round(image.size[0] * scale), round(image.size[1] * scale)),
                Image.Resampling.LANCZOS,
            )
        else:
            model_image = image
        try:
            candidates = engine.detect_visual_prompt(
                model_image,
                visual_prompt=visual_prompt,
            )
        except LocateAnythingError:
            return None
        confident = [
            candidate
            for candidate in candidates
            if candidate.score >= self.rescue_min_score
        ]
        if not confident:
            return None
        best = max(confident, key=lambda item: item.score)
        inverse = 1.0 / scale
        return LocateCandidate(
            box=tuple(round(value * inverse) for value in best.box),
            score=best.score,
        )


def _load_rgb_image(path: Path) -> Any:
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:
        raise TrackingError("Pillow is required for occlusion rescue") from exc
    with Image.open(path) as image:
        return image.convert("RGB")


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
