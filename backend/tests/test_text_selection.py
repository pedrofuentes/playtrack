from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from app.models.locate_engine import LocateCandidate
from app.selection import TextSelector
from app.videos import ExtractedSourceCrop, VideoMetadata


@dataclass
class FakeSourceStore:
    image_path: Path

    def get(self, video_id: str) -> object:
        assert video_id == "video-1"
        return SimpleNamespace(
            metadata=VideoMetadata(
                width=4000,
                height=1000,
                fps=30.0,
                nb_frames=10,
                duration=1 / 3,
            )
        )

    def extract_source_crop(self, *args: object, **kwargs: object) -> ExtractedSourceCrop:
        assert kwargs == {
            "frame_idx": 3,
            "x": 0,
            "y": 0,
            "width": 4000,
            "height": 1000,
        }
        return ExtractedSourceCrop(
            path=self.image_path, x=0, y=0, width=4000, height=1000
        )


class FakeLocateEngine:
    available = True
    unavailable_reason = ""

    def __init__(self) -> None:
        self.image_size: tuple[int, int] | None = None
        self.prompts: list[str] = []

    def ground_text(self, image: Image.Image, prompt: str) -> list[LocateCandidate]:
        self.image_size = image.size
        self.prompts.append(prompt)
        return [LocateCandidate(box=(100, 50, 300, 200), score=0.75)]


def test_text_selector_downscales_and_maps_candidates_back_to_source(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "frame.png"
    Image.new("RGB", (4000, 1000), "black").save(image_path)
    engine = FakeLocateEngine()
    selector = TextSelector(
        FakeSourceStore(image_path),
        engine_provider=lambda: engine,
        max_input_dimension=2000,
    )

    candidates = selector.select_text("video-1", 3, "white jersey")

    assert engine.image_size == (2000, 500)
    assert engine.prompts == ["white jersey"]
    assert candidates == [LocateCandidate(box=(200, 100, 600, 400), score=0.75)]
