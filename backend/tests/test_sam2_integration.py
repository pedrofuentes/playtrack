from __future__ import annotations

import base64
from pathlib import Path

import pytest

from app.config import settings
from app.models.sam2_engine import get_sam2_engine
from app.selection import ClickSelector
from app.videos import VideoStore


@pytest.mark.integration
@pytest.mark.skipif(
    not settings.sam2_checkpoint.is_file(),
    reason="SAM 2.1 checkpoint is not downloaded",
)
def test_full_sam2_click_prediction_on_example(tmp_path: Path) -> None:
    store = VideoStore(repo_root=settings.repo_root, data_dir=tmp_path / "data")
    record = store.register_path("examples/example.mp4")
    selector = ClickSelector(
        store,
        engine_provider=lambda: get_sam2_engine(
            settings.sam2_checkpoint, settings.sam2_model_config
        ),
        crop_size=settings.sam2_crop_size,
    )

    result = selector.select_click(record.video_id, frame_idx=0, x=2048, y=512)

    assert base64.b64decode(result.mask_png).startswith(b"\x89PNG\r\n\x1a\n")
    x1, y1, x2, y2 = result.box
    assert 0 <= x1 < x2 <= record.metadata.width
    assert 0 <= y1 < y2 <= record.metadata.height
    assert 0.0 <= result.score <= 1.0
