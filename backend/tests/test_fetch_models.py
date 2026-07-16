from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

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


def test_download_writes_atomically_without_network(tmp_path: Path) -> None:
    calls: list[str] = []

    def opener(url: str) -> FakeResponse:
        calls.append(url)
        return FakeResponse(b"weights!")

    destination = download_checkpoint(
        MODEL_SPECS["base-plus"],
        tmp_path,
        opener=opener,
    )

    assert calls == [MODEL_SPECS["base-plus"].url]
    assert destination.read_bytes() == b"weights!"
    assert not destination.with_suffix(destination.suffix + ".part").exists()
