from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


class CropPlanningError(ValueError):
    """Raised when a crop plan cannot be produced from the supplied geometry."""


@dataclass(frozen=True, slots=True)
class SmoothingOptions:
    responsiveness: float | None = None
    max_acceleration: float = 3.0
    # Legacy request fields remain accepted. They no longer affect planning.
    window_sec: float | None = None
    dead_zone_px: float = 30.0
    max_velocity: float = 28.0

    @property
    def tau(self) -> float:
        return self.responsiveness if self.responsiveness is not None else (self.window_sec if self.window_sec is not None else 0.5)


@dataclass(frozen=True, slots=True)
class CropWindow:
    frame_idx: int
    x: int
    y: int
    width: int
    height: int
    cx: float | None = None
    cy: float | None = None

    def __post_init__(self) -> None:
        if self.cx is None:
            object.__setattr__(self, "cx", self.x + self.width / 2)
        if self.cy is None:
            object.__setattr__(self, "cy", self.y + self.height / 2)

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
    boxes: Sequence[tuple[float, float, float, float] | None] | None = None,
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
    if options.tau < 0 or options.max_acceleration <= 0:
        raise CropPlanningError("Smoothing responsiveness and acceleration must be positive")

    if boxes is not None and len(boxes) != len(centers):
        raise CropPlanningError("Track boxes must align with track centers")

    effective_zoom = float(np.clip(zoom, 1.0, 4.0))
    scale = min(source_width / output_width, source_height / output_height)
    maximum_crop_width = _even_floor(min(source_width, output_width * scale))
    maximum_crop_height = _even_floor(min(source_height, output_height * scale))
    crop_width = _even_floor(maximum_crop_width / effective_zoom)
    crop_height = _even_floor(
        min(source_height, output_height * scale / effective_zoom)
    )
    if crop_width < 2 or crop_height < 2:
        raise CropPlanningError("Requested zoom produces an empty crop window")

    trajectory = fill_missing_centers(centers)
    trajectory = _critically_damped_spring(trajectory, options.tau, fps)
    trajectory = _clamp_acceleration(trajectory, options.max_acceleration)

    if boxes is None:
        sizes = [(crop_width, crop_height)] * len(trajectory)
        camera_centers = trajectory
    else:
        sizes, camera_centers = _adaptive_geometry(
            trajectory,
            boxes,
            target_width=crop_width,
            target_height=crop_height,
            maximum_width=maximum_crop_width,
            maximum_height=maximum_crop_height,
            fps=fps,
        )

    return [
        _window_for_center(
            index,
            center,
            source_width=source_width,
            source_height=source_height,
            crop_width=sizes[index][0],
            crop_height=sizes[index][1],
        )
        for index, center in enumerate(camera_centers)
    ]


def _adaptive_geometry(
    trajectory: np.ndarray,
    boxes: Sequence[tuple[float, float, float, float] | None],
    *,
    target_width: int,
    target_height: int,
    maximum_width: int,
    maximum_height: int,
    fps: float,
) -> tuple[list[tuple[int, int]], np.ndarray]:
    safe_fraction = 0.8
    return_tau = 0.75
    maximum_factor = min(
        maximum_width / target_width,
        maximum_height / target_height,
    )
    return_alpha = 1.0 - np.exp(-1.0 / (fps * return_tau))
    current_factor = 1.0
    sizes: list[tuple[int, int]] = []
    camera_centers = trajectory.copy()

    for index, raw_box in enumerate(boxes):
        if raw_box is not None:
            x1, y1, x2, y2 = (float(value) for value in raw_box)
            center = camera_centers[index]
            horizontal_extent = max(center[0] - x1, x2 - center[0])
            vertical_extent = max(center[1] - y1, y2 - center[1])
            required_factor = max(
                1.0,
                2.0 * horizontal_extent / (target_width * safe_fraction),
                2.0 * vertical_extent / (target_height * safe_fraction),
            )
            required_factor = min(required_factor, maximum_factor)
            if required_factor >= current_factor:
                current_factor = required_factor
            else:
                current_factor += (required_factor - current_factor) * return_alpha

        width = min(maximum_width, _even_ceil(target_width * current_factor))
        height = min(maximum_height, _even_ceil(target_height * current_factor))
        sizes.append((width, height))

        if raw_box is not None:
            camera_centers[index] = _contain_box(
                camera_centers[index], raw_box, width, height, safe_fraction
            )

    return sizes, camera_centers


def _contain_box(
    center: np.ndarray,
    box: tuple[float, float, float, float],
    width: int,
    height: int,
    safe_fraction: float,
) -> np.ndarray:
    corrected = center.copy()
    for axis, (lower_edge, upper_edge, size) in enumerate(
        ((box[0], box[2], width), (box[1], box[3], height))
    ):
        safe_half = size * safe_fraction / 2.0
        minimum = upper_edge - safe_half
        maximum = lower_edge + safe_half
        if minimum > maximum:
            minimum = upper_edge - size / 2.0
            maximum = lower_edge + size / 2.0
        corrected[axis] = np.clip(corrected[axis], minimum, maximum)
    return corrected


def _critically_damped_spring(trajectory: np.ndarray, tau: float, fps: float) -> np.ndarray:
    if tau <= 0 or len(trajectory) <= 1:
        return trajectory.copy()
    dt = 1.0 / fps
    omega = 2.0 / tau
    filtered = np.empty_like(trajectory)
    filtered[0] = trajectory[0]
    velocity = np.zeros(2, dtype=np.float64)
    for index in range(1, len(trajectory)):
        acceleration = omega * omega * (trajectory[index] - filtered[index - 1]) - 2 * omega * velocity
        velocity = velocity + acceleration * dt
        filtered[index] = filtered[index - 1] + velocity * dt
    return filtered


def _clamp_acceleration(trajectory: np.ndarray, maximum: float) -> np.ndarray:
    if len(trajectory) <= 1:
        return trajectory.copy()
    clamped = np.empty_like(trajectory)
    clamped[0] = trajectory[0]
    velocity = np.zeros(2, dtype=np.float64)
    for index in range(1, len(clamped)):
        delta = trajectory[index] - clamped[index - 1]
        acceleration = delta - velocity
        distance = float(np.linalg.norm(acceleration))
        if distance > maximum:
            acceleration *= maximum / distance
        velocity = velocity + acceleration
        clamped[index] = clamped[index - 1] + velocity
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
    cx = float(np.clip(center[0], crop_width / 2, source_width - crop_width / 2))
    cy = float(np.clip(center[1], crop_height / 2, source_height - crop_height / 2))
    x = _clamped_even(cx - crop_width / 2, max_x)
    y = _clamped_even(cy - crop_height / 2, max_y)
    return CropWindow(frame_idx, x, y, crop_width, crop_height, cx, cy)


def _even_floor(value: float) -> int:
    return int(np.floor(value / 2.0)) * 2


def _even_ceil(value: float) -> int:
    return int(np.ceil(value / 2.0)) * 2


def _clamped_even(value: float, maximum: int) -> int:
    maximum_even = maximum - maximum % 2
    rounded = int(round(value / 2.0)) * 2
    return min(max(rounded, 0), maximum_even)
