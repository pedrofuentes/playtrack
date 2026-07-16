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
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    frame_cache_max_dimension: int = 2048


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
        ffmpeg_binary=os.environ.get("FINDME_FFMPEG", "ffmpeg"),
        ffprobe_binary=os.environ.get("FINDME_FFPROBE", "ffprobe"),
    )


settings = load_settings()
