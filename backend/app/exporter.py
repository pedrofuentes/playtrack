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
            audio_codec_frame_samples = max(
                1,
                input_audio.codec_context.frame_size if input_audio is not None else 1,
            )
            audio_fallback_time = Fraction(0, 1)
            audio_coverage_end = audio_start
            audio_output_end_pts: int | None = None
            decoded_audio_rate: int | None = None
            audio_frame_template: object | None = None

            streams = [input_video]
            if input_audio is not None:
                streams.append(input_audio)
            if source_start_frame > 0:
                video_time_base = Fraction(input_video.time_base)
                stream_start = input_video.start_time or 0
                seek_offset = stream_start + int(
                    (Fraction(source_start_frame, 1) / rate) / video_time_base
                )
                source.seek(
                    seek_offset,
                    stream=input_video,
                    backward=True,
                    any_frame=False,
                )
            demux_exhausted = False
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
                            if (
                                decoded_audio_rate is not None
                                and sample_rate != decoded_audio_rate
                            ):
                                raise ExportError("Source audio sample rate changed")
                            decoded_audio_rate = sample_rate
                            audio_frame_template = decoded
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
                            overlap_start = max(frame_start, audio_start)
                            overlap_end = min(frame_end, audio_end)
                            if overlap_end <= overlap_start:
                                continue
                            tolerance = Fraction(1, sample_rate)
                            if overlap_start > audio_coverage_end + tolerance:
                                boundary_gap = overlap_start - audio_coverage_end
                                if (
                                    audio_output_end_pts is None
                                    and
                                    boundary_gap
                                    <= Fraction(audio_codec_frame_samples, sample_rate)
                                ):
                                    missing_samples = _round_fraction(
                                        boundary_gap * sample_rate
                                    )
                                    silence = _silence_audio_frame_like(
                                        decoded, missing_samples
                                    )
                                    silence.pts = audio_output_end_pts or 0
                                    silence.time_base = Fraction(1, sample_rate)
                                    for encoded in output_audio.encode(silence):
                                        output.mux(encoded)
                                    audio_output_end_pts = (
                                        audio_output_end_pts or 0
                                    ) + missing_samples
                                    audio_coverage_end = overlap_start
                                else:
                                    raise ExportError(
                                        "Source audio does not cover selected interval"
                                    )
                            uncovered_start = max(
                                overlap_start, audio_coverage_end
                            )
                            start_sample = max(
                                0,
                                _ceil_fraction(
                                    (uncovered_start - frame_start) * sample_rate
                                ),
                            )
                            end_sample = min(
                                decoded.samples,
                                _ceil_fraction(
                                    (overlap_end - frame_start) * sample_rate
                                ),
                            )
                            if end_sample <= start_sample:
                                continue
                            trimmed_source_start = frame_start + Fraction(
                                start_sample, sample_rate
                            )
                            trimmed_source_end = frame_start + Fraction(
                                end_sample, sample_rate
                            )
                            if (
                                trimmed_source_start
                                > audio_coverage_end + tolerance
                            ):
                                raise ExportError(
                                    "Source audio does not cover selected interval"
                                )
                            output_start_pts = _round_fraction(
                                (trimmed_source_start - audio_start)
                                * sample_rate
                            )
                            if audio_output_end_pts is not None:
                                if output_start_pts < audio_output_end_pts:
                                    duplicate_samples = (
                                        audio_output_end_pts - output_start_pts
                                    )
                                    start_sample += duplicate_samples
                                    if end_sample <= start_sample:
                                        continue
                                    trimmed_source_start += Fraction(
                                        duplicate_samples, sample_rate
                                    )
                                    output_start_pts = audio_output_end_pts
                                elif output_start_pts > audio_output_end_pts + 1:
                                    raise ExportError(
                                        "Source audio does not cover selected interval"
                                    )
                            trimmed = _slice_audio_frame(
                                decoded, start_sample, end_sample
                            )
                            trimmed.pts = output_start_pts
                            trimmed.time_base = Fraction(1, sample_rate)
                            audio_output_end_pts = output_start_pts + trimmed.samples
                            audio_coverage_end = max(
                                audio_coverage_end, trimmed_source_end
                            )
                            for encoded in output_audio.encode(trimmed):
                                output.mux(encoded)
                    if output_frame_index >= len(windows) and (
                        not copy_audio and audio_coverage_end >= audio_end
                    ):
                        break
                    continue
                for decoded in packet.decode():
                    decoded_source_index = _decoded_video_frame_index(
                        decoded, input_video, rate, source_frame_index
                    )
                    source_frame_index = decoded_source_index + 1
                    expected_source_index = (
                        source_start_frame + output_frame_index
                    )
                    if decoded_source_index < expected_source_index:
                        continue
                    if output_frame_index >= len(windows):
                        continue
                    if decoded_source_index > expected_source_index:
                        raise ExportError(
                            f"Source frame {expected_source_index} was not decoded"
                        )
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
                    output_frame_index += 1
                    if on_progress is not None:
                        on_progress(
                            output_frame_index / len(windows),
                            f"Exporting frame {output_frame_index} of {len(windows)}",
                        )
                if output_frame_index >= len(windows) and input_audio is None:
                    break
            else:
                demux_exhausted = True

            for encoded in output_video.encode():
                output.mux(encoded)
            if output_audio is not None and not copy_audio:
                audio_rate = decoded_audio_rate or output_audio.codec_context.sample_rate
                if audio_rate is None or audio_rate <= 0:
                    raise ExportError("Source audio has no sample rate")
                tolerance = Fraction(audio_codec_frame_samples, audio_rate)
                if audio_coverage_end < audio_end - tolerance:
                    raise ExportError(
                        "Source audio does not cover selected interval"
                    )
                expected_end_pts = _round_fraction(
                    (audio_end - audio_start) * audio_rate
                )
                missing_end_samples = expected_end_pts - (
                    audio_output_end_pts or 0
                )
                if (
                    0 < missing_end_samples <= audio_codec_frame_samples
                    and audio_frame_template is not None
                    and demux_exhausted
                ):
                    silence = _silence_audio_frame_like(
                        audio_frame_template, missing_end_samples
                    )
                    silence.pts = audio_output_end_pts
                    silence.time_base = Fraction(1, audio_rate)
                    for encoded in output_audio.encode(silence):
                        output.mux(encoded)
                    audio_output_end_pts = expected_end_pts
                    audio_coverage_end = audio_end
                if (
                    audio_output_end_pts is None
                    or abs(audio_output_end_pts - expected_end_pts)
                    > audio_codec_frame_samples
                ):
                    raise ExportError(
                        "Source audio does not cover selected interval"
                    )
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


def _silence_audio_frame_like(frame: object, sample_count: int) -> object:
    import av
    import numpy as np

    array = frame.to_ndarray()
    channel_count = len(frame.layout.channels)
    width = sample_count if frame.format.is_planar else sample_count * channel_count
    silence = np.zeros_like(array[:, :width])
    result = av.AudioFrame.from_ndarray(
        silence, format=frame.format.name, layout=frame.layout.name
    )
    result.sample_rate = frame.sample_rate
    return result


def _ceil_fraction(value: Fraction) -> int:
    return -(-value.numerator // value.denominator)


def _round_fraction(value: Fraction) -> int:
    quotient, remainder = divmod(value.numerator, value.denominator)
    return quotient + int(remainder * 2 >= value.denominator)


def _decoded_video_frame_index(
    frame: object,
    stream: object,
    rate: Fraction,
    fallback_index: int,
) -> int:
    if frame.pts is None:
        return fallback_index
    stream_start = stream.start_time or 0
    source_time = Fraction(frame.pts - stream_start) * Fraction(frame.time_base)
    return _round_fraction(source_time * rate)
