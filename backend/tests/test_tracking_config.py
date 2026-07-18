from __future__ import annotations

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
        "FINDME_ALLOWED_HOSTS",
        "FINDME_MAX_UPLOAD_BYTES",
        "FINDME_MAX_EXPORT_WIDTH",
        "FINDME_MAX_EXPORT_HEIGHT",
        "FINDME_MAX_EXPORT_PIXELS",
        "FINDME_LOCATE_REVISION",
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
    monkeypatch.setenv("FINDME_ALLOWED_HOSTS", " findme.lan,scoreboard.local ")
    monkeypatch.setenv("FINDME_MAX_UPLOAD_BYTES", "1024")
    monkeypatch.setenv("FINDME_MAX_EXPORT_WIDTH", "1920")
    monkeypatch.setenv("FINDME_MAX_EXPORT_HEIGHT", "1080")
    monkeypatch.setenv("FINDME_MAX_EXPORT_PIXELS", "2073600")
    monkeypatch.setenv("FINDME_LOCATE_REVISION", "deadbeef")

    configured = load_settings()

    assert configured.allowed_hosts == ("findme.lan", "scoreboard.local")
    assert configured.max_upload_bytes == 1024
    assert configured.max_export_width == 1920
    assert configured.max_export_height == 1080
    assert configured.max_export_pixels == 2073600
    assert configured.locate_revision == "deadbeef"
