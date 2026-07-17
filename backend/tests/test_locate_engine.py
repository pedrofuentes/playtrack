from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.models.locate_engine import (
    LocateAnythingEngine,
    detect_locate_device,
    get_locate_engine,
    parse_boxes,
)


class FakeCuda:
    def __init__(self, available: bool, capability: tuple[int, int]) -> None:
        self._available = available
        self._capability = capability
        self.empty_cache_calls = 0

    def is_available(self) -> bool:
        return self._available

    def get_device_capability(self) -> tuple[int, int]:
        return self._capability

    def empty_cache(self) -> None:
        self.empty_cache_calls += 1


def fake_torch(
    *, cuda: bool, capability: tuple[int, int] = (0, 0)
) -> SimpleNamespace:
    return SimpleNamespace(cuda=FakeCuda(cuda, capability))


def test_locate_device_matrix_uses_fp16_on_turing_and_bf16_on_ampere() -> None:
    turing = detect_locate_device(fake_torch(cuda=True, capability=(7, 5)))
    ampere = detect_locate_device(fake_torch(cuda=True, capability=(8, 6)))

    assert (turing.enabled, turing.dtype, turing.attention) == (
        True,
        "float16",
        "sdpa",
    )
    assert (ampere.enabled, ampere.dtype, ampere.attention) == (
        True,
        "bfloat16",
        "sdpa",
    )


def test_locate_device_matrix_disables_non_cuda_hosts() -> None:
    profile = detect_locate_device(fake_torch(cuda=False))

    assert profile.enabled is False
    assert profile.dtype is None
    assert "CUDA" in profile.reason


def test_parse_boxes_maps_normalized_tokens_to_pixel_xyxy() -> None:
    boxes = parse_boxes(
        "<ref>player</ref><box><250><100><750><900></box>",
        image_width=400,
        image_height=200,
    )

    assert boxes == [(100, 20, 300, 180)]


def test_singleton_is_lazy_and_unload_releases_cuda_cache(
    tmp_path: Path, monkeypatch: object
) -> None:
    get_locate_engine.cache_clear()
    engine = get_locate_engine("nvidia/LocateAnything-3B")
    assert isinstance(engine, LocateAnythingEngine)
    assert engine.is_loaded is False
    assert engine is get_locate_engine("nvidia/LocateAnything-3B")

    torch = fake_torch(cuda=True, capability=(7, 5))
    engine._model = object()
    engine._tokenizer = object()
    engine._processor = object()
    monkeypatch.setattr(engine, "_import_torch", lambda: torch)

    engine.unload()

    assert engine.is_loaded is False
    assert torch.cuda.empty_cache_calls == 1
