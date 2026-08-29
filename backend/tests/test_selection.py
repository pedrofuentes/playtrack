from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from app.models.sam2_engine import SAM2Prediction
from app.selection import ClickSelector


class RecordingEngine:
    def __init__(self) -> None:
        self.image: np.ndarray | None = None

    def predict(self, image: object, point_x: int, point_y: int) -> SAM2Prediction:
        assert isinstance(image, np.ndarray)
        self.image = image
        mask = np.zeros(image.shape[:2], dtype=bool)
        mask[point_y, point_x] = True
        return SAM2Prediction(mask=mask, score=0.9)


class TinyVideoStore:
    def __init__(self, image_path: Path) -> None:
        self.image_path = image_path

    def get(self, video_id: str) -> object:
        return SimpleNamespace(metadata=SimpleNamespace(width=4, height=3))

    def extract_source_crop(self, *args: object, **kwargs: object) -> object:
        return SimpleNamespace(path=self.image_path)


def test_click_selector_passes_writable_owned_rgb_array(tmp_path: Path) -> None:
    image_path = tmp_path / "crop.png"
    Image.new("RGB", (4, 3), (10, 20, 30)).save(image_path)
    engine = RecordingEngine()
    selector = ClickSelector(
        TinyVideoStore(image_path), engine_provider=lambda: engine, crop_size=4
    )

    selector.select_click("video-1", frame_idx=0, x=1, y=1)

    assert engine.image is not None
    assert engine.image.dtype == np.uint8
    assert engine.image.flags.c_contiguous
    assert engine.image.flags.writeable
    assert engine.image.base is None
