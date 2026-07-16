from __future__ import annotations

from pathlib import Path

from app.videos import VideoStore


def test_tracking_frames_use_a_separate_configurable_cache(
    tmp_path: Path, tiny_video: Path
) -> None:
    store = VideoStore(
        repo_root=tmp_path,
        data_dir=tmp_path / "data",
        frame_cache_max_dimension=80,
        tracking_max_dimension=160,
    )
    record = store.register_path(tiny_video)

    ui_frame = store.extract_frame(record.video_id, 0)
    tracking = store.prepare_tracking_frames(record.video_id)
    cached_again = store.prepare_tracking_frames(record.video_id)

    assert (ui_frame.width, ui_frame.height) == (80, 46)
    assert (tracking.width, tracking.height) == (160, 90)
    assert tracking.path != record.frame_cache_dir
    assert tracking.path.parent.name == record.video_id
    assert len(list(tracking.path.glob("*.jpg"))) == 4
    assert cached_again == tracking
