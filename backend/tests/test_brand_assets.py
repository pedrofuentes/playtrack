from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.build_brand_assets import build_brand_assets  # noqa: E402


def source_logo(path: Path, *, size: int, color: tuple[int, int, int, int]) -> None:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = size // 5
    draw.rectangle((margin, margin, size - margin, size - margin), fill=color)
    image.save(path)


def test_brand_builder_emits_expected_assets_and_dimensions(tmp_path: Path) -> None:
    source_dir = tmp_path / "exchange"
    repo_root = tmp_path / "repo"
    source_dir.mkdir()
    source_logo(source_dir / "playtrack-player-bright.png", size=144, color=(31, 183, 255, 255))
    source_logo(source_dir / "playtrack-bright.png", size=204, color=(99, 255, 128, 255))

    outputs = build_brand_assets(source_dir=source_dir, repo_root=repo_root)

    expected = {
        "frontend/public/brand/playtrack-player-bright.png": (512, 512),
        "website/assets/playtrack-player-bright.png": (512, 512),
        "website/assets/playtrack-bright.png": (1024, 1024),
        "frontend/public/favicon-16.png": (16, 16),
        "frontend/public/favicon-32.png": (32, 32),
        "frontend/public/favicon-48.png": (48, 48),
        "frontend/public/apple-touch-icon.png": (180, 180),
        "frontend/public/pwa-192x192.png": (192, 192),
        "frontend/public/pwa-512x512.png": (512, 512),
        "frontend/public/pwa-maskable-192x192.png": (192, 192),
        "frontend/public/pwa-maskable-512x512.png": (512, 512),
    }
    assert {path.relative_to(repo_root).as_posix() for path in outputs} == set(expected)
    for relative, dimensions in expected.items():
        with Image.open(repo_root / relative) as image:
            assert image.size == dimensions
            assert image.mode == "RGBA"


def test_install_icons_use_opaque_dark_canvas_and_maskable_safe_zone(tmp_path: Path) -> None:
    source_dir = tmp_path / "exchange"
    repo_root = tmp_path / "repo"
    source_dir.mkdir()
    source_logo(source_dir / "playtrack-player-bright.png", size=144, color=(31, 183, 255, 255))
    source_logo(source_dir / "playtrack-bright.png", size=204, color=(99, 255, 128, 255))

    build_brand_assets(source_dir=source_dir, repo_root=repo_root)

    with Image.open(repo_root / "frontend/public/pwa-512x512.png").convert("RGBA") as standard:
        assert standard.getpixel((0, 0)) == (8, 13, 20, 255)
        assert standard.getpixel((256, 256))[:3] == (31, 183, 255)
    with Image.open(repo_root / "frontend/public/pwa-maskable-512x512.png").convert("RGBA") as maskable:
        assert maskable.getpixel((0, 0)) == (8, 13, 20, 255)
        assert maskable.getpixel((256, 256))[:3] == (31, 183, 255)
        assert maskable.getpixel((64, 64)) == (8, 13, 20, 255)


def test_committed_web_derivatives_stay_within_weight_budget() -> None:
    expected = {
        ROOT / "frontend/public/brand/playtrack-player-bright.png": (512, 512, 1_000_000),
        ROOT / "website/assets/playtrack-player-bright.png": (512, 512, 1_000_000),
        ROOT / "website/assets/playtrack-bright.png": (1024, 1024, 2_000_000),
    }
    for path, (width, height, max_bytes) in expected.items():
        assert path.is_file()
        assert path.stat().st_size <= max_bytes
        with Image.open(path) as image:
            assert image.size == (width, height)
