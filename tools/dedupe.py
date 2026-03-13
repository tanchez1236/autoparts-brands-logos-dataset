from __future__ import annotations

import argparse
import sys
from pathlib import Path

import imagehash
from PIL import Image

ROOT_DIR = Path(__file__).resolve().parents[1]
UTILS_DIR = ROOT_DIR / "scrapers" / "utils"
if str(UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(UTILS_DIR))

from downloader import read_metadata, write_metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Elimina imagenes duplicadas usando perceptual hashing.")
    parser.add_argument("--dataset-dir", default="dataset")
    parser.add_argument("--threshold", type=int, default=4)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def compute_hash(image_path: Path) -> imagehash.ImageHash:
    with Image.open(image_path) as image:
        return imagehash.phash(image.convert("RGB"))


def main() -> int:
    args = parse_args()
    dataset_dir = (ROOT_DIR / args.dataset_dir).resolve()
    removed_files = 0

    for brand_dir in sorted(path for path in dataset_dir.iterdir() if path.is_dir()):
        seen_hashes: list[tuple[Path, imagehash.ImageHash]] = []
        for image_path in sorted(brand_dir.glob("*.png")):
            current_hash = compute_hash(image_path)
            duplicate_of: Path | None = None
            for existing_path, existing_hash in seen_hashes:
                if current_hash - existing_hash <= args.threshold:
                    duplicate_of = existing_path
                    break

            if duplicate_of is None:
                seen_hashes.append((image_path, current_hash))
                continue

            print(f"[duplicate] {image_path} ~= {duplicate_of}")
            if not args.dry_run:
                image_path.unlink()
            removed_files += 1

        metadata = read_metadata(brand_dir, brand_dir.name)
        write_metadata(brand_dir, metadata.get("brand", brand_dir.name), set(metadata.get("sources", [])))

    print(f"Duplicados detectados/eliminados: {removed_files}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
