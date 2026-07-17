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


def test_tracking_frame_range_extracts_only_selected_source_frames(
    tmp_path: Path, tiny_video: Path
) -> None:
    store = VideoStore(
        repo_root=tmp_path,
        data_dir=tmp_path / "data",
        tracking_max_dimension=160,
    )
    record = store.register_path(tiny_video)

    sequence = store.prepare_tracking_frames(
        record.video_id,
        start_frame_idx=1,
        end_frame_exclusive=4,
    )

    assert sequence.start_frame_idx == 1
    assert sequence.frame_count == 3
    assert len(list(sequence.path.glob("*.jpg"))) == 3
    assert "range-1-4" in sequence.path.name


def test_tracking_frame_limit_caps_range_from_selected_start(
    tmp_path: Path, tiny_video: Path
) -> None:
    store = VideoStore(repo_root=tmp_path, data_dir=tmp_path / "data")
    record = store.register_path(tiny_video)

    sequence = store.prepare_tracking_frames(
        record.video_id,
        start_frame_idx=1,
        end_frame_exclusive=4,
        frame_limit=2,
    )

    assert sequence.start_frame_idx == 1
    assert sequence.frame_count == 2
    assert "range-1-3" in sequence.path.name
