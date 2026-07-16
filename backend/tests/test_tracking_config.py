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
