from __future__ import annotations

import numpy as np
import pytest

from app.crop_planner import (
    CropPlanningError,
    SmoothingOptions,
    fill_missing_centers,
    plan_crop_windows,
)


def test_gap_fill_interpolates_interior_and_holds_sequence_ends() -> None:
    centers = [None, (0.0, 0.0), None, None, (6.0, 3.0), None]

    filled = fill_missing_centers(centers)

    np.testing.assert_allclose(
        filled,
        np.asarray(
            [
                (0.0, 0.0),
                (0.0, 0.0),
                (2.0, 1.0),
                (4.0, 2.0),
                (6.0, 3.0),
                (6.0, 3.0),
            ]
        ),
    )


def test_gap_fill_rejects_track_without_any_known_center() -> None:
    with pytest.raises(CropPlanningError, match="known center"):
        fill_missing_centers([None, None])


def test_plan_sizes_window_to_output_aspect_and_clamps_frame_edges() -> None:
    windows = plan_crop_windows(
        [(0.0, 0.0), (4095.0, 1023.0)],
        source_width=4096,
        source_height=1024,
        output_width=1920,
        output_height=1080,
        fps=30.0,
        smoothing=SmoothingOptions(responsiveness=0, max_acceleration=9999),
    )

    assert (windows[0].width, windows[0].height) == (1820, 1024)
    assert (windows[0].x, windows[0].y) == (0, 0)
    assert windows[1].x + windows[1].width <= 4096
    assert windows[1].y + windows[1].height <= 1024
    assert windows[1].x == 2276


def test_plan_emits_fully_clamped_even_integer_windows() -> None:
    windows = plan_crop_windows(
        [(5.5, 7.25), (501.2, 301.7), (999.0, 599.0)],
        source_width=1001,
        source_height=601,
        output_width=853,
        output_height=479,
        fps=29.97,
        zoom=2.3,
    )

    for window in windows:
        values = (window.x, window.y, window.width, window.height)
        assert all(isinstance(value, int) for value in values)
        assert all(value % 2 == 0 for value in values)
        assert 0 <= window.x < window.x + window.width <= 1001
        assert 0 <= window.y < window.y + window.height <= 601


def test_zoom_is_clamped_to_supported_one_through_four_range() -> None:
    arguments = dict(
        centers=[(500.0, 300.0)],
        source_width=1000,
        source_height=600,
        output_width=16,
        output_height=9,
        fps=30.0,
    )

    below = plan_crop_windows(**arguments, zoom=0.1)
    minimum = plan_crop_windows(**arguments, zoom=1.0)
    above = plan_crop_windows(**arguments, zoom=99.0)
    maximum = plan_crop_windows(**arguments, zoom=4.0)

    assert below == minimum
    assert above == maximum
    assert maximum[0].width < minimum[0].width


def test_smoothing_is_deterministic_and_velocity_limited() -> None:
    centers = [(100.0, 100.0), (110.0, 100.0), (300.0, 100.0)] * 4
    options = SmoothingOptions(responsiveness=0.35, max_acceleration=3)
    arguments = dict(
        centers=centers,
        source_width=1000,
        source_height=600,
        output_width=320,
        output_height=180,
        fps=30.0,
        zoom=4.0,
        smoothing=options,
    )

    first = plan_crop_windows(**arguments)
    second = plan_crop_windows(**arguments)

    assert first == second
    xs = np.asarray([window.cx for window in first])
    velocities = np.diff(xs)
    assert np.max(np.abs(np.diff(velocities))) <= 3.000001


def test_spring_filter_converges_deterministically_to_a_step_target() -> None:
    options = SmoothingOptions(responsiveness=0.5, max_acceleration=1000)
    arguments = dict(
        centers=[(100.0, 100.0)] + [(500.0, 100.0)] * 180,
        source_width=1000,
        source_height=600,
        output_width=320,
        output_height=180,
        fps=30.0,
        zoom=4.0,
        smoothing=options,
    )

    first = plan_crop_windows(**arguments)
    second = plan_crop_windows(**arguments)

    assert first == second
    assert first[-1].cx is not None
    assert abs(first[-1].cx - 500.0) < 1.0


def test_float_centers_are_edge_clamped_while_preview_windows_stay_even() -> None:
    windows = plan_crop_windows(
        [(0.1, 0.1), (999.9, 599.9)],
        source_width=1000,
        source_height=600,
        output_width=320,
        output_height=180,
        fps=30,
        zoom=4,
        smoothing=SmoothingOptions(responsiveness=0, max_acceleration=9999),
    )

    assert windows[0].cx == windows[0].width / 2
    assert windows[0].cy == windows[0].height / 2
    assert windows[-1].cx == 1000 - windows[-1].width / 2
    assert windows[-1].cy == 600 - windows[-1].height / 2
    assert all(window.x % 2 == window.y % 2 == 0 for window in windows)


def test_adaptive_crop_keeps_fast_player_box_visible() -> None:
    centers = [(500.0, 700.0)] * 12 + [(2500.0, 700.0)] * 40
    boxes = [
        (460.0, 640.0, 540.0, 760.0) if index < 12
        else (2460.0, 640.0, 2540.0, 760.0)
        for index in range(len(centers))
    ]

    windows = plan_crop_windows(
        centers,
        boxes=boxes,
        source_width=4096,
        source_height=1024,
        output_width=1280,
        output_height=720,
        fps=30,
        zoom=3.4,
        smoothing=SmoothingOptions(responsiveness=1.2, max_acceleration=3),
    )

    for window, box in zip(windows, boxes, strict=True):
        x1, y1, x2, y2 = box
        assert window.x <= x1 <= x2 <= window.x + window.width
        assert window.y <= y1 <= y2 <= window.y + window.height


def test_adaptive_crop_widens_immediately_and_returns_slowly() -> None:
    centers = [(500.0, 500.0)] * 5 + [(1800.0, 500.0)] + [(500.0, 500.0)] * 180
    boxes = [(center[0] - 40, 440.0, center[0] + 40, 560.0) for center in centers]

    windows = plan_crop_windows(
        centers,
        boxes=boxes,
        source_width=2400,
        source_height=1350,
        output_width=1280,
        output_height=720,
        fps=30,
        zoom=4,
        smoothing=SmoothingOptions(responsiveness=1.2, max_acceleration=9999),
    )

    target_width = windows[0].width
    widened_width = windows[5].width
    assert widened_width > target_width
    assert target_width < windows[6].width <= widened_width
    assert windows[-1].width < windows[6].width
    assert windows[-1].width <= target_width + 4


def test_adaptive_crop_holds_safe_scale_while_track_is_lost() -> None:
    centers = [(500.0, 500.0), (1800.0, 500.0), None, None, (500.0, 500.0)]
    boxes = [
        (460.0, 440.0, 540.0, 560.0),
        (1760.0, 440.0, 1840.0, 560.0),
        None,
        None,
        (460.0, 440.0, 540.0, 560.0),
    ]

    windows = plan_crop_windows(
        centers,
        boxes=boxes,
        source_width=2400,
        source_height=1350,
        output_width=1280,
        output_height=720,
        fps=30,
        zoom=4,
        smoothing=SmoothingOptions(responsiveness=1.2, max_acceleration=9999),
    )

    assert windows[2].width == windows[1].width
    assert windows[3].width == windows[1].width
    assert all(window.width % 2 == window.height % 2 == 0 for window in windows)
