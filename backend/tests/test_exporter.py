from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

av = pytest.importorskip("av", reason="PyAV dependency is not installed")

from app.crop_planner import CropWindow
from app.exporter import ExportError, export_video


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
    path: Path,
    frame_count: int = 32,
    *,
    audio_start_seconds: float = 0.0,
    audio_end_seconds: float | None = None,
    audio_gap_seconds: tuple[float, float] | None = None,
) -> None:
    sample_rate = 48_000
    samples_per_frame = 1_024
    with av.open(str(path), mode="w") as container:
        video = container.add_stream("libx264", rate=Fraction(8, 1))
        video.width = 96
        video.height = 64
        video.pix_fmt = "yuv420p"
        video.gop_size = 8
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

        audio_start = round(audio_start_seconds * sample_rate)
        audio_end = round(
            (audio_end_seconds if audio_end_seconds is not None else frame_count / 8)
            * sample_rate
        )
        gap = (
            tuple(round(value * sample_rate) for value in audio_gap_seconds)
            if audio_gap_seconds is not None
            else None
        )
        frequencies = np.array([233, 347, 461, 613, 797], dtype=np.float64)
        cursor = audio_start
        while cursor < audio_end:
            if gap is not None and gap[0] <= cursor < gap[1]:
                cursor = gap[1]
                continue
            count = min(samples_per_frame, audio_end - cursor)
            if gap is not None and cursor < gap[0]:
                count = min(count, gap[0] - cursor)
            time = (np.arange(count, dtype=np.float64) + cursor) / sample_rate
            frequency = frequencies[
                np.minimum(np.floor(time).astype(int), len(frequencies) - 1)
            ]
            tone = np.round(np.sin(2 * np.pi * frequency * time) * 12_000).astype(np.int16)
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


def _decoded_mono_audio(path: Path) -> tuple[np.ndarray, int]:
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        rate = int(stream.rate)
        samples = np.concatenate(
            [frame.to_ndarray()[0] for frame in container.decode(stream)]
        )
    return samples, rate


def _dominant_frequency(samples: np.ndarray, sample_rate: int) -> float:
    centered = samples.astype(np.float64) - float(samples.mean())
    spectrum = np.abs(np.fft.rfft(centered * np.hanning(len(centered))))
    frequencies = np.fft.rfftfreq(len(centered), 1 / sample_rate)
    return float(frequencies[int(spectrum.argmax())])


def _audio_packet_payloads(path: Path) -> list[bytes]:
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        return [bytes(packet) for packet in container.demux(stream) if packet.size]


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
    source_start_frame = 9
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
        source_start_frame=source_start_frame,
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
    assert int(np.linalg.norm(source_colors - first_rgb, axis=1).argmin()) == 9
    assert int(np.linalg.norm(source_colors - last_rgb, axis=1).argmin()) == 24
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
    audio_samples, sample_rate = _decoded_mono_audio(destination)
    assert _dominant_frequency(
        audio_samples[round(0.02 * sample_rate) : round(0.10 * sample_rate)],
        sample_rate,
    ) == pytest.approx(347, abs=20)
    assert _dominant_frequency(
        audio_samples[round(1.91 * sample_rate) : round(1.99 * sample_rate)],
        sample_rate,
    ) == pytest.approx(613, abs=20)


def test_exports_partial_range_without_audio(tmp_path: Path) -> None:
    source = tmp_path / "silent-source.mp4"
    destination = tmp_path / "silent-subrange.mp4"
    _write_synthetic_video(source)
    windows = [
        CropWindow(frame_idx=index, x=0, y=0, width=96, height=64)
        for index in range(8)
    ]

    export_video(
        source,
        destination,
        windows,
        output_width=96,
        output_height=64,
        fps=8.0,
        source_start_frame=5,
        source_total_frames=32,
    )

    with av.open(str(destination)) as exported:
        assert len(list(exported.decode(exported.streams.video[0]))) == 8
        assert not exported.streams.audio


