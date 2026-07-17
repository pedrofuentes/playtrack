from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


class CropPlanningError(ValueError):
    """Raised when a crop plan cannot be produced from the supplied geometry."""


@dataclass(frozen=True, slots=True)
class SmoothingOptions:
    window_sec: float = 0.8
    dead_zone_px: float = 30.0
    max_velocity: float = 28.0


@dataclass(frozen=True, slots=True)
class CropWindow:
    frame_idx: int
    x: int
    y: int
    width: int
    height: int

    def to_dict(self) -> dict[str, int]:
        return {
            "frameIdx": self.frame_idx,
            "x": self.x,
            "y": self.y,
            "w": self.width,
            "h": self.height,
        }


def fill_missing_centers(
    centers: Sequence[tuple[float, float] | None],
) -> np.ndarray:
    """Interpolate internal gaps and hold the nearest known center at each end."""
    if not centers:
        raise CropPlanningError("Track must contain at least one frame")
    values = np.full((len(centers), 2), np.nan, dtype=np.float64)
    for index, center in enumerate(centers):
        if center is None:
            continue
        x, y = center
        if not np.isfinite(x) or not np.isfinite(y):
            continue
        values[index] = (float(x), float(y))

    known = np.flatnonzero(np.isfinite(values).all(axis=1))
    if known.size == 0:
        raise CropPlanningError("Track must contain at least one known center")
    indices = np.arange(len(centers), dtype=np.float64)
    for axis in range(2):
        values[:, axis] = np.interp(indices, known, values[known, axis])
    return values


def plan_crop_windows(
    centers: Sequence[tuple[float, float] | None],
    *,
    source_width: int,
    source_height: int,
    output_width: int,
    output_height: int,
    fps: float,
    zoom: float = 1.0,
    smoothing: SmoothingOptions | None = None,
) -> list[CropWindow]:
    """Build deterministic source-space crop windows for each tracked frame."""
    if min(source_width, source_height, output_width, output_height) <= 0:
        raise CropPlanningError("Source and output dimensions must be positive")
    if source_width < 2 or source_height < 2:
        raise CropPlanningError("Source dimensions must support even crop windows")
    if not np.isfinite(fps) or fps <= 0:
        raise CropPlanningError("Frame rate must be positive")
    options = smoothing or SmoothingOptions()
    if options.window_sec < 0 or options.dead_zone_px < 0:
        raise CropPlanningError("Smoothing window and dead zone cannot be negative")
    if options.max_velocity <= 0:
        raise CropPlanningError("Maximum velocity must be positive")

    effective_zoom = float(np.clip(zoom, 1.0, 4.0))
    scale = min(source_width / output_width, source_height / output_height)
    crop_width = _even_floor(min(source_width, output_width * scale / effective_zoom))
    crop_height = _even_floor(
        min(source_height, output_height * scale / effective_zoom)
    )
    if crop_width < 2 or crop_height < 2:
        raise CropPlanningError("Requested zoom produces an empty crop window")

    trajectory = fill_missing_centers(centers)
    trajectory = _apply_dead_zone(trajectory, options.dead_zone_px)
    trajectory = _centered_moving_average(trajectory, options.window_sec, fps)
    trajectory = _clamp_velocity(trajectory, options.max_velocity)

    return [
        _window_for_center(
            index,
            center,
            source_width=source_width,
            source_height=source_height,
            crop_width=crop_width,
            crop_height=crop_height,
        )
        for index, center in enumerate(trajectory)
    ]


def _apply_dead_zone(trajectory: np.ndarray, threshold: float) -> np.ndarray:
    if threshold <= 0 or len(trajectory) <= 1:
        return trajectory.copy()
    filtered = trajectory.copy()
    accepted = filtered[0].copy()
    for index in range(1, len(filtered)):
        candidate = trajectory[index]
        if float(np.linalg.norm(candidate - accepted)) < threshold:
            filtered[index] = accepted
        else:
            accepted = candidate.copy()
            filtered[index] = accepted
    return filtered


def _centered_moving_average(
    trajectory: np.ndarray, window_sec: float, fps: float
) -> np.ndarray:
    frame_window = max(1, int(round(window_sec * fps)))
    if frame_window <= 1 or len(trajectory) <= 1:
        return trajectory.copy()
    if frame_window % 2 == 0:
        frame_window += 1
    radius = frame_window // 2
    padded = np.pad(trajectory, ((radius, radius), (0, 0)), mode="edge")
    kernel = np.full(frame_window, 1.0 / frame_window, dtype=np.float64)
    return np.column_stack(
        [np.convolve(padded[:, axis], kernel, mode="valid") for axis in range(2)]
    )


def _clamp_velocity(trajectory: np.ndarray, maximum: float) -> np.ndarray:
    if len(trajectory) <= 1:
        return trajectory.copy()
    clamped = trajectory.copy()
    for index in range(1, len(clamped)):
        delta = trajectory[index] - clamped[index - 1]
        distance = float(np.linalg.norm(delta))
        if distance > maximum:
            delta *= maximum / distance
        clamped[index] = clamped[index - 1] + delta
    return clamped


def _window_for_center(
    frame_idx: int,
    center: np.ndarray,
    *,
    source_width: int,
    source_height: int,
    crop_width: int,
    crop_height: int,
) -> CropWindow:
    max_x = source_width - crop_width
    max_y = source_height - crop_height
    x = _clamped_even(float(center[0]) - crop_width / 2, max_x)
    y = _clamped_even(float(center[1]) - crop_height / 2, max_y)
    return CropWindow(frame_idx, x, y, crop_width, crop_height)


def _even_floor(value: float) -> int:
    return int(np.floor(value / 2.0)) * 2


def _clamped_even(value: float, maximum: int) -> int:
    maximum_even = maximum - maximum % 2
    rounded = int(round(value / 2.0)) * 2
    return min(max(rounded, 0), maximum_even)
