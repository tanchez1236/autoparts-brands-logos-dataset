from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
UTILS_DIR = ROOT_DIR / "scrapers" / "utils"
if str(UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(UTILS_DIR))

from downloader import read_metadata, write_metadata


def count_images(brand_dir: Path) -> int:
    return len([path for path in brand_dir.glob("*.png")])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cuenta imagenes por marca dentro del dataset.")
    parser.add_argument("--dataset-dir", default="dataset")
    parser.add_argument("--sync-metadata", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset_dir = (ROOT_DIR / args.dataset_dir).resolve()
    summary: dict[str, int] = {}

    for brand_dir in sorted(path for path in dataset_dir.iterdir() if path.is_dir()):
        count = count_images(brand_dir)
        summary[brand_dir.name] = count

        if args.sync_metadata:
            metadata = read_metadata(brand_dir, brand_dir.name)
            write_metadata(brand_dir, metadata.get("brand", brand_dir.name), set(metadata.get("sources", [])))

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        for brand, count in summary.items():
            print(f"{brand}: {count}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
