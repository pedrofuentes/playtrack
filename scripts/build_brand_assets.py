from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

DARK = (8, 13, 20, 255)


def prepared_artwork(
    source: Image.Image,
    *,
    size: int,
    fill_ratio: float,
    background: tuple[int, int, int, int] | None,
) -> Image.Image:
    artwork = source.convert("RGBA")
    bounds = artwork.getchannel("A").getbbox()
    if bounds is None:
        raise ValueError("Brand source has no visible pixels")
    artwork = artwork.crop(bounds)
    target = max(1, round(size * fill_ratio))
    artwork.thumbnail((target, target), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), background or (0, 0, 0, 0))
    offset = ((size - artwork.width) // 2, (size - artwork.height) // 2)
    canvas.alpha_composite(artwork, offset)
    return canvas


def save_png(image: Image.Image, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="PNG", optimize=True, compress_level=9)
    return destination


def build_brand_assets(*, source_dir: Path, repo_root: Path) -> tuple[Path, ...]:
    with Image.open(source_dir / "playtrack-player-bright.png") as image:
        player_source = image.convert("RGBA")
    with Image.open(source_dir / "playtrack-bright.png") as image:
        complete_source = image.convert("RGBA")
    outputs: list[Path] = []

    player_web = prepared_artwork(
        player_source, size=512, fill_ratio=0.88, background=None
    )
    outputs.append(save_png(
        player_web, repo_root / "frontend/public/brand/playtrack-player-bright.png"
    ))
    outputs.append(save_png(
        player_web, repo_root / "website/assets/playtrack-player-bright.png"
    ))
    outputs.append(save_png(
        prepared_artwork(complete_source, size=1024, fill_ratio=0.90, background=None),
        repo_root / "website/assets/playtrack-bright.png",
    ))

    icon_specs = {
        "favicon-16.png": (16, 0.84),
        "favicon-32.png": (32, 0.84),
        "favicon-48.png": (48, 0.84),
        "apple-touch-icon.png": (180, 0.78),
        "pwa-192x192.png": (192, 0.82),
        "pwa-512x512.png": (512, 0.82),
        "pwa-maskable-192x192.png": (192, 0.64),
        "pwa-maskable-512x512.png": (512, 0.64),
    }
    for filename, (size, fill_ratio) in icon_specs.items():
        outputs.append(save_png(
            prepared_artwork(
                player_source,
                size=size,
                fill_ratio=fill_ratio,
                background=DARK,
            ),
            repo_root / "frontend/public" / filename,
        ))
    return tuple(outputs)


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Build PlayTrack brand derivatives")
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=repo_root.parent / "exchange",
    )
    args = parser.parse_args()
    for path in build_brand_assets(source_dir=args.source_dir, repo_root=repo_root):
        print(path.relative_to(repo_root))


if __name__ == "__main__":
    main()
