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
        smoothing=SmoothingOptions(window_sec=0, dead_zone_px=0, max_velocity=9999),
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
    options = SmoothingOptions(
        window_sec=0.2,
        dead_zone_px=30,
        max_velocity=28,
    )
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
    xs = np.asarray([window.x + window.width / 2 for window in first])
    assert np.max(np.abs(np.diff(xs))) <= 28
