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
    on_progress: ExportProgress | None = None,
) -> Path:
    """Crop, resize, and encode a video while stream-copying source audio."""
    if not windows:
        raise ExportError("Crop plan cannot be empty")
    if output_width <= 0 or output_height <= 0:
        raise ExportError("Output dimensions must be positive")
    if output_width % 2 or output_height % 2:
        raise ExportError("Output dimensions must be even for yuv420p")
    if fps <= 0:
        raise ExportError("Frame rate must be positive")
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
    frame_index = 0

    try:
        with av.open(str(source_path), mode="r") as source, av.open(
            str(temporary), mode="w"
        ) as output:
            if not source.streams.video:
                raise ExportError("Source has no video stream")
            input_video = source.streams.video[0]
            input_audio = source.streams.audio[0] if source.streams.audio else None

            output_video = output.add_stream("libx264", rate=rate)
            output_video.width = output_width
            output_video.height = output_height
            output_video.pix_fmt = "yuv420p"
            output_video.options = {"crf": "18"}
            output_audio = (
                _add_audio_stream_from_template(output, input_audio)
                if input_audio is not None
                else None
            )

            streams = [input_video]
            if input_audio is not None:
                streams.append(input_audio)
            for packet in source.demux(streams):
                if input_audio is not None and packet.stream.index == input_audio.index:
                    if output_audio is not None and packet.dts is not None:
                        packet.stream = output_audio
                        output.mux(packet)
                    continue
                for decoded in packet.decode():
                    if frame_index >= len(windows):
                        continue
                    window = windows[frame_index]
                    if window.frame_idx != frame_index:
                        raise ExportError("Crop plan frame indices must be contiguous")
                    image = decoded.to_ndarray(format="bgr24")
                    crop = image[
                        window.y : window.y + window.height,
                        window.x : window.x + window.width,
                    ]
                    if crop.shape[:2] != (window.height, window.width):
                        raise ExportError(
                            f"Crop window for frame {frame_index} is outside the source"
                        )
                    resized = cv2.resize(
                        crop,
                        (output_width, output_height),
                        interpolation=cv2.INTER_LANCZOS4,
                    )
                    output_frame = av.VideoFrame.from_ndarray(
                        resized, format="bgr24"
                    )
                    output_frame.pts = frame_index
                    output_frame.time_base = Fraction(1, 1) / rate
                    for encoded in output_video.encode(output_frame):
                        output.mux(encoded)
                    frame_index += 1
                    if on_progress is not None:
                        on_progress(
                            frame_index / len(windows),
                            f"Exporting frame {frame_index} of {len(windows)}",
                        )

            for encoded in output_video.encode():
                output.mux(encoded)

        if frame_index != len(windows):
            raise ExportError(
                f"Expected {len(windows)} source frames, decoded {frame_index}"
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
