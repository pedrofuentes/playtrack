from __future__ import annotations

import os
import threading
from contextlib import ExitStack
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


class SAM2EngineError(RuntimeError):
    """Base error for SAM 2 loading and prediction."""


class SAM2CheckpointMissingError(SAM2EngineError):
    """Raised when the configured checkpoint has not been downloaded."""


class SAM2DependencyError(SAM2EngineError):
    """Raised when Torch, NumPy, or the official SAM 2 package is absent."""


@dataclass(frozen=True, slots=True)
class DeviceProfile:
    device: str
    autocast_dtype: str | None
    recommended_model: str
    compute_capability: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class SAM2Prediction:
    mask: Any
    score: float


def detect_device(torch_module: Any | None = None) -> DeviceProfile:
    """Detect the plan's CUDA/MPS/CPU profile without importing Torch eagerly."""
    if torch_module is None:
        try:
            import torch as torch_module
        except ModuleNotFoundError:
            return DeviceProfile("cpu", None, "small")

    if torch_module.cuda.is_available():
        capability = tuple(torch_module.cuda.get_device_capability())
        if capability[0] >= 8:
            return DeviceProfile("cuda", "bfloat16", "large", capability)
        return DeviceProfile("cuda", "float16", "base-plus", capability)

    mps_backend = getattr(getattr(torch_module, "backends", None), "mps", None)
    if mps_backend is not None and mps_backend.is_available():
        return DeviceProfile("mps", None, "base-plus")
    return DeviceProfile("cpu", None, "small")


class SAM2Engine:
    """Thread-safe, lazy wrapper around the official SAM2ImagePredictor."""

    def __init__(self, checkpoint_path: Path, model_config: str) -> None:
        self.checkpoint_path = Path(checkpoint_path)
        self.model_config = model_config
        self._predictor: Any | None = None
        self._profile: DeviceProfile | None = None
        self._lock = threading.RLock()

    @property
    def is_loaded(self) -> bool:
        with self._lock:
            return self._predictor is not None

    @property
    def device_profile(self) -> DeviceProfile:
        with self._lock:
            if self._profile is None:
                self._profile = detect_device()
            return self._profile

    def predict(self, image: Any, point_x: int, point_y: int) -> SAM2Prediction:
        with self._lock:
            torch = self._import_torch()
            predictor = self._ensure_predictor(torch)
            try:
                import numpy as np
            except ModuleNotFoundError as exc:
                raise SAM2DependencyError(
                    "NumPy is required for SAM 2 image prediction"
                ) from exc

            with ExitStack() as contexts:
                contexts.enter_context(torch.inference_mode())
                profile = self.device_profile
                if profile.device == "cuda" and profile.autocast_dtype is not None:
                    contexts.enter_context(
                        torch.autocast(
                            device_type="cuda",
                            dtype=getattr(torch, profile.autocast_dtype),
                        )
                    )
                predictor.set_image(image)
                masks, scores, _ = predictor.predict(
                    point_coords=np.asarray(
                        [[point_x, point_y]], dtype=np.float32
                    ),
                    point_labels=np.asarray([1], dtype=np.int32),
                    multimask_output=True,
                )

            scores_array = np.asarray(scores)
            masks_array = np.asarray(masks)
            if scores_array.size == 0 or masks_array.shape[0] != scores_array.size:
                raise SAM2EngineError("SAM 2 returned an invalid prediction")
            best_index = int(np.argmax(scores_array))
            return SAM2Prediction(
                mask=np.asarray(masks_array[best_index], dtype=bool),
                score=float(scores_array[best_index]),
            )

    def _ensure_predictor(self, torch: Any) -> Any:
        if self._predictor is not None:
            return self._predictor
        if not self.checkpoint_path.is_file():
            raise SAM2CheckpointMissingError(
                f"SAM 2 checkpoint not found: {self.checkpoint_path}. "
                "Run scripts/fetch_models.py first."
            )

        try:
            from sam2.build_sam import build_sam2
            from sam2.sam2_image_predictor import SAM2ImagePredictor
        except ModuleNotFoundError as exc:
            raise SAM2DependencyError(
                "The official SAM-2 package is required for click selection"
            ) from exc

        profile = self.device_profile
        if profile.device == "cuda" and profile.compute_capability is not None:
            self._configure_cuda_attention(torch, profile)

        try:
            model = build_sam2(
                self.model_config,
                str(self.checkpoint_path),
                device=profile.device,
            )
            self._predictor = SAM2ImagePredictor(model)
        except Exception as exc:
            raise SAM2EngineError(f"Could not load SAM 2: {exc}") from exc
        return self._predictor

    @staticmethod
    def _configure_cuda_attention(torch: Any, profile: DeviceProfile) -> None:
        """Keep Turing on supported SDPA kernels instead of Flash Attention."""
        if profile.compute_capability is None or profile.compute_capability[0] >= 8:
            return
        cuda_backend = getattr(getattr(torch, "backends", None), "cuda", None)
        if cuda_backend is None:
            return
        if hasattr(cuda_backend, "enable_flash_sdp"):
            cuda_backend.enable_flash_sdp(False)
        if hasattr(cuda_backend, "enable_math_sdp"):
            cuda_backend.enable_math_sdp(True)
        if hasattr(cuda_backend, "enable_mem_efficient_sdp"):
            cuda_backend.enable_mem_efficient_sdp(True)

    @staticmethod
    def _import_torch() -> Any:
        os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
        try:
            import torch
        except ModuleNotFoundError as exc:
            raise SAM2DependencyError(
                "PyTorch is required for SAM 2 image prediction"
            ) from exc
        return torch


@lru_cache(maxsize=None)
def get_sam2_engine(checkpoint_path: Path, model_config: str) -> SAM2Engine:
    """Return one lazy engine per checkpoint/configuration pair."""
    return SAM2Engine(Path(checkpoint_path), model_config)
