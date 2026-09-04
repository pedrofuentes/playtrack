from __future__ import annotations

import os
import gc
import importlib
import logging
import threading
from contextlib import ExitStack
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ..tracking import PropagationDirection

logger = logging.getLogger(__name__)

# SAM2 keeps activations, the memory bank, and autocast copies alongside the
# stacked video tensor. CUDA desktops also need enough unclaimed VRAM for the
# display driver to remain responsive while tracking runs.
_VIDEO_RUNTIME_HEADROOM_BYTES = 3 * 1024**3
_CUDA_SYSTEM_RESERVE_BYTES = 2 * 1024**3
FrameLoadProgress = Callable[[int, int], None]


def video_fits_in_vram(frame_count: int, *, image_size: int, free_bytes: int) -> bool:
    """Whether SAM2's stacked float32 [N, 3, S, S] video tensor fits free VRAM
    with enough headroom for runtime allocations and the host desktop."""
    tensor_bytes = frame_count * 3 * image_size * image_size * 4
    return (
        tensor_bytes
        + _VIDEO_RUNTIME_HEADROOM_BYTES
        + _CUDA_SYSTEM_RESERVE_BYTES
        <= free_bytes
    )


def _sam2_cuda_extension_available() -> bool:
    try:
        extension = importlib.import_module("sam2._C")
    except Exception:  # optional native module — probing it must never be fatal
        return False
    return callable(getattr(extension, "get_connected_componnets", None))


def resolve_video_offload(
    device: str,
    *,
    requested_video: bool,
    requested_state: bool,
    frame_count: int,
    image_size: int,
    free_vram_bytes: int | None,
) -> tuple[bool, bool]:
    """Final (offload_video, offload_state) flags for SAM2 init_state.

    MPS always offloads: its stacked video tensor exceeds MPSGraph's INT_MAX
    above ~750 frames. CUDA escalates only when the video would otherwise
    live on the GPU but lacks headroom (930 frames ~= 11,160 MiB against an
    11,264 MiB card plus a ~2,900 MiB loaded model froze an RTX 2080 Ti
    desktop via WDDM oversubscription). A tripped guard enables both flags —
    the only configuration verified stable on 11 GB. Requests are only
    honored upward; requested video offload already keeps the tensor on CPU,
    so nothing else is escalated.
    """
    if device == "mps":
        return True, True
    if (
        device == "cuda"
        and not requested_video
        and free_vram_bytes is not None
        and not video_fits_in_vram(
            frame_count, image_size=image_size, free_bytes=free_vram_bytes
        )
    ):
        tensor_mib = frame_count * 3 * image_size * image_size * 4 // 1024**2
        headroom_mib = _VIDEO_RUNTIME_HEADROOM_BYTES // 1024**2
        reserve_mib = _CUDA_SYSTEM_RESERVE_BYTES // 1024**2
        free_mib = free_vram_bytes // 1024**2
        logger.warning(
            "SAM2 safety guard: %d MiB video tensor plus %d MiB runtime "
            "headroom plus %d MiB system reserve exceeds %d MiB free VRAM; "
            "enabling CPU offload",
            tensor_mib,
            headroom_mib,
            reserve_mib,
            free_mib,
        )
        return True, True
    return requested_video, requested_state


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

    def unload(self) -> None:
        """Release the image predictor to free accelerator memory."""
        with self._lock:
            self._predictor = None
            gc.collect()
            torch = self._import_torch()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

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


