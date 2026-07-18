from __future__ import annotations

import sys
import hashlib
from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.fetch_models import MODEL_SPECS, download_checkpoint  # noqa: E402


class FakeResponse(BytesIO):
    headers = {"Content-Length": "8"}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def test_base_plus_uses_official_sam_2_1_checkpoint() -> None:
    spec = MODEL_SPECS["base-plus"]

    assert spec.filename == "sam2.1_hiera_base_plus.pt"
    assert spec.url == (
        "https://dl.fbaipublicfiles.com/segment_anything_2/092824/"
        "sam2.1_hiera_base_plus.pt"
    )
    assert spec.sha256 == (
        "a2345aede8715ab1d5d31b4a509fb160c5a4af1970f199d9054ccfb746c004c5"
    )


def test_download_writes_atomically_without_network(tmp_path: Path) -> None:
    calls: list[str] = []

    def opener(url: str) -> FakeResponse:
        calls.append(url)
        return FakeResponse(b"weights!")

    spec = replace(
        MODEL_SPECS["base-plus"],
        sha256=hashlib.sha256(b"weights!").hexdigest(),
    )
    destination = download_checkpoint(
        spec,
        tmp_path,
        opener=opener,
    )

    assert calls == [spec.url]
    assert destination.read_bytes() == b"weights!"
    assert not destination.with_suffix(destination.suffix + ".part").exists()


def test_download_rejects_checkpoint_with_wrong_hash(tmp_path: Path) -> None:
    spec = replace(MODEL_SPECS["base-plus"], sha256="0" * 64)

    with pytest.raises(ValueError, match="checksum"):
        download_checkpoint(spec, tmp_path, opener=lambda _url: FakeResponse(b"wrong"))

    destination = tmp_path / spec.filename
    assert not destination.exists()
    assert not destination.with_suffix(destination.suffix + ".part").exists()


def test_existing_checkpoint_is_verified_before_reuse(tmp_path: Path) -> None:
    spec = replace(MODEL_SPECS["base-plus"], sha256="0" * 64)
    destination = tmp_path / spec.filename
    destination.parent.mkdir(exist_ok=True)
    destination.write_bytes(b"wrong")

    with pytest.raises(ValueError, match="checksum"):
        download_checkpoint(spec, tmp_path)

    assert destination.read_bytes() == b"wrong"
