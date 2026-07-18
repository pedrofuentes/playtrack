from __future__ import annotations

from pathlib import Path

from app.config import load_settings


def test_tracking_settings_read_resolution_and_offload_flags(monkeypatch: object) -> None:
    monkeypatch.setenv("TRACKING_MAX_DIM", "4096")
    monkeypatch.setenv("SAM2_OFFLOAD_VIDEO_TO_CPU", "true")
    monkeypatch.setenv("SAM2_OFFLOAD_STATE_TO_CPU", "1")

    configured = load_settings()

    assert configured.tracking_max_dimension == 4096
    assert configured.sam2_offload_video_to_cpu is True
    assert configured.sam2_offload_state_to_cpu is True


def test_tracking_settings_default_to_2048_without_offloading(
    monkeypatch: object,
) -> None:
    monkeypatch.delenv("TRACKING_MAX_DIM", raising=False)
    monkeypatch.delenv("SAM2_OFFLOAD_VIDEO_TO_CPU", raising=False)
    monkeypatch.delenv("SAM2_OFFLOAD_STATE_TO_CPU", raising=False)

    configured = load_settings()

    assert configured.tracking_max_dimension == 2048
    assert configured.sam2_offload_video_to_cpu is False
    assert configured.sam2_offload_state_to_cpu is False


def test_hardening_settings_have_balanced_defaults(monkeypatch: object) -> None:
    for name in (
        "PLAYTRACK_ALLOWED_HOSTS",
        "PLAYTRACK_MAX_UPLOAD_BYTES",
        "PLAYTRACK_MAX_EXPORT_WIDTH",
        "PLAYTRACK_MAX_EXPORT_HEIGHT",
        "PLAYTRACK_MAX_EXPORT_PIXELS",
        "PLAYTRACK_LOCATE_REVISION",
    ):
        monkeypatch.delenv(name, raising=False)

    configured = load_settings()

    assert configured.allowed_hosts == ()
    assert configured.max_upload_bytes == 20 * 1024**3
    assert configured.max_export_width == 4096
    assert configured.max_export_height == 2160
    assert configured.max_export_pixels == 4096 * 2160
    assert (
        configured.locate_revision
        == "c32291ca5e996f5a7a485845b4f57a233936bba0"
    )


def test_hardening_settings_parse_host_and_limit_overrides(monkeypatch: object) -> None:
    monkeypatch.setenv("PLAYTRACK_ALLOWED_HOSTS", " playtrack.lan,scoreboard.local ")
    monkeypatch.setenv("PLAYTRACK_MAX_UPLOAD_BYTES", "1024")
    monkeypatch.setenv("PLAYTRACK_MAX_EXPORT_WIDTH", "1920")
    monkeypatch.setenv("PLAYTRACK_MAX_EXPORT_HEIGHT", "1080")
    monkeypatch.setenv("PLAYTRACK_MAX_EXPORT_PIXELS", "2073600")
    monkeypatch.setenv("PLAYTRACK_LOCATE_REVISION", "deadbeef")

    configured = load_settings()

    assert configured.allowed_hosts == ("playtrack.lan", "scoreboard.local")
    assert configured.max_upload_bytes == 1024
    assert configured.max_export_width == 1920
    assert configured.max_export_height == 1080
    assert configured.max_export_pixels == 2073600
    assert configured.locate_revision == "deadbeef"


def test_playtrack_branded_settings_cover_all_public_overrides(
    monkeypatch: object, tmp_path: Path
) -> None:
    data_dir = tmp_path / "playtrack-data"
    checkpoints_dir = tmp_path / "models"
    checkpoint = checkpoints_dir / "custom.pt"
    values = {
        "PLAYTRACK_DATA_DIR": str(data_dir),
        "PLAYTRACK_CHECKPOINTS_DIR": str(checkpoints_dir),
        "PLAYTRACK_SAM2_CHECKPOINT": str(checkpoint),
        "PLAYTRACK_SAM2_CONFIG": "custom/model.yaml",
        "PLAYTRACK_SAM2_CROP_SIZE": "768",
        "PLAYTRACK_FFMPEG": "/tools/ffmpeg",
        "PLAYTRACK_FFPROBE": "/tools/ffprobe",
        "PLAYTRACK_LOCATE_MODEL": "example/playtrack-locate",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)

    configured = load_settings()

    assert configured.data_dir == data_dir
    assert configured.checkpoints_dir == checkpoints_dir
    assert configured.sam2_checkpoint == checkpoint
    assert configured.sam2_model_config == "custom/model.yaml"
    assert configured.sam2_crop_size == 768
    assert configured.ffmpeg_binary == "/tools/ffmpeg"
    assert configured.ffprobe_binary == "/tools/ffprobe"
    assert configured.locate_model_id == "example/playtrack-locate"


def test_obsolete_findme_settings_are_not_accepted(
    monkeypatch: object, tmp_path: Path
) -> None:
    obsolete = {
        "FINDME_DATA_DIR": str(tmp_path / "obsolete"),
        "FINDME_CHECKPOINTS_DIR": str(tmp_path / "obsolete-models"),
        "FINDME_SAM2_CHECKPOINT": str(tmp_path / "obsolete.pt"),
        "FINDME_SAM2_CONFIG": "obsolete.yaml",
        "FINDME_SAM2_CROP_SIZE": "17",
        "FINDME_FFMPEG": "obsolete-ffmpeg",
        "FINDME_FFPROBE": "obsolete-ffprobe",
        "FINDME_LOCATE_MODEL": "obsolete/model",
        "FINDME_LOCATE_REVISION": "obsolete-revision",
        "FINDME_ALLOWED_HOSTS": "obsolete.local",
        "FINDME_MAX_UPLOAD_BYTES": "1",
        "FINDME_MAX_EXPORT_WIDTH": "2",
        "FINDME_MAX_EXPORT_HEIGHT": "2",
        "FINDME_MAX_EXPORT_PIXELS": "4",
    }
    for name, value in obsolete.items():
        monkeypatch.setenv(name, value)

    configured = load_settings()

    assert configured.data_dir != tmp_path / "obsolete"
    assert configured.checkpoints_dir != tmp_path / "obsolete-models"
    assert configured.sam2_checkpoint != tmp_path / "obsolete.pt"
    assert configured.sam2_model_config != "obsolete.yaml"
    assert configured.sam2_crop_size == 1024
    assert configured.ffmpeg_binary == "ffmpeg"
    assert configured.ffprobe_binary == "ffprobe"
    assert configured.locate_model_id == "nvidia/LocateAnything-3B"
    assert configured.locate_revision != "obsolete-revision"
    assert configured.allowed_hosts == ()
    assert configured.max_upload_bytes == 20 * 1024**3
    assert configured.max_export_width == 4096
    assert configured.max_export_height == 2160
    assert configured.max_export_pixels == 4096 * 2160
