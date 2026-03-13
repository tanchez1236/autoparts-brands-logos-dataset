"""Generates data/logos.json — the main publishable dataset file.

Reads every  logos/original/<slug>.png  file, looks up the canonical
brand name from  dataset/<slug>/metadata.json  and assembles entries in
the same format used by filippofilip95/car-logos-dataset:

    {
      "name": "Bosch",
      "slug": "bosch",
      "image": {
        "thumb": "https://raw.githubusercontent.com/.../logos/thumb/bosch.png",
        "optimized": "https://raw.githubusercontent.com/.../logos/optimized/bosch.png",
        "original": "https://raw.githubusercontent.com/.../logos/original/bosch.png"
      }
    }

The output is written to  data/logos.json  (or the path given via
--output) and also printed to stdout unless  --quiet  is passed.

Usage
-----
    python tools/generate_data.py
    python tools/generate_data.py --repo-url https://raw.githubusercontent.com/YOU/REPO/master
    python tools/generate_data.py --output data/logos.json --quiet
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
UTILS_DIR = ROOT_DIR / "scrapers" / "utils"
if str(UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(UTILS_DIR))

from downloader import read_metadata, slugify_brand_name

DEFAULT_REPO_URL = (
    "https://raw.githubusercontent.com/tanchez1236/autoparts-brands-logos-dataset/master"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug_to_display_name(slug: str) -> str:
    """Best-effort conversion of a slug back to a display name."""
    return re.sub(r"[-_]+", " ", slug).title()


def _load_name(slug: str, dataset_dir: Path) -> str:
    brand_dir = dataset_dir / slug
    if brand_dir.is_dir():
        metadata = read_metadata(brand_dir, slug)
        name = metadata.get("name") or metadata.get("brand") or ""
        if name and name != slug:
            return name
    return _slug_to_display_name(slug)


def build_entry(slug: str, dataset_dir: Path, repo_url: str) -> dict:
    name = _load_name(slug, dataset_dir)
    base = repo_url.rstrip("/")
    return {
        "name": name,
        "slug": slug,
        "image": {
            "thumb": f"{base}/logos/thumb/{slug}.png",
            "optimized": f"{base}/logos/optimized/{slug}.png",
            "original": f"{base}/logos/original/{slug}.png",
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera data/logos.json con todas las marcas del dataset."
    )
    parser.add_argument(
        "--logos-dir", default="logos",
        help="Directorio que contiene original/, optimized/ y thumb/ (default: logos)",
    )
    parser.add_argument(
        "--dataset-dir", default="dataset",
        help="Directorio raíz del dataset para cargar metadatos (default: dataset)",
    )
    parser.add_argument(
        "--repo-url",
        default=DEFAULT_REPO_URL,
        help=(
            "URL base raw de GitHub para construir las URLs de imagen. "
            f"(default: {DEFAULT_REPO_URL})"
        ),
    )
    parser.add_argument(
        "--output", default="data/logos.json",
        help="Ruta del archivo JSON de salida (default: data/logos.json)",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="No imprimir el JSON por stdout",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logos_dir = (ROOT_DIR / args.logos_dir).resolve()
    original_dir = logos_dir / "original"
    dataset_dir = (ROOT_DIR / args.dataset_dir).resolve()
    output_path = (ROOT_DIR / args.output).resolve()

    if not original_dir.is_dir():
        print(
            f"Error: logos/original/ not found at {original_dir}.\n"
            "Run  python tools/process_logos.py  first.",
            file=sys.stderr,
        )
        return 1

    slugs = sorted(p.stem for p in original_dir.glob("*.png"))
    if not slugs:
        print("No logos found in logos/original/. Nothing to do.", file=sys.stderr)
        return 1

    entries = [build_entry(slug, dataset_dir, args.repo_url) for slug in slugs]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    json_text = json.dumps(entries, indent=2, ensure_ascii=False)
    output_path.write_text(json_text + "\n", encoding="utf-8")

    if not args.quiet:
        print(json_text)

    print(f"\n✓  {len(entries)} entries written to {output_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
