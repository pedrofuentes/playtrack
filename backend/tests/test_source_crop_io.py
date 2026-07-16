from __future__ import annotations

from pathlib import Path

from app.videos import VideoStore


def test_extracts_and_caches_exact_source_crop(
    video_store: VideoStore, tiny_video: Path
) -> None:
    record = video_store.register_path(tiny_video)

    first = video_store.extract_source_crop(
        record.video_id,
        frame_idx=2,
        x=11,
        y=13,
        width=100,
        height=80,
    )
    first_mtime = first.path.stat().st_mtime_ns
    second = video_store.extract_source_crop(
        record.video_id,
        frame_idx=2,
        x=11,
        y=13,
        width=100,
        height=80,
    )

    assert (first.x, first.y, first.width, first.height) == (11, 13, 100, 80)
    assert first.path.suffix == ".png"
    assert first.path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert second.path == first.path
    assert second.path.stat().st_mtime_ns == first_mtime