@pytest.mark.parametrize(
    "audio_options",
    [
        {"audio_start_seconds": 3.5},
        {"audio_start_seconds": 1.5},
        {"audio_end_seconds": 2.5},
        {"audio_gap_seconds": (1.75, 2.25)},
    ],
    ids=["no-overlap", "late-start", "early-end", "internal-gap"],
)
def test_rejects_incomplete_partial_audio_and_removes_temporary_output(
    tmp_path: Path, audio_options: dict[str, object]
) -> None:
    source = tmp_path / "incomplete-audio.mp4"
    destination = tmp_path / "incomplete-export.mp4"
    _write_synthetic_video_with_audio(source, **audio_options)
    windows = [
        CropWindow(frame_idx=index, x=0, y=0, width=96, height=64)
        for index in range(16)
    ]

    with pytest.raises(ExportError, match="audio.*selected interval"):
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

    assert not destination.exists()
    assert not destination.with_suffix(".part.mp4").exists()


def test_full_range_export_stream_copies_audio_packets(tmp_path: Path) -> None:
    source = tmp_path / "full-source.mp4"
    destination = tmp_path / "full-export.mp4"
    _write_synthetic_video_with_audio(source, frame_count=8)
    windows = [
        CropWindow(frame_idx=index, x=0, y=0, width=96, height=64)
        for index in range(8)
    ]

    export_video(
        source,
        destination,
        windows,
        output_width=96,
        output_height=64,
        fps=8.0,
        source_start_frame=0,
        source_total_frames=8,
    )

    assert _audio_packet_payloads(destination) == _audio_packet_payloads(source)


def test_partial_export_seeks_near_start_and_stops_demux_after_interval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "bounded-source.mp4"
    destination = tmp_path / "bounded-export.mp4"
    _write_synthetic_video_with_audio(source)
    real_open = av.open
    seek_offsets: list[int] = []
    demux_exhausted = False

    class InstrumentedInput:
        def __init__(self, container: object) -> None:
            self.container = container

        def __enter__(self) -> "InstrumentedInput":
            return self

        def __exit__(self, *args: object) -> None:
            self.container.close()

        def __getattr__(self, name: str) -> object:
            return getattr(self.container, name)

        def seek(self, offset: int, *args: object, **kwargs: object) -> None:
            seek_offsets.append(offset)
            self.container.seek(offset, *args, **kwargs)

        def demux(self, *streams: object) -> object:
            nonlocal demux_exhausted
            for packet in self.container.demux(*streams):
                yield packet
            demux_exhausted = True

    def instrumented_open(file: str, *args: object, **kwargs: object) -> object:
        container = real_open(file, *args, **kwargs)
        if Path(file) == source and kwargs.get("mode") == "r":
            return InstrumentedInput(container)
        return container

    monkeypatch.setattr(av, "open", instrumented_open)
    windows = [
        CropWindow(frame_idx=index, x=0, y=0, width=96, height=64)
        for index in range(8)
    ]

    export_video(
        source,
        destination,
        windows,
        output_width=96,
        output_height=64,
        fps=8.0,
        source_start_frame=16,
        source_total_frames=32,
    )

    assert seek_offsets and seek_offsets[0] > 0
    assert demux_exhausted is False
    with real_open(str(destination)) as exported:
        frames = list(exported.decode(exported.streams.video[0]))
    assert len(frames) == 8
    assert frames[0].pts == 0


def test_accepts_codec_frame_audio_boundary_mismatch_with_zero_based_pts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "codec-boundary-source.mp4"
    destination = tmp_path / "codec-boundary-export.mp4"
    _write_synthetic_video_with_audio(
        source,
        audio_gap_seconds=(1, 1 + 512 / 48_000),
    )
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
        stream = exported.streams.audio[0]
        frames = list(exported.decode(stream))
    assert frames[0].pts == 0
    assert sum(frame.samples for frame in frames) / stream.rate == pytest.approx(
        2.0, abs=1_024 / 48_000
    )
