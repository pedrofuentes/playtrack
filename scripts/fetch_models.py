#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
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
    sha256: str


def _model(key: str, filename: str, config: str, sha256: str) -> ModelSpec:
    return ModelSpec(
        key=key,
        filename=filename,
        config=config,
        url=f"{SAM2_1_BASE_URL}/{filename}",
        sha256=sha256,
    )


MODEL_SPECS = {
    "tiny": _model(
        "tiny",
        "sam2.1_hiera_tiny.pt",
        "configs/sam2.1/sam2.1_hiera_t.yaml",
        "7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69",
    ),
    "small": _model(
        "small",
        "sam2.1_hiera_small.pt",
        "configs/sam2.1/sam2.1_hiera_s.yaml",
        "6d1aa6f30de5c92224f8172114de081d104bbd23dd9dc5c58996f0cad5dc4d38",
    ),
    "base-plus": _model(
        "base-plus",
        "sam2.1_hiera_base_plus.pt",
        "configs/sam2.1/sam2.1_hiera_b+.yaml",
        "a2345aede8715ab1d5d31b4a509fb160c5a4af1970f199d9054ccfb746c004c5",
    ),
    "large": _model(
        "large",
        "sam2.1_hiera_large.pt",
        "configs/sam2.1/sam2.1_hiera_l.yaml",
        "2647878d5dfa5098f2f8649825738a9345572bae2d4350a2468587ece47dd318",
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
        _verify_checksum(destination, spec.sha256)
        print(f"Already present: {destination}")
        return destination

    print(f"Downloading {spec.key}: {spec.url}")
    try:
        with opener(spec.url) as response, partial.open("wb") as output:
            while chunk := response.read(CHUNK_SIZE):
                output.write(chunk)
        _verify_checksum(partial, spec.sha256)
        partial.replace(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    print(f"Saved {destination}")
    return destination


def _verify_checksum(path: Path, expected: str) -> None:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        raise ValueError(
            f"Checkpoint checksum mismatch for {path.name}: expected {expected}, got {actual}"
        )


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
