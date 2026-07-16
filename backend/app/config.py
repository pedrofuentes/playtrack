from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    repo_root: Path
    data_dir: Path
    frontend_dist: Path
    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    frame_cache_max_dimension: int = 2048


def load_settings() -> Settings:
    repo_root = Path(__file__).resolve().parents[2]
    data_dir = Path(os.environ.get("FINDME_DATA_DIR", repo_root / "data"))
    return Settings(
        repo_root=repo_root,
        data_dir=data_dir,
        frontend_dist=repo_root / "frontend" / "dist",
        ffmpeg_binary=os.environ.get("FINDME_FFMPEG", "ffmpeg"),
        ffprobe_binary=os.environ.get("FINDME_FFPROBE", "ffprobe"),
    )


settings = load_settings()

