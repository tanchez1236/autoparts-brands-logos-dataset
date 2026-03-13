from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
UTILS_DIR = ROOT_DIR / "scrapers" / "utils"
if str(UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(UTILS_DIR))

from downloader import load_brands, slugify_brand_name
from validators import validate_image_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verifica que cada marca tenga al menos una imagen valida.")
    parser.add_argument("--brands-file", default="brands-list.txt")
    parser.add_argument("--dataset-dir", default="dataset")
    parser.add_argument("--min-size", nargs=2, type=int, default=(64, 64), metavar=("WIDTH", "HEIGHT"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset_dir = (ROOT_DIR / args.dataset_dir).resolve()
    brands = load_brands(ROOT_DIR / args.brands_file)

    failures = 0
    for brand in brands:
        brand_dir = dataset_dir / slugify_brand_name(brand)
        if not brand_dir.exists():
            print(f"[missing] {brand}: carpeta inexistente")
            failures += 1
            continue

        image_paths = sorted(brand_dir.glob("*.png"))
        if not image_paths:
            print(f"[missing] {brand}: sin imagenes")
            failures += 1
            continue

        valid_images = 0
        for image_path in image_paths:
            is_valid, errors = validate_image_file(image_path, min_size=tuple(args.min_size), allowed_formats={"PNG"})
            if is_valid:
                valid_images += 1
            else:
                print(f"[invalid] {brand}: {image_path.name} -> {', '.join(errors)}")

        if valid_images == 0:
            print(f"[missing] {brand}: ninguna imagen valida")
            failures += 1

    if failures:
        print(f"Verificacion finalizada con {failures} marca(s) sin cobertura valida.")
        return 1

    print("Verificacion completada sin errores.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
