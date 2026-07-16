#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable
from urllib.request import urlopen


SAM2_1_BASE_URL = "https://dl.fbaipublicfiles.com/segment_anything_2/092824"
CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class ModelSpec:
    key: str
    filename: str
    config: str
    url: str


def _model(key: str, filename: str, config: str) -> ModelSpec:
    return ModelSpec(
        key=key,
        filename=filename,
        config=config,
        url=f"{SAM2_1_BASE_URL}/{filename}",
    )


MODEL_SPECS = {
    "tiny": _model(
        "tiny",
        "sam2.1_hiera_tiny.pt",
        "configs/sam2.1/sam2.1_hiera_t.yaml",
    ),
    "small": _model(
        "small",
        "sam2.1_hiera_small.pt",
        "configs/sam2.1/sam2.1_hiera_s.yaml",
    ),
    "base-plus": _model(
        "base-plus",
        "sam2.1_hiera_base_plus.pt",
        "configs/sam2.1/sam2.1_hiera_b+.yaml",
    ),
    "large": _model(
        "large",
        "sam2.1_hiera_large.pt",
        "configs/sam2.1/sam2.1_hiera_l.yaml",
    ),
}


def download_checkpoint(
    spec: ModelSpec,
    output_dir: Path,
    *,
    force: bool = False,
    opener: Callable[[str], BinaryIO] = urlopen,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / spec.filename
    partial = destination.with_suffix(destination.suffix + ".part")
    if destination.is_file() and not force:
        print(f"Already present: {destination}")
        return destination

    print(f"Downloading {spec.key}: {spec.url}")
    try:
        with opener(spec.url) as response, partial.open("wb") as output:
            while chunk := response.read(CHUNK_SIZE):
                output.write(chunk)
        partial.replace(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    print(f"Saved {destination}")
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download official Meta SAM 2.1 checkpoints for FindMe."
    )
    parser.add_argument(
        "--model",
        choices=tuple(MODEL_SPECS),
        default="base-plus",
        help="checkpoint size to download (default: base-plus)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="download all SAM 2.1 checkpoint sizes",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "checkpoints",
        help="checkpoint destination (default: repository checkpoints/)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace checkpoints that already exist",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    selected = list(MODEL_SPECS.values()) if args.all else [MODEL_SPECS[args.model]]
    try:
        for spec in selected:
            download_checkpoint(spec, args.output_dir, force=args.force)
    except Exception as exc:
        print(f"Download failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

