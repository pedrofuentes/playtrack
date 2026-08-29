from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import app.models.sam2_engine as sam2_engine
from app.models.sam2_engine import (
    DeviceProfile,
    SAM2Engine,
    SAM2VideoEngine,
    detect_device,
    get_sam2_engine,
    get_sam2_video_engine,
    resolve_video_offload,
    video_fits_in_vram,
)


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


def test_video_singleton_is_lazy_and_keeps_offload_configuration(
    tmp_path: Path,
) -> None:
    get_sam2_video_engine.cache_clear()
    checkpoint = tmp_path / "model.pt"

    first = get_sam2_video_engine(
        checkpoint,
        "configs/model.yaml",
        offload_video_to_cpu=True,
        offload_state_to_cpu=False,
    )
    second = get_sam2_video_engine(
        checkpoint,
        "configs/model.yaml",
        offload_video_to_cpu=True,
        offload_state_to_cpu=False,
    )

    assert isinstance(first, SAM2VideoEngine)
    assert first is second
    assert first.is_loaded is False
    assert first.offload_video_to_cpu is True
    assert first.offload_state_to_cpu is False


def test_full_video_tensor_fails_required_headroom() -> None:
    # 930 frames at 1024x1024 float32 is ~11,160 MiB: technically under an
    # 11,264 MiB card, but it leaves ~104 MiB — nowhere near enough for the
    # already-loaded model (~2,900 MiB baseline) plus headroom.
    assert not video_fits_in_vram(930, image_size=1024, free_bytes=11_264 * 1024**2)


@pytest.mark.parametrize("error", [ImportError, OSError, RuntimeError])
def test_sam2_cuda_extension_probe_never_raises(
    monkeypatch: pytest.MonkeyPatch, error: type[Exception]
) -> None:
    def failing(name: str) -> object:
        raise error(name)

    monkeypatch.setattr(sam2_engine.importlib, "import_module", failing)

    assert sam2_engine._sam2_cuda_extension_available() is False


def test_sam2_cuda_extension_probe_accepts_connected_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extension = SimpleNamespace(get_connected_componnets=lambda *_args: None)

    def import_module(name: str) -> SimpleNamespace:
        assert name == "sam2._C"
        return extension

    monkeypatch.setattr(sam2_engine.importlib, "import_module", import_module)

    assert sam2_engine._sam2_cuda_extension_available() is True


def _install_fake_video_predictor_builder(
    monkeypatch: pytest.MonkeyPatch, predictor: SimpleNamespace
) -> dict[str, object]:
    received: dict[str, object] = {}

    def build(*args: object, **kwargs: object) -> SimpleNamespace:
        received["kwargs"] = dict(kwargs)
        return predictor

    build_sam = ModuleType("sam2.build_sam")
    build_sam.build_sam2_video_predictor = build
    sam2 = ModuleType("sam2")
    sam2.build_sam = build_sam
    monkeypatch.setitem(sys.modules, "sam2", sam2)
    monkeypatch.setitem(sys.modules, "sam2.build_sam", build_sam)
    return received


def test_video_predictor_disables_only_hole_filling_without_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"")
    predictor = SimpleNamespace(
        fill_hole_area=8,
        dynamic_multimask_via_stability=True,
        binarize_mask_from_pts_for_mem_enc=True,
    )
    received = _install_fake_video_predictor_builder(monkeypatch, predictor)
    engine = SAM2VideoEngine(checkpoint, "cfg")
    engine._profile = DeviceProfile("cpu", None, "small", None)
    monkeypatch.setattr(
        sam2_engine, "_sam2_cuda_extension_available", lambda: False, raising=False
    )

    assert engine._ensure_predictor(fake_torch()) is predictor
    # Upstream post-processing stays on its defaults; only hole filling is cut.
    assert "apply_postprocessing" not in received["kwargs"]
    assert predictor.fill_hole_area == 0
    assert predictor.dynamic_multimask_via_stability is True
    assert predictor.binarize_mask_from_pts_for_mem_enc is True


def test_video_predictor_keeps_hole_filling_with_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"")
    predictor = SimpleNamespace(
        fill_hole_area=8,
        dynamic_multimask_via_stability=True,
        binarize_mask_from_pts_for_mem_enc=True,
    )
    _install_fake_video_predictor_builder(monkeypatch, predictor)
    engine = SAM2VideoEngine(checkpoint, "cfg")
    engine._profile = DeviceProfile("cpu", None, "small", None)
    monkeypatch.setattr(
        sam2_engine, "_sam2_cuda_extension_available", lambda: True, raising=False
    )

    assert engine._ensure_predictor(fake_torch()) is predictor
    assert predictor.fill_hole_area == 8


