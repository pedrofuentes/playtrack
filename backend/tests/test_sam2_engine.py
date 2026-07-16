from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.models.sam2_engine import SAM2Engine, detect_device, get_sam2_engine


class FakeCuda:
    def __init__(self, available: bool, capability: tuple[int, int] = (0, 0)) -> None:
        self._available = available
        self._capability = capability

    def is_available(self) -> bool:
        return self._available

    def get_device_capability(self) -> tuple[int, int]:
        return self._capability


class FakeMps:
    def __init__(self, available: bool) -> None:
        self._available = available

    def is_available(self) -> bool:
        return self._available


def fake_torch(
    *, cuda: bool = False, capability: tuple[int, int] = (0, 0), mps: bool = False
) -> SimpleNamespace:
    return SimpleNamespace(
        cuda=FakeCuda(cuda, capability),
        backends=SimpleNamespace(mps=FakeMps(mps)),
    )


def test_detects_turing_cuda_profile() -> None:
    profile = detect_device(fake_torch(cuda=True, capability=(7, 5)))

    assert profile.device == "cuda"
    assert profile.autocast_dtype == "float16"
    assert profile.recommended_model == "base-plus"


def test_detects_ampere_cuda_profile() -> None:
    profile = detect_device(fake_torch(cuda=True, capability=(8, 6)))

    assert profile.device == "cuda"
    assert profile.autocast_dtype == "bfloat16"
    assert profile.recommended_model == "large"


def test_detects_mps_profile() -> None:
    profile = detect_device(fake_torch(mps=True))

    assert profile.device == "mps"
    assert profile.autocast_dtype is None
    assert profile.recommended_model == "base-plus"


def test_falls_back_to_cpu_profile() -> None:
    profile = detect_device(fake_torch())

    assert profile.device == "cpu"
    assert profile.autocast_dtype is None
    assert profile.recommended_model == "small"


def test_singleton_is_lazy_and_reuses_matching_configuration(tmp_path: Path) -> None:
    get_sam2_engine.cache_clear()
    checkpoint = tmp_path / "model.pt"

    first = get_sam2_engine(checkpoint, "configs/model.yaml")
    second = get_sam2_engine(checkpoint, "configs/model.yaml")

    assert isinstance(first, SAM2Engine)
    assert first is second
    assert first.is_loaded is False
