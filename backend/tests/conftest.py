from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.videos import VideoStore


@pytest.fixture(scope="session", autouse=True)
def require_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg and ffprobe are required for video I/O tests")


@pytest.fixture
def tiny_video(tmp_path: Path) -> Path:
    output = tmp_path / "tiny.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=10:duration=0.4",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output),
        ],
        check=True,
    )
    return output


@pytest.fixture
def video_store(tmp_path: Path) -> VideoStore:
    return VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")


@pytest.fixture
def client(video_store: VideoStore) -> TestClient:
    with TestClient(create_app(video_store)) as test_client:
        yield test_client


@pytest.fixture
def registered_video(client: TestClient, tiny_video: Path) -> dict[str, object]:
    response = client.post("/api/videos", json={"path": str(tiny_video)})
    assert response.status_code == 201
    return response.json()

