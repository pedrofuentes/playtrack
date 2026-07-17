from __future__ import annotations

from pathlib import Path

import pytest

from app.config import settings
from app.models.locate_engine import get_locate_engine
from app.videos import VideoStore


@pytest.mark.integration
@pytest.mark.requires_cuda
def test_real_locateanything_text_grounding_on_example(tmp_path: Path) -> None:
    torch = pytest.importorskip("torch")
    if not torch.cuda.is_available():
        pytest.skip("LocateAnything integration requires an NVIDIA CUDA GPU")
    pytest.importorskip(
        "transformers",
        reason="Install the CUDA-only LocateAnything extra with --extra locate",
    )
    from PIL import Image

    store = VideoStore(repo_root=settings.repo_root, data_dir=tmp_path / "data")
    record = store.register_path("examples/example.mp4")
    extracted = store.extract_source_crop(
        record.video_id,
        frame_idx=0,
        x=0,
        y=0,
        width=record.metadata.width,
        height=record.metadata.height,
    )
    with Image.open(extracted.path) as source:
        image = source.convert("RGB")
        if max(image.size) > settings.locate_max_input_dimension:
            scale = settings.locate_max_input_dimension / max(image.size)
            image = image.resize(
                (round(image.width * scale), round(image.height * scale)),
                Image.Resampling.LANCZOS,
            )

    engine = get_locate_engine(settings.locate_model_id)
    try:
        candidates = engine.ground_text(image, "the player in the white jersey")
    finally:
        engine.unload()

    assert candidates
    assert all(0 <= candidate.score <= 1 for candidate in candidates)
    assert all(
        0 <= candidate.box[0] < candidate.box[2] <= image.width
        and 0 <= candidate.box[1] < candidate.box[3] <= image.height
        for candidate in candidates
    )
