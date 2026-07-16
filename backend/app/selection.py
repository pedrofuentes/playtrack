from __future__ import annotations

import base64
import io
import math
from dataclasses import dataclass
from typing import Callable, Protocol

from .models.sam2_engine import SAM2EngineError, SAM2Prediction
from .videos import VideoStore


DEFAULT_CROP_SIZE = 1024


class SelectionError(Exception):
    """Base error for click selection."""


class SelectionInputError(SelectionError):
    """Raised when a click or geometry value is invalid."""


class SelectionUnavailableError(SelectionError):
    """Raised when the configured model cannot run."""


class EmptySelectionError(SelectionError):
    """Raised when SAM 2 returns no foreground pixels."""


@dataclass(frozen=True, slots=True)
class CropWindow:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class ClickSelection:
    box: tuple[int, int, int, int]
    mask_png: str
    score: float


class SelectionEngine(Protocol):
    def predict(self, image: object, point_x: int, point_y: int) -> SAM2Prediction: ...


EngineProvider = Callable[[], SelectionEngine]


class ClickSelector:
    """Run click selection on a high-resolution source crop."""

    def __init__(
        self,
        video_store: VideoStore,
        *,
        engine_provider: EngineProvider,
        crop_size: int = DEFAULT_CROP_SIZE,
    ) -> None:
        self.video_store = video_store
        self.engine_provider = engine_provider
        self.crop_size = crop_size

    def select_click(
        self, video_id: str, frame_idx: int, x: int, y: int
    ) -> ClickSelection:
        record = self.video_store.get(video_id)
        crop = compute_crop_window(
            record.metadata.width,
            record.metadata.height,
            x,
            y,
            self.crop_size,
        )
        crop_point = source_to_crop_point(crop, x, y)
        extracted = self.video_store.extract_source_crop(
            video_id,
            frame_idx=frame_idx,
            x=crop.x,
            y=crop.y,
            width=crop.width,
            height=crop.height,
        )

        try:
            import numpy as np
            from PIL import Image
        except ModuleNotFoundError as exc:
            raise SelectionUnavailableError(
                "NumPy and Pillow are required for click selection"
            ) from exc

        with Image.open(extracted.path) as source_image:
            rgb_image = np.asarray(source_image.convert("RGB"))
        try:
            prediction = self.engine_provider().predict(
                rgb_image, crop_point[0], crop_point[1]
            )
        except SAM2EngineError as exc:
            raise SelectionUnavailableError(str(exc)) from exc

        mask = np.asarray(prediction.mask, dtype=bool)
        if mask.shape != (crop.height, crop.width):
            raise SelectionUnavailableError(
                "SAM 2 returned a mask with unexpected dimensions"
            )
        mask_box = _mask_box(mask, np)
        if mask_box is None:
            raise EmptySelectionError("SAM 2 did not select any pixels")
        if not math.isfinite(prediction.score):
            raise SelectionUnavailableError("SAM 2 returned an invalid score")

        return ClickSelection(
            box=crop_box_to_source(crop, mask_box),
            mask_png=_encode_source_mask_png(
                mask,
                crop,
                source_width=record.metadata.width,
                source_height=record.metadata.height,
                np=np,
                image_class=Image,
            ),
            score=float(prediction.score),
        )


def compute_crop_window(
    source_width: int,
    source_height: int,
    click_x: int,
    click_y: int,
    crop_size: int = DEFAULT_CROP_SIZE,
) -> CropWindow:
    """Return a click-centered square crop clamped to source-pixel bounds."""
    if source_width <= 0 or source_height <= 0:
        raise SelectionInputError("Source dimensions must be positive")
    if crop_size <= 0:
        raise SelectionInputError("Crop size must be positive")
    if not (0 <= click_x < source_width and 0 <= click_y < source_height):
        raise SelectionInputError("Click must be inside the source frame")

    width = min(crop_size, source_width)
    height = min(crop_size, source_height)
    x = min(max(click_x - width // 2, 0), source_width - width)
    y = min(max(click_y - height // 2, 0), source_height - height)
    return CropWindow(x=x, y=y, width=width, height=height)


def source_to_crop_point(
    crop: CropWindow, source_x: int, source_y: int
) -> tuple[int, int]:
    crop_x = source_x - crop.x
    crop_y = source_y - crop.y
    if not (0 <= crop_x < crop.width and 0 <= crop_y < crop.height):
        raise SelectionInputError("Source point must be inside the crop")
    return crop_x, crop_y


def crop_box_to_source(
    crop: CropWindow, box: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    if not (0 <= x1 < x2 <= crop.width and 0 <= y1 < y2 <= crop.height):
        raise SelectionInputError("Crop box must be valid exclusive XYXY coordinates")
    return crop.x + x1, crop.y + y1, crop.x + x2, crop.y + y2


def _mask_box(mask: object, np: object) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return None
    return (
        int(xs.min()),
        int(ys.min()),
        int(xs.max()) + 1,
        int(ys.max()) + 1,
    )


def _encode_source_mask_png(
    mask: object,
    crop: CropWindow,
    *,
    source_width: int,
    source_height: int,
    np: object,
    image_class: object,
) -> str:
    overlay = np.zeros((source_height, source_width, 4), dtype=np.uint8)
    crop_overlay = overlay[
        crop.y : crop.y + crop.height,
        crop.x : crop.x + crop.width,
    ]
    crop_overlay[mask] = (47, 225, 180, 132)
    output = io.BytesIO()
    image_class.fromarray(overlay).save(output, format="PNG", compress_level=3)
    return base64.b64encode(output.getvalue()).decode("ascii")
