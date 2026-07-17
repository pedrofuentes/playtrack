from __future__ import annotations

import gc
import re
import threading
from contextlib import nullcontext
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Sequence


DEFAULT_MODEL_ID = "nvidia/LocateAnything-3B"


class LocateAnythingError(RuntimeError):
    """Base error for LocateAnything loading and inference."""


class LocateAnythingUnavailableError(LocateAnythingError):
    """Raised when CUDA or the optional Transformers dependency is unavailable."""


@dataclass(frozen=True, slots=True)
class LocateDeviceProfile:
    enabled: bool
    dtype: str | None
    attention: str | None
    reason: str
    compute_capability: tuple[int, int] | None = None


@dataclass(frozen=True, slots=True)
class LocateCandidate:
    box: tuple[int, int, int, int]
    score: float


def detect_locate_device(torch_module: Any | None = None) -> LocateDeviceProfile:
    """Return the CUDA-only LocateAnything profile from the project matrix."""
    if torch_module is None:
        try:
            import torch as torch_module
        except ModuleNotFoundError:
            return LocateDeviceProfile(
                False,
                None,
                None,
                "LocateAnything requires PyTorch with an NVIDIA CUDA GPU",
            )

    if not torch_module.cuda.is_available():
        return LocateDeviceProfile(
            False,
            None,
            None,
            "LocateAnything requires an NVIDIA CUDA GPU; it is disabled on MPS/CPU",
        )
    capability = tuple(torch_module.cuda.get_device_capability())
    dtype = "bfloat16" if capability[0] >= 8 else "float16"
    return LocateDeviceProfile(True, dtype, "sdpa", "", capability)


def parse_boxes(
    answer: str, image_width: int, image_height: int
) -> list[tuple[int, int, int, int]]:
    """Parse LocateAnything's normalized 0-1000 box tokens into pixel XYXY."""
    if image_width <= 0 or image_height <= 0:
        raise ValueError("Image dimensions must be positive")
    boxes: list[tuple[int, int, int, int]] = []
    pattern = r"<box>\s*<(\d+)>\s*<(\d+)>\s*<(\d+)>\s*<(\d+)>\s*</box>"
    for match in re.finditer(pattern, answer):
        normalized = [max(0, min(1000, int(value))) for value in match.groups()]
        x1 = round(normalized[0] / 1000 * image_width)
        y1 = round(normalized[1] / 1000 * image_height)
        x2 = round(normalized[2] / 1000 * image_width)
        y2 = round(normalized[3] / 1000 * image_height)
        x1, x2 = sorted((max(0, x1), min(image_width, x2)))
        y1, y2 = sorted((max(0, y1), min(image_height, y2)))
        if x1 < x2 and y1 < y2:
            boxes.append((x1, y1, x2, y2))
    return boxes


