from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Callable, Sequence

from .crop_planner import CropWindow


class ExportError(RuntimeError):
    """Raised when a planned video export cannot be completed."""


ExportProgress = Callable[[float, str], None]


def export_video(
    source_path: Path,
    destination: Path,
    windows: Sequence[CropWindow],
    *,
    output_width: int,
    output_height: int,
    fps: float,
    source_start_frame: int = 0,
    source_total_frames: int | None = None,
    on_progress: ExportProgress | None = None,
) -> Path:
    """Crop, resize, and encode a bounded source interval."""
    if not windows:
        raise ExportError("Crop plan cannot be empty")
    if output_width <= 0 or output_height <= 0:
        raise ExportError("Output dimensions must be positive")
    if output_width % 2 or output_height % 2:
        raise ExportError("Output dimensions must be even for yuv420p")
    if fps <= 0:
        raise ExportError("Frame rate must be positive")
    if source_start_frame < 0:
        raise ExportError("Source start frame cannot be negative")
    if source_total_frames is not None:
        if source_total_frames <= 0:
            raise ExportError("Source frame count must be positive")
        if source_start_frame + len(windows) > source_total_frames:
            raise ExportError("Crop plan extends beyond the source frame range")
    if not Path(source_path).is_file():
        raise ExportError(f"Source video not found: {source_path}")

    try:
        import av
        import cv2
    except ModuleNotFoundError as exc:
        raise ExportError("PyAV and OpenCV are required for video export") from exc

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".part.mp4")
    temporary.unlink(missing_ok=True)
    rate = Fraction(str(fps)).limit_denominator(100_000)
    source_frame_index = 0
    output_frame_index = 0

    try:
        with av.open(str(source_path), mode="r") as source, av.open(
            str(temporary), mode="w"
        ) as output:
            if not source.streams.video:
                raise ExportError("Source has no video stream")
            input_video = source.streams.video[0]
            input_audio = source.streams.audio[0] if source.streams.audio else None
            total_source_frames = source_total_frames or input_video.frames or None
            copy_audio = (
                input_audio is not None
                and source_start_frame == 0
                and total_source_frames is not None
                and len(windows) == total_source_frames
            )

            output_video = output.add_stream("libx264", rate=rate)
            output_video.width = output_width
            output_video.height = output_height
            output_video.pix_fmt = "yuv420p"
            output_video.options = {"crf": "18"}
            if input_audio is None:
                output_audio = None
            elif copy_audio:
                output_audio = _add_audio_stream_from_template(output, input_audio)
            else:
                output_audio = _add_aac_stream(output, input_audio)

            audio_start = Fraction(source_start_frame, 1) / rate
            audio_end = Fraction(source_start_frame + len(windows), 1) / rate
            audio_fallback_time = Fraction(0, 1)
            audio_samples_written = 0

            streams = [input_video]
            if input_audio is not None:
                streams.append(input_audio)
            for packet in source.demux(streams):
                if input_audio is not None and packet.stream.index == input_audio.index:
                    if copy_audio and output_audio is not None and packet.dts is not None:
                        packet.stream = output_audio
                        output.mux(packet)
                    elif output_audio is not None:
                        for decoded in packet.decode():
                            sample_rate = decoded.sample_rate
                            if sample_rate is None or sample_rate <= 0:
                                raise ExportError("Source audio has no sample rate")
                            frame_time_base = decoded.time_base or Fraction(
                                1, sample_rate
                            )
                            frame_start = (
                                Fraction(decoded.pts) * frame_time_base
                                if decoded.pts is not None
                                else audio_fallback_time
                            )
                            frame_end = frame_start + Fraction(
                                decoded.samples, sample_rate
                            )
                            audio_fallback_time = frame_end
                            start_sample = max(
                                0,
                                _ceil_fraction(
                                    (audio_start - frame_start) * sample_rate
                                ),
                            )
                            end_sample = min(
                                decoded.samples,
                                _ceil_fraction(
                                    (audio_end - frame_start) * sample_rate
                                ),
                            )
                            if end_sample <= start_sample:
                                continue
                            trimmed = _slice_audio_frame(
                                decoded, start_sample, end_sample
                            )
                            trimmed.pts = audio_samples_written
                            trimmed.time_base = Fraction(1, sample_rate)
                            audio_samples_written += trimmed.samples
                            for encoded in output_audio.encode(trimmed):
                                output.mux(encoded)
                    continue
                for decoded in packet.decode():
                    if source_frame_index < source_start_frame:
                        source_frame_index += 1
                        continue
                    if output_frame_index >= len(windows):
                        source_frame_index += 1
                        continue
                    window = windows[output_frame_index]
                    if window.frame_idx != output_frame_index:
                        raise ExportError("Crop plan frame indices must be contiguous")
                    image = decoded.to_ndarray(format="bgr24")
                    crop = cv2.getRectSubPix(
                        image,
                        (window.width, window.height),
                        (float(window.cx), float(window.cy)),
                    )
                    if crop.shape[:2] != (window.height, window.width):
                        raise ExportError(
                            f"Crop window for frame {output_frame_index} is outside the source"
                        )
                    resized = cv2.resize(
                        crop,
                        (output_width, output_height),
                        interpolation=cv2.INTER_LANCZOS4,
                    )
                    output_frame = av.VideoFrame.from_ndarray(
                        resized, format="bgr24"
                    )
                    output_frame.pts = output_frame_index
                    output_frame.time_base = Fraction(1, 1) / rate
                    for encoded in output_video.encode(output_frame):
                        output.mux(encoded)
                    source_frame_index += 1
                    output_frame_index += 1
                    if on_progress is not None:
                        on_progress(
                            output_frame_index / len(windows),
                            f"Exporting frame {output_frame_index} of {len(windows)}",
                        )

            for encoded in output_video.encode():
                output.mux(encoded)
            if output_audio is not None and not copy_audio:
                for encoded in output_audio.encode():
                    output.mux(encoded)

        if output_frame_index != len(windows):
            raise ExportError(
                f"Expected {len(windows)} source frames, decoded {output_frame_index}"
            )
        temporary.replace(destination)
        return destination
    except ExportError:
        temporary.unlink(missing_ok=True)
        raise
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise ExportError(f"Could not export video: {exc}") from exc


def _add_audio_stream_from_template(output: object, input_audio: object) -> object:
    add_from_template = getattr(output, "add_stream_from_template", None)
    if add_from_template is not None:
        return add_from_template(input_audio)
    return output.add_stream(template=input_audio)


def _add_aac_stream(output: object, input_audio: object) -> object:
    sample_rate = input_audio.codec_context.sample_rate
    if sample_rate is None or sample_rate <= 0:
        raise ExportError("Source audio has no sample rate")
    stream = output.add_stream("aac", rate=sample_rate)
    layout = input_audio.codec_context.layout
    if layout is not None:
        stream.layout = layout.name
    return stream


def _slice_audio_frame(frame: object, start: int, end: int) -> object:
    import av

    array = frame.to_ndarray()
    if frame.format.is_planar:
        array = array[:, start:end]
    else:
        channel_count = len(frame.layout.channels)
        array = array[:, start * channel_count : end * channel_count]
    trimmed = av.AudioFrame.from_ndarray(
        array, format=frame.format.name, layout=frame.layout.name
    )
    trimmed.sample_rate = frame.sample_rate
    return trimmed


def _ceil_fraction(value: Fraction) -> int:
    return -(-value.numerator // value.denominator)
