from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

av = pytest.importorskip("av", reason="PyAV dependency is not installed")

from app.crop_planner import CropWindow
from app.exporter import export_video


def _write_synthetic_video(path: Path, frame_count: int = 32) -> None:
    with av.open(str(path), mode="w") as container:
        stream = container.add_stream("libx264", rate=Fraction(8, 1))
        stream.width = 96
        stream.height = 64
        stream.pix_fmt = "yuv420p"
        for frame_idx in range(frame_count):
            image = np.zeros((64, 96, 3), dtype=np.uint8)
            x = min(frame_idx * 2, 76)
            image[20:40, x : x + 20] = (255, 255, 255)
            frame = av.VideoFrame.from_ndarray(image, format="rgb24")
            frame.pts = frame_idx
            frame.time_base = Fraction(1, 8)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def test_exports_planned_crops_with_expected_dimensions_and_frame_count(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    destination = tmp_path / "export.mp4"
    _write_synthetic_video(source)
    windows = [
        CropWindow(frame_idx=index, x=16, y=0, width=64, height=64)
        for index in range(32)
    ]
    progress: list[float] = []

    export_video(
        source,
        destination,
        windows,
        output_width=48,
        output_height=32,
        fps=8.0,
        on_progress=lambda value, _message: progress.append(value),
    )

    with av.open(str(destination)) as exported:
        stream = exported.streams.video[0]
        frames = list(exported.decode(stream))

    assert (stream.width, stream.height) == (48, 32)
    assert len(frames) == 32
    assert progress[-1] == 1.0