def test_cuda_offload_warning_reports_memory_budget(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="app.models.sam2_engine"):
        result = resolve_video_offload(
            "cuda",
            requested_video=False,
            requested_state=False,
            frame_count=930,
            image_size=1024,
            free_vram_bytes=9_603 * 1024**2,
        )

    assert result == (True, True)
    assert len(caplog.records) == 1
    assert "11160 MiB video tensor" in caplog.messages[0]
    assert "3072 MiB headroom" in caplog.messages[0]
    assert "9603 MiB free VRAM" in caplog.messages[0]


def test_short_clip_video_tensor_fits_with_headroom() -> None:
    # 100 frames is ~1.2 GiB; fits an 8 GiB budget even with headroom.
    assert video_fits_in_vram(100, image_size=1024, free_bytes=8 * 1024**3)


def test_mps_always_offloads_video_and_state() -> None:
    assert resolve_video_offload(
        "mps",
        requested_video=False,
        requested_state=False,
        frame_count=10,
        image_size=1024,
        free_vram_bytes=None,
    ) == (True, True)


def test_cuda_offloads_when_video_tensor_lacks_headroom() -> None:
    assert resolve_video_offload(
        "cuda",
        requested_video=False,
        requested_state=False,
        frame_count=930,
        image_size=1024,
        free_vram_bytes=11_264 * 1024**2,
    ) == (True, True)


def test_cuda_keeps_gpu_video_when_tensor_fits() -> None:
    assert resolve_video_offload(
        "cuda",
        requested_video=False,
        requested_state=False,
        frame_count=100,
        image_size=1024,
        free_vram_bytes=8 * 1024**3,
    ) == (False, False)


def test_explicit_offload_requests_are_never_downgraded() -> None:
    assert resolve_video_offload(
        "cuda",
        requested_video=True,
        requested_state=True,
        frame_count=10,
        image_size=1024,
        free_vram_bytes=24 * 1024**3,
    ) == (True, True)


def test_explicit_video_offload_is_not_escalated_to_state_offload() -> None:
    # With the video already on CPU the giant tensor never reaches the GPU,
    # so a long clip must not drag state offload (slower) along with it.
    assert resolve_video_offload(
        "cuda",
        requested_video=True,
        requested_state=False,
        frame_count=930,
        image_size=1024,
        free_vram_bytes=11_264 * 1024**2,
    ) == (True, False)


def test_cpu_device_passes_requests_through() -> None:
    assert resolve_video_offload(
        "cpu",
        requested_video=False,
        requested_state=True,
        frame_count=930,
        image_size=1024,
        free_vram_bytes=None,
    ) == (False, True)


class _NullContext:
    def __enter__(self) -> "_NullContext":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class RecordingVideoPredictor:
    image_size = 1024

    def __init__(self) -> None:
        self.init_kwargs: dict[str, bool] | None = None

    def init_state(
        self,
        *,
        video_path: str,
        offload_video_to_cpu: bool,
        offload_state_to_cpu: bool,
    ) -> object:
        self.init_kwargs = {
            "offload_video_to_cpu": offload_video_to_cpu,
            "offload_state_to_cpu": offload_state_to_cpu,
        }
        return object()

    def add_new_points_or_box(self, **kwargs: object) -> None:
        return None

    def propagate_in_video(
        self, state: object, *, start_frame_idx: int, reverse: bool
    ) -> object:
        return iter(())


def fake_video_torch(free_bytes: int) -> SimpleNamespace:
    # Real torch cannot be used here: torch.autocast("cuda") and
    # torch.cuda.mem_get_info() are unavailable off-GPU.
    return SimpleNamespace(
        inference_mode=_NullContext,
        autocast=lambda **_kwargs: _NullContext(),
        float16="float16",
        cuda=SimpleNamespace(mem_get_info=lambda: (free_bytes, 11_264 * 1024**2)),
    )


def test_cuda_propagate_wires_offload_into_init_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Proof that the guard's decision actually reaches SAM2: a 930-frame
    # CUDA propagation on an 11 GiB budget must call init_state with both
    # offload flags enabled. This is the wiring the live GPU run relies on.
    frames = tmp_path / "frames"
    frames.mkdir()
    for index in range(930):
        (frames / f"{index:05d}.jpg").write_bytes(b"")

    engine = SAM2VideoEngine(tmp_path / "missing.pt", "cfg")
    predictor = RecordingVideoPredictor()
    engine._predictor = predictor
    engine._profile = DeviceProfile("cuda", "float16", "base-plus", (7, 5))
    monkeypatch.setattr(
        SAM2Engine,
        "_import_torch",
        staticmethod(lambda: fake_video_torch(11_264 * 1024**2)),
    )

    assert list(engine.propagate(frames, 0, (10, 10, 20, 20), reverse=False)) == []
    assert predictor.init_kwargs == {
        "offload_video_to_cpu": True,
        "offload_state_to_cpu": True,
    }
