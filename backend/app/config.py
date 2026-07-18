from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    repo_root: Path
    data_dir: Path
    frontend_dist: Path
    checkpoints_dir: Path
    exports_dir: Path
    sam2_checkpoint: Path
    sam2_model_config: str
    sam2_crop_size: int = 1024
    sam2_offload_video_to_cpu: bool = False
    sam2_offload_state_to_cpu: bool = False
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    frame_cache_max_dimension: int = 2048
    tracking_max_dimension: int = 2048
    locate_model_id: str = "nvidia/LocateAnything-3B"
    locate_max_input_dimension: int = 2500
    locate_rescue_enabled: bool = True
    locate_rescue_after: int = 15
    locate_rescue_min_score: float = 0.5
    locate_revision: str = "c32291ca5e996f5a7a485845b4f57a233936bba0"
    allowed_hosts: tuple[str, ...] = ()
    max_upload_bytes: int = 20 * 1024**3
    max_export_width: int = 4096
    max_export_height: int = 2160
    max_export_pixels: int = 4096 * 2160


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def _env_positive_int(name: str, default: int) -> int:
    value = int(os.environ.get(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _env_csv(name: str) -> tuple[str, ...]:
    return tuple(
        item.strip().lower().rstrip(".")
        for item in os.environ.get(name, "").split(",")
        if item.strip()
    )


def load_settings() -> Settings:
    repo_root = Path(__file__).resolve().parents[2]
    data_dir = Path(os.environ.get("PLAYTRACK_DATA_DIR", repo_root / "data"))
    checkpoints_dir = Path(
        os.environ.get("PLAYTRACK_CHECKPOINTS_DIR", repo_root / "checkpoints")
    )
    sam2_checkpoint = Path(
        os.environ.get(
            "PLAYTRACK_SAM2_CHECKPOINT",
            checkpoints_dir / "sam2.1_hiera_base_plus.pt",
        )
    )
    return Settings(
        repo_root=repo_root,
        data_dir=data_dir,
        frontend_dist=repo_root / "frontend" / "dist",
        checkpoints_dir=checkpoints_dir,
        exports_dir=repo_root / "exports",
        sam2_checkpoint=sam2_checkpoint,
        sam2_model_config=os.environ.get(
            "PLAYTRACK_SAM2_CONFIG",
            "configs/sam2.1/sam2.1_hiera_b+.yaml",
        ),
        sam2_crop_size=int(os.environ.get("PLAYTRACK_SAM2_CROP_SIZE", "1024")),
        sam2_offload_video_to_cpu=_env_bool("SAM2_OFFLOAD_VIDEO_TO_CPU"),
        sam2_offload_state_to_cpu=_env_bool("SAM2_OFFLOAD_STATE_TO_CPU"),
        ffmpeg_binary=os.environ.get("PLAYTRACK_FFMPEG", "ffmpeg"),
        ffprobe_binary=os.environ.get("PLAYTRACK_FFPROBE", "ffprobe"),
        tracking_max_dimension=int(os.environ.get("TRACKING_MAX_DIM", "2048")),
        locate_model_id=os.environ.get(
            "PLAYTRACK_LOCATE_MODEL", "nvidia/LocateAnything-3B"
        ),
        locate_max_input_dimension=int(
            os.environ.get("LOCATE_MAX_INPUT_DIM", "2500")
        ),
        locate_rescue_enabled=_env_bool("LOCATE_RESCUE_ENABLED", True),
        locate_rescue_after=int(os.environ.get("LOCATE_RESCUE_AFTER", "15")),
        locate_rescue_min_score=float(
            os.environ.get("LOCATE_RESCUE_MIN_SCORE", "0.5")
        ),
        locate_revision=os.environ.get(
            "PLAYTRACK_LOCATE_REVISION",
            "c32291ca5e996f5a7a485845b4f57a233936bba0",
        ),
        allowed_hosts=_env_csv("PLAYTRACK_ALLOWED_HOSTS"),
        max_upload_bytes=_env_positive_int(
            "PLAYTRACK_MAX_UPLOAD_BYTES", 20 * 1024**3
        ),
        max_export_width=_env_positive_int("PLAYTRACK_MAX_EXPORT_WIDTH", 4096),
        max_export_height=_env_positive_int("PLAYTRACK_MAX_EXPORT_HEIGHT", 2160),
        max_export_pixels=_env_positive_int(
            "PLAYTRACK_MAX_EXPORT_PIXELS", 4096 * 2160
        ),
    )


settings = load_settings()
