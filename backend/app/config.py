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
    sam2_checkpoint: Path
    sam2_model_config: str
    sam2_crop_size: int = 1024
    sam2_offload_video_to_cpu: bool = False
    sam2_offload_state_to_cpu: bool = False
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    frame_cache_max_dimension: int = 2048
    tracking_max_dimension: int = 2048


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


def load_settings() -> Settings:
    repo_root = Path(__file__).resolve().parents[2]
    data_dir = Path(os.environ.get("FINDME_DATA_DIR", repo_root / "data"))
    checkpoints_dir = Path(
        os.environ.get("FINDME_CHECKPOINTS_DIR", repo_root / "checkpoints")
    )
    sam2_checkpoint = Path(
        os.environ.get(
            "FINDME_SAM2_CHECKPOINT",
            checkpoints_dir / "sam2.1_hiera_base_plus.pt",
        )
    )
    return Settings(
        repo_root=repo_root,
        data_dir=data_dir,
        frontend_dist=repo_root / "frontend" / "dist",
        checkpoints_dir=checkpoints_dir,
        sam2_checkpoint=sam2_checkpoint,
        sam2_model_config=os.environ.get(
            "FINDME_SAM2_CONFIG",
            "configs/sam2.1/sam2.1_hiera_b+.yaml",
        ),
        sam2_crop_size=int(os.environ.get("FINDME_SAM2_CROP_SIZE", "1024")),
        sam2_offload_video_to_cpu=_env_bool("SAM2_OFFLOAD_VIDEO_TO_CPU"),
        sam2_offload_state_to_cpu=_env_bool("SAM2_OFFLOAD_STATE_TO_CPU"),
        ffmpeg_binary=os.environ.get("FINDME_FFMPEG", "ffmpeg"),
        ffprobe_binary=os.environ.get("FINDME_FFPROBE", "ffprobe"),
        tracking_max_dimension=int(os.environ.get("TRACKING_MAX_DIM", "2048")),
    )


settings = load_settings()