class LocateAnythingEngine:
    """Serialized, lazy LocateAnything worker with explicit VRAM release."""

    def __init__(self, model_id: str = DEFAULT_MODEL_ID) -> None:
        self.model_id = model_id
        self._model: Any | None = None
        self._tokenizer: Any | None = None
        self._processor: Any | None = None
        self._profile: LocateDeviceProfile | None = None
        self._lock = threading.RLock()

    @property
    def is_loaded(self) -> bool:
        with self._lock:
            return self._model is not None

    @property
    def device_profile(self) -> LocateDeviceProfile:
        with self._lock:
            if self._profile is None:
                self._profile = detect_locate_device()
            return self._profile

    @property
    def available(self) -> bool:
        profile = self.device_profile
        if not profile.enabled:
            return False
        try:
            self._import_transformers()
        except LocateAnythingUnavailableError:
            return False
        return True

    @property
    def unavailable_reason(self) -> str:
        profile = self.device_profile
        if not profile.enabled:
            return profile.reason
        try:
            self._import_transformers()
        except LocateAnythingUnavailableError as exc:
            return str(exc)
        return ""

    def ground_text(self, image: Any, prompt: str) -> list[LocateCandidate]:
        """Ground all instances matching a natural-language description."""
        question = (
            "Locate all the instances that match the following description: "
            f"{prompt}."
        )
        answer = self._predict(image, question)
        return self._candidates(answer, image.size)

    def detect_visual_prompt(
        self,
        image: Any,
        *,
        visual_prompt: Any,
    ) -> list[LocateCandidate]:
        """Find objects matching a reference crop using the upstream prompt format."""
        answer = self._predict(
            image,
            "Detect all the objects in the image that belong to the category set: .",
            visual_prompt=visual_prompt,
        )
        return self._candidates(answer, image.size)

    def unload(self) -> None:
        """Drop all model objects and return cached allocations to CUDA."""
        with self._lock:
            self._model = None
            self._tokenizer = None
            self._processor = None
            gc.collect()
            torch = self._import_torch()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def _predict(
        self,
        image: Any,
        question: str,
        *,
        visual_prompt: Any | None = None,
    ) -> str:
        with self._lock:
            torch = self._import_torch()
            model, tokenizer, processor = self._ensure_loaded(torch)
            content: list[dict[str, object]] = [
                {"type": "image", "image": image.convert("RGB")},
                {"type": "text", "text": question},
            ]
            if visual_prompt is not None:
                content.append(
                    {"type": "image", "image": visual_prompt.convert("RGB")}
                )
            messages = [{"role": "user", "content": content}]
            text = processor.py_apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
            images, videos = processor.process_vision_info(messages)
            inputs = processor(
                text=[text], images=images, videos=videos, return_tensors="pt"
            ).to("cuda")
            pixel_values = inputs["pixel_values"].to(
                getattr(torch, self.device_profile.dtype)
            )
            context = (
                torch.inference_mode()
                if hasattr(torch, "inference_mode")
                else nullcontext()
            )
            with context:
                response = model.generate(
                    pixel_values=pixel_values,
                    input_ids=inputs["input_ids"],
                    attention_mask=inputs["attention_mask"],
                    image_grid_hws=inputs.get("image_grid_hws"),
                    tokenizer=tokenizer,
                    max_new_tokens=2048,
                    use_cache=True,
                    generation_mode="hybrid",
                    temperature=0.7,
                    do_sample=True,
                    top_p=0.9,
                    top_k=None,
                    repetition_penalty=1.1,
                    verbose=False,
                )
            answer = response[0] if isinstance(response, tuple) else response
            return str(answer)

    def _ensure_loaded(self, torch: Any) -> tuple[Any, Any, Any]:
        if self._model is not None:
            return self._model, self._tokenizer, self._processor
        profile = self.device_profile
        if not profile.enabled:
            raise LocateAnythingUnavailableError(profile.reason)
        AutoModel, AutoTokenizer, AutoProcessor = self._import_transformers()
        dtype = getattr(torch, profile.dtype)
        try:
            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model_id, trust_remote_code=True
            )
            self._processor = AutoProcessor.from_pretrained(
                self.model_id, trust_remote_code=True
            )
            self._model = AutoModel.from_pretrained(
                self.model_id,
                trust_remote_code=True,
                torch_dtype=dtype,
                attn_implementation=profile.attention,
            ).to("cuda").eval()
        except Exception as exc:
            self._model = None
            self._tokenizer = None
            self._processor = None
            raise LocateAnythingError(f"Could not load LocateAnything: {exc}") from exc
        return self._model, self._tokenizer, self._processor

    @staticmethod
    def _candidates(answer: str, size: Sequence[int]) -> list[LocateCandidate]:
        width, height = int(size[0]), int(size[1])
        # LocateAnything's public worker does not expose calibrated confidences.
        return [
            LocateCandidate(box=box, score=1.0)
            for box in parse_boxes(answer, width, height)
        ]

    @staticmethod
    def _import_torch() -> Any:
        try:
            import torch
        except ImportError as exc:
            raise LocateAnythingUnavailableError(
                "LocateAnything requires PyTorch with CUDA support"
            ) from exc
        return torch

    @staticmethod
    def _import_transformers() -> tuple[Any, Any, Any]:
        try:
            from transformers import AutoModel, AutoProcessor, AutoTokenizer
        except ImportError as exc:
            raise LocateAnythingUnavailableError(
                "LocateAnything is not installed; run `uv sync --extra locate` on a CUDA host"
            ) from exc
        return AutoModel, AutoTokenizer, AutoProcessor


@lru_cache(maxsize=None)
def get_locate_engine(model_id: str = DEFAULT_MODEL_ID) -> LocateAnythingEngine:
    """Return the process-wide lazy LocateAnything worker."""
    return LocateAnythingEngine(model_id)
