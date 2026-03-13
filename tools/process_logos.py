"""Processes raw logos from dataset/ into the three publish variants.

For each brand directory in  dataset/<slug>/  this tool picks the
best available image (preferring logo.png, then the largest PNG file),
applies the appropriate resize, and writes:

    logos/original/<slug>.png   — original resolution, losslessly converted to PNG
    logos/optimized/<slug>.png  — max 240 px on either axis, PNG
    logos/thumb/<slug>.png      — max 100 px on either axis, PNG

Existing files are overwritten only when  --force  is passed.

Usage
-----
    python tools/process_logos.py
    python tools/process_logos.py --dataset-dir dataset --logos-dir logos --force
    python tools/process_logos.py --slug bosch            # single brand
"""
from __future__ import annotations

import argparse
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT_DIR = Path(__file__).resolve().parents[1]
UTILS_DIR = ROOT_DIR / "scrapers" / "utils"
if str(UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(UTILS_DIR))

from downloader import read_metadata, slugify_brand_name

# Output sizes: (max_width, max_height) — thumbnail() preserves aspect ratio
VARIANTS: dict[str, tuple[int, int] | None] = {
    "original": None,      # no resize — keep full resolution
    "optimized": (240, 240),
    "thumb": (100, 100),
}


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def _best_logo_path(brand_dir: Path) -> Path | None:
    """Return the path to the most suitable logo file inside brand_dir."""
    # Explicit 'logo.png' saved by the site scrapers takes priority
    logo_candidate = brand_dir / "logo.png"
    if logo_candidate.exists():
        return logo_candidate

    # site.png saved by dom_logo_scraper is next in line
    site_candidate = brand_dir / "site.png"
    if site_candidate.exists():
        return site_candidate

    # Fall back to the largest PNG (by file size) among the numbered files
    pngs = sorted(
        (p for p in brand_dir.glob("*.png")),
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    return pngs[0] if pngs else None


def _load_png(path: Path) -> Image.Image:
    img = Image.open(path)
    img.load()
    # Always normalise to RGBA so resize + save work uniformly
    if img.mode not in ("RGBA", "RGB"):
        img = img.convert("RGBA")
    return img


def _resize(img: Image.Image, max_size: tuple[int, int]) -> Image.Image:
    resized = img.copy()
    resized.thumbnail(max_size, Image.Resampling.LANCZOS)
    return resized


def _save_png(img: Image.Image, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    buf = BytesIO()
    # Save as RGBA PNG with maximum lossless compression
    img_out = img if img.mode == "RGBA" else img.convert("RGBA")
    img_out.save(buf, format="PNG", optimize=True)
    dest.write_bytes(buf.getvalue())


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------

def process_brand(brand_dir: Path, logos_dir: Path, slug: str, force: bool) -> bool:
    """Process one brand directory.  Returns True if any file was written."""
    source_path = _best_logo_path(brand_dir)
    if not source_path:
        return False

    try:
        original_img = _load_png(source_path)
    except Exception as exc:
        print(f"  [skip] {slug}: cannot open {source_path.name} — {exc}")
        return False

    wrote_any = False
    for variant, max_size in VARIANTS.items():
        dest = logos_dir / variant / f"{slug}.png"
        if dest.exists() and not force:
            continue

        img = _resize(original_img, max_size) if max_size else original_img.copy()
        try:
            _save_png(img, dest)
            wrote_any = True
        except Exception as exc:
            print(f"  [error] {slug}/{variant}: {exc}")

    return wrote_any


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera logos/original|optimized|thumb desde el dataset."
    )
    parser.add_argument("--dataset-dir", default="dataset",
                        help="Directorio raíz del dataset (default: dataset)")
    parser.add_argument("--logos-dir", default="logos",
                        help="Directorio de salida para los logos publicables (default: logos)")
    parser.add_argument("--slug", default=None,
                        help="Procesar únicamente esta marca (slug). Omitir para procesar todas.")
    parser.add_argument("--force", action="store_true",
                        help="Sobreescribir archivos existentes en logos/")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset_dir = (ROOT_DIR / args.dataset_dir).resolve()
    logos_dir = (ROOT_DIR / args.logos_dir).resolve()

    if not dataset_dir.is_dir():
        print(f"Error: dataset dir not found: {dataset_dir}")
        return 1

    # Collect brand directories to process
    if args.slug:
        slug = slugify_brand_name(args.slug)
        brand_dirs = [dataset_dir / slug]
    else:
        brand_dirs = sorted(p for p in dataset_dir.iterdir() if p.is_dir())

    processed = 0
    skipped = 0

    for brand_dir in brand_dirs:
        if not brand_dir.is_dir():
            print(f"  [warn] {brand_dir.name}: directory not found, skipping")
            continue

        slug = brand_dir.name
        wrote = process_brand(brand_dir, logos_dir, slug, args.force)
        if wrote:
            print(f"  ✓  {slug}")
            processed += 1
        else:
            skipped += 1

    print(f"\nDone: {processed} processed, {skipped} skipped (already up-to-date or no source)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