class SAM2VideoEngine:
    """Lazy, serialized wrapper around the official SAM 2 video predictor."""

    def __init__(
        self,
        checkpoint_path: Path,
        model_config: str,
        *,
        offload_video_to_cpu: bool = False,
        offload_state_to_cpu: bool = False,
    ) -> None:
        self.checkpoint_path = Path(checkpoint_path)
        self.model_config = model_config
        self.offload_video_to_cpu = offload_video_to_cpu
        self.offload_state_to_cpu = offload_state_to_cpu
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

    def propagate_directions(
        self,
        frame_directory: Path,
        anchor_frame_idx: int,
        box: tuple[int, int, int, int],
        *,
        directions: tuple[PropagationDirection, ...],
        on_frame_load: FrameLoadProgress | None = None,
    ) -> object:
        with self._lock:
            torch = SAM2Engine._import_torch()
            predictor = self._ensure_predictor(torch)
            try:
                import numpy as np
            except ModuleNotFoundError as exc:
                raise SAM2DependencyError(
                    "NumPy is required for SAM 2 video propagation"
                ) from exc

            profile = self.device_profile
            state: Any | None = None
            try:
                with ExitStack() as contexts:
                    contexts.enter_context(torch.inference_mode())
                    if profile.device == "cuda" and profile.autocast_dtype is not None:
                        contexts.enter_context(
                            torch.autocast(
                                device_type="cuda",
                                dtype=getattr(torch, profile.autocast_dtype),
                            )
                        )
                    if profile.device == "cuda":
                        gc.collect()
                        self._empty_cuda_cache(torch, context="before video state")
                    frame_count = sum(
                        1
                        for entry in Path(frame_directory).iterdir()
                        if entry.suffix.lower() in {".jpg", ".jpeg"}
                    )
                    free_vram_bytes = None
                    if profile.device == "cuda":
                        free_vram_bytes, total_vram_bytes = torch.cuda.mem_get_info()
                        logger.debug(
                            "SAM2 CUDA memory before video state: %d MiB free of %d MiB",
                            free_vram_bytes // 1024**2,
                            total_vram_bytes // 1024**2,
                        )
                    offload_video, offload_state = resolve_video_offload(
                        profile.device,
                        requested_video=self.offload_video_to_cpu,
                        requested_state=self.offload_state_to_cpu,
                        frame_count=frame_count,
                        image_size=int(getattr(predictor, "image_size", 1024)),
                        free_vram_bytes=free_vram_bytes,
                    )
                    from sam2.utils import misc as sam2_misc

                    original_tqdm = sam2_misc.tqdm

                    def reporting_tqdm(*args: Any, **kwargs: Any) -> object:
                        progress = original_tqdm(*args, **kwargs)
                        if (
                            on_frame_load is None
                            or kwargs.get("desc") != "frame loading (JPEG)"
                        ):
                            return progress
                        total = getattr(progress, "total", None)

                        def report_items() -> object:
                            for completed, item in enumerate(progress, start=1):
                                yield item
                                if isinstance(total, int) and total > 0:
                                    on_frame_load(completed, total)

                        return report_items()

                    sam2_misc.tqdm = reporting_tqdm
                    try:
                        state = predictor.init_state(
                            video_path=str(frame_directory),
                            offload_video_to_cpu=offload_video,
                            offload_state_to_cpu=offload_state,
                        )
                    finally:
                        sam2_misc.tqdm = original_tqdm
                    for direction_index, direction in enumerate(directions):
                        if direction_index > 0:
                            predictor.reset_state(state)
                            gc.collect()
                            if profile.device == "cuda":
                                self._empty_cuda_cache(
                                    torch, context="between tracking directions"
                                )
                        predictor.add_new_points_or_box(
                            inference_state=state,
                            frame_idx=anchor_frame_idx,
                            obj_id=1,
                            box=np.asarray(box, dtype=np.float32),
                        )
                        propagation = predictor.propagate_in_video(
                            state,
                            start_frame_idx=anchor_frame_idx,
                            reverse=direction == "backward",
                        )
                        try:
                            for output_frame_idx, object_ids, mask_logits in propagation:
                                object_id_values = (
                                    np.asarray(object_ids).reshape(-1).tolist()
                                )
                                try:
                                    object_index = object_id_values.index(1)
                                except ValueError:
                                    continue
                                logits = mask_logits[object_index]
                                if hasattr(logits, "detach"):
                                    logits = logits.detach()
                                if hasattr(logits, "cpu"):
                                    logits = logits.cpu()
                                mask = np.asarray(logits > 0, dtype=bool).squeeze()
                                yield direction, int(output_frame_idx), mask
                        finally:
                            close = getattr(propagation, "close", None)
                            if close is not None:
                                close()
                            propagation = None
            finally:
                if state is not None:
                    try:
                        predictor.reset_state(state)
                    except Exception:
                        logger.warning(
                            "SAM2 could not reset video inference state during cleanup",
                            exc_info=True,
                        )
                    try:
                        state.clear()
                    except Exception:
                        logger.warning(
                            "SAM2 could not clear video inference state during cleanup",
                            exc_info=True,
                        )
                    state = None
                gc.collect()
                if profile.device == "cuda":
                    self._empty_cuda_cache(torch, context="after video state")
                    try:
                        free_vram_bytes, total_vram_bytes = torch.cuda.mem_get_info()
                    except Exception:
                        logger.debug(
                            "SAM2 could not read CUDA memory after cleanup", exc_info=True
                        )
                    else:
                        logger.info(
                            "SAM2 video state released: %d MiB free of %d MiB VRAM; "
                            "predictor remains loaded",
                            free_vram_bytes // 1024**2,
                            total_vram_bytes // 1024**2,
                        )

    @staticmethod
    def _empty_cuda_cache(torch: Any, *, context: str) -> None:
        try:
            torch.cuda.empty_cache()
        except Exception:
            logger.warning(
                "SAM2 could not release unused CUDA memory %s", context, exc_info=True
            )

    def unload(self) -> None:
        """Release the video predictor to free accelerator memory."""
        with self._lock:
            self._predictor = None
            gc.collect()
            torch = SAM2Engine._import_torch()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def _ensure_predictor(self, torch: Any) -> Any:
        if self._predictor is not None:
            return self._predictor
        if not self.checkpoint_path.is_file():
            raise SAM2CheckpointMissingError(
                f"SAM 2 checkpoint not found: {self.checkpoint_path}. "
                "Run scripts/fetch_models.py first."
            )
        try:
            from sam2.build_sam import build_sam2_video_predictor
        except ModuleNotFoundError as exc:
            raise SAM2DependencyError(
                "The official SAM-2 package is required for video tracking"
            ) from exc

        profile = self.device_profile
        if profile.device == "cuda" and profile.compute_capability is not None:
            SAM2Engine._configure_cuda_attention(torch, profile)
        try:
            predictor = build_sam2_video_predictor(
                self.model_config,
                str(self.checkpoint_path),
                device=profile.device,
            )
        except Exception as exc:
            raise SAM2EngineError(f"Could not load SAM 2 video predictor: {exc}") from exc
        if (
            getattr(predictor, "fill_hole_area", 0) > 0
            and not _sam2_cuda_extension_available()
        ):
            predictor.fill_hole_area = 0
            logger.info(
                "SAM2 optional small-hole filling is disabled because sam2._C is unavailable"
            )
        self._predictor = predictor
        return self._predictor


@lru_cache(maxsize=None)
def get_sam2_engine(checkpoint_path: Path, model_config: str) -> SAM2Engine:
    """Return one lazy engine per checkpoint/configuration pair."""
    return SAM2Engine(Path(checkpoint_path), model_config)


@lru_cache(maxsize=None)
def get_sam2_video_engine(
    checkpoint_path: Path,
    model_config: str,
    *,
    offload_video_to_cpu: bool = False,
    offload_state_to_cpu: bool = False,
) -> SAM2VideoEngine:
    """Return one lazy video engine per model and offload configuration."""
    return SAM2VideoEngine(
        Path(checkpoint_path),
        model_config,
        offload_video_to_cpu=offload_video_to_cpu,
        offload_state_to_cpu=offload_state_to_cpu,
    )
