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


def _write_synthetic_video_with_audio(
    path: Path, frame_count: int = 32
) -> None:
    sample_rate = 48_000
    samples_per_frame = 1_024
    with av.open(str(path), mode="w") as container:
        video = container.add_stream("libx264", rate=Fraction(8, 1))
        video.width = 96
        video.height = 64
        video.pix_fmt = "yuv420p"
        audio = container.add_stream("aac", rate=sample_rate)
        audio.layout = "mono"

        for frame_idx in range(frame_count):
            image = np.empty((64, 96, 3), dtype=np.uint8)
            image[:, :] = (16 + frame_idx * 7, 40, 80)
            frame = av.VideoFrame.from_ndarray(image, format="rgb24")
            frame.pts = frame_idx
            frame.time_base = Fraction(1, 8)
            for packet in video.encode(frame):
                container.mux(packet)
        for packet in video.encode():
            container.mux(packet)

        sample_count = frame_count * sample_rate // 8
        cursor = 0
        while cursor < sample_count:
            count = min(samples_per_frame, sample_count - cursor)
            time = (np.arange(count, dtype=np.float64) + cursor) / sample_rate
            tone = np.round(np.sin(2 * np.pi * 440 * time) * 12_000).astype(
                np.int16
            )
            frame = av.AudioFrame.from_ndarray(
                tone.reshape(1, -1), format="s16", layout="mono"
            )
            frame.sample_rate = sample_rate
            frame.pts = cursor
            frame.time_base = Fraction(1, sample_rate)
            for packet in audio.encode(frame):
                container.mux(packet)
            cursor += count
        for packet in audio.encode():
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


def test_exports_subpixel_crop_windows_without_changing_output_shape(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.mp4"
    destination = tmp_path / "subpixel.mp4"
    _write_synthetic_video(source, frame_count=8)
    windows = [
        CropWindow(
            frame_idx=index,
            x=16,
            y=0,
            width=64,
            height=64,
            cx=48.25 + index * 0.2,
            cy=32.0,
        )
        for index in range(8)
    ]

    export_video(
        source,
        destination,
        windows,
        output_width=48,
        output_height=32,
        fps=8.0,
    )

    with av.open(str(destination)) as exported:
        stream = exported.streams.video[0]
        frames = list(exported.decode(stream))
    assert (stream.width, stream.height) == (48, 32)
    assert len(frames) == 8


def test_exports_subrange_and_trims_audio_to_matching_rebased_interval(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source-with-audio.mp4"
    destination = tmp_path / "subrange.mp4"
    _write_synthetic_video_with_audio(source)
    windows = [
        CropWindow(frame_idx=index, x=0, y=0, width=96, height=64)
        for index in range(16)
    ]

    export_video(
        source,
        destination,
        windows,
        output_width=96,
        output_height=64,
        fps=8.0,
        source_start_frame=8,
        source_total_frames=32,
    )

    with av.open(str(destination)) as exported:
        video_stream = exported.streams.video[0]
        audio_stream = exported.streams.audio[0]
        video_frames = list(exported.decode(video_stream))
    with av.open(str(destination)) as exported:
        audio_frames = list(exported.decode(exported.streams.audio[0]))
    with av.open(str(source)) as source_container:
        source_frames = list(source_container.decode(source_container.streams.video[0]))

    assert len(video_frames) == 16
    first_rgb = video_frames[0].to_ndarray(format="rgb24").mean(axis=(0, 1))
    last_rgb = video_frames[-1].to_ndarray(format="rgb24").mean(axis=(0, 1))
    source_colors = np.array(
        [frame.to_ndarray(format="rgb24").mean(axis=(0, 1)) for frame in source_frames]
    )
    assert int(np.linalg.norm(source_colors - first_rgb, axis=1).argmin()) == 8
    assert int(np.linalg.norm(source_colors - last_rgb, axis=1).argmin()) == 23
    assert float(video_frames[0].pts * video_frames[0].time_base) == pytest.approx(
        0.0, abs=1 / 8
    )
    assert audio_frames
    assert float(audio_frames[0].pts * audio_frames[0].time_base) == pytest.approx(
        0.0, abs=1_024 / 48_000
    )
    video_duration = len(video_frames) / 8
    audio_duration = sum(frame.samples for frame in audio_frames) / audio_stream.rate
    assert video_duration == pytest.approx(2.0, abs=1 / 8)
    assert audio_duration == pytest.approx(2.0, abs=1_024 / 48_000)
