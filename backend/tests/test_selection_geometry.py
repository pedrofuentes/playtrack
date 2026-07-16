from __future__ import annotations

import pytest

from app.selection import (
    CropWindow,
    SelectionInputError,
    compute_crop_window,
    crop_box_to_source,
    source_to_crop_point,
)


def test_centers_1024_crop_on_panorama_click() -> None:
    crop = compute_crop_window(
        source_width=4096,
        source_height=1024,
        click_x=2048,
        click_y=512,
    )

    assert crop == CropWindow(x=1536, y=0, width=1024, height=1024)


def test_clamps_crop_to_source_edges() -> None:
    left = compute_crop_window(4096, 1024, 10, 10)
    right = compute_crop_window(4096, 1024, 4095, 1023)

    assert left == CropWindow(x=0, y=0, width=1024, height=1024)
    assert right == CropWindow(x=3072, y=0, width=1024, height=1024)


def test_uses_whole_source_when_smaller_than_crop() -> None:
    crop = compute_crop_window(640, 360, 320, 180)

    assert crop == CropWindow(x=0, y=0, width=640, height=360)


def test_maps_source_click_into_crop_coordinates() -> None:
    crop = CropWindow(x=1536, y=0, width=1024, height=1024)

    assert source_to_crop_point(crop, 2048, 512) == (512, 512)


def test_maps_exclusive_crop_box_back_to_source() -> None:
    crop = CropWindow(x=1536, y=100, width=1024, height=800)

    assert crop_box_to_source(crop, (10, 20, 100, 200)) == (
        1546,
        120,
        1636,
        300,
    )


@pytest.mark.parametrize(
    ("click_x", "click_y"),
    [(-1, 0), (0, -1), (4096, 0), (0, 1024)],
)
def test_rejects_clicks_outside_source(click_x: int, click_y: int) -> None:
    with pytest.raises(SelectionInputError, match="inside the source frame"):
        compute_crop_window(4096, 1024, click_x, click_y)
