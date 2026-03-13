"""Scrapes brand logos from logodix.com (high-resolution PNG / SVG fallback).

Logodix mirrors many Wikimedia Commons SVG logos as large PNGs (≥2000 px).
Entries whose title contains "Wikimedia Commons" are sourced directly from
official Wikipedia/Commons files and are ideal for this dataset.

Strategy per brand
------------------
1. GET https://logodix.com/{brand_slug}
2. Parse all ``<a href="/logos/{id}">`` links and their title text.
3. Score each entry:
   - "wikimedia" + ".svg" in title  →  +100   (SVG rasterised from Commons)
   - "wikimedia" in title           →  +80    (PNG directly from Commons)
   - "vector" or ".svg" in title    →  +50
   - product terms (iridium, shirt, sticker …) in title  →  -50 each
4. Download best entry:
   a. Try vector file: https://logodix.com/vector-downloaded/{id}  (→ SVG when available)
   b. Fall back to PNG: https://logodix.com/logo/{id}.png
5. Save to dataset/<slug>/logo.png (overriding only when --force or file missing).

Usage
-----
    python scrapers/logodix_scraper.py
    python scrapers/logodix_scraper.py --brands-file brands-list.txt --pause 1.0
    python scrapers/logodix_scraper.py --slug ngk --force
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

CURRENT_DIR = Path(__file__).resolve().parent
UTILS_DIR = CURRENT_DIR / "utils"
if str(UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(UTILS_DIR))

from cleaners import normalize_image_bytes
from downloader import ensure_brand_dir, load_brands, slugify_brand_name, update_brand_metadata
from validators import validate_image_bytes

SOURCE_NAME = "logodix"
BASE_URL = "https://logodix.com"
LOGO_PNG_URL = "https://logodix.com/logo/{id}.png"
LOGO_VECTOR_URL = "https://logodix.com/vector-downloaded/{id}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

IMG_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Referer": "https://logodix.com/",
}

# ---------------------------------------------------------------------------
# Slug conversion
# ---------------------------------------------------------------------------

def _logodix_slug(brand: str) -> str:
    """Convert a brand name to a logodix.com URL slug."""
    slug = brand.lower()
    slug = slug.replace("&", "and")
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug


# ---------------------------------------------------------------------------
# Page parsing
# ---------------------------------------------------------------------------

_PRODUCT_TERMS = frozenset([
    "iridium", "platinum", "sticker", "shirt", "mug", "hat",
    "decal", "patch", "jacket", "spray", "bottle", "can", "box",
])


def _parse_logo_entries(html: str) -> list[tuple[int, str]]:
    """Return (logo_id, title) pairs parsed from the brand page HTML."""
    soup = BeautifulSoup(html, "lxml")
    entries: list[tuple[int, str]] = []
    seen: set[int] = set()
    for a in soup.select("a[href*='/logos/']"):
        href = a.get("href", "")
        m = re.search(r"/logos/(\d+)$", href)
        if not m:
            continue
        logo_id = int(m.group(1))
        if logo_id in seen:
            continue
        seen.add(logo_id)
        title = a.get("title") or a.get_text(strip=True) or ""
        entries.append((logo_id, title))
    return entries


def _score_entry(title: str, brand: str) -> int:
    """Score a logodix logo entry; higher = better quality source."""
    t = title.lower()
    score = 0

    # Wikimedia Commons sourced → very high quality rasters from SVG originals
    if "wikimedia" in t and ".svg" in t:
        score += 100
    elif "wikimedia" in t:
        score += 80

    # Vector / SVG indicators
    if "vector" in t or ".svg" in t:
        score += 50

    # Official logo keywords
    if "logo" in t:
        score += 10

    # Penalise product-specific entries
    for bad in _PRODUCT_TERMS:
        if bad in t:
            score -= 50

    return score


def _pick_best_entry(entries: list[tuple[int, str]], brand: str) -> int | None:
    """Return the logo_id of the best entry, or None."""
    if not entries:
        return None

    scored = [(entries[i][0], entries[i][1], _score_entry(entries[i][1], brand))
              for i in range(len(entries))]

    # Sort by (score DESC, original position ASC)
    best = max(scored, key=lambda x: x[2])

    # Only use a negative-score entry as last resort (it's a product image)
    if best[2] < 0:
        # Fall back to first entry on the page
        return entries[0][0]

    return best[0]


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def _try_vector(logo_id: int, session: requests.Session) -> bytes | None:
    """Attempt to download the vector file; returns PNG bytes or None."""
    url = LOGO_VECTOR_URL.format(id=logo_id)
    try:
        resp = session.get(url, headers=IMG_HEADERS, timeout=30, allow_redirects=True)
        resp.raise_for_status()
        ct = resp.headers.get("Content-Type", "")
        if "svg" in ct or resp.url.lower().endswith(".svg"):
            ext = ".svg"
        elif "png" in ct or resp.url.lower().endswith(".png"):
            ext = ".png"
        else:
            return None  # Unknown format
        return normalize_image_bytes(resp.content, source_extension=ext)
    except Exception:
        return None


def _try_png(logo_id: int, session: requests.Session) -> bytes | None:
    """Download the direct PNG at logodix.com/logo/{id}.png."""
    url = LOGO_PNG_URL.format(id=logo_id)
    try:
        resp = session.get(url, headers=IMG_HEADERS, timeout=30)
        resp.raise_for_status()
        return normalize_image_bytes(resp.content, source_extension=".png")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Per-brand logic
# ---------------------------------------------------------------------------

def scrape_brand(
    brand: str,
    dataset_dir: Path,
    session: requests.Session,
    *,
    pause: float = 1.0,
    force: bool = False,
) -> bool:
    """Scrape one brand. Returns True if a logo was saved."""
    brand_dir = ensure_brand_dir(dataset_dir, brand)
    dest = brand_dir / "logo.png"
    if dest.exists() and not force:
        return False

    slug = _logodix_slug(brand)
    brand_page_url = f"{BASE_URL}/{slug}"

    try:
        resp = session.get(brand_page_url, headers=HEADERS, timeout=20)
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"  [error] {brand}: {exc}")
        return False

    entries = _parse_logo_entries(resp.text)
    time.sleep(pause * 0.5)

    if not entries:
        return False

    best_id = _pick_best_entry(entries, brand)
    if best_id is None:
        return False

    # Determine whether the best entry is a Wikimedia/vector candidate
    best_title = next((t for lid, t in entries if lid == best_id), "")
    has_vector_candidate = "wikimedia" in best_title.lower() or "vector" in best_title.lower()

    png_bytes: bytes | None = None

    if has_vector_candidate:
        png_bytes = _try_vector(best_id, session)
        time.sleep(pause * 0.3)

    if png_bytes is None:
        png_bytes = _try_png(best_id, session)
        time.sleep(pause * 0.3)

    if png_bytes is None:
        return False

    is_valid, errors = validate_image_bytes(
        png_bytes,
        min_size=(32, 32),
        allowed_formats={"PNG"},
        skip_logo_heuristic=True,
    )
    if not is_valid:
        print(f"  [skip] {brand}: invalid image — {', '.join(errors)}")
        return False

    dest.write_bytes(png_bytes)
    update_brand_metadata(dataset_dir, brand, source=SOURCE_NAME)
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Descarga logos desde logodix.com (altas resoluciones, fuente Wikimedia Commons)."
    )
    parser.add_argument("--brands-file", default="brands-list.txt")
    parser.add_argument("--dataset-dir", default="dataset")
    parser.add_argument(
        "--pause", type=float, default=1.0,
        help="Pausa entre peticiones (segundos)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Sobreescribir logo.png existente"
    )
    parser.add_argument(
        "--slug", default=None,
        help="Procesar sólo esta marca (nombre exacto del brands-list)"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset_dir = Path(args.dataset_dir).resolve()
    session = requests.Session()

    brands = [args.slug] if args.slug else load_brands(args.brands_file)

    ok = skip = fail = 0
    for brand in brands:
        try:
            saved = scrape_brand(
                brand, dataset_dir, session,
                pause=args.pause, force=args.force,
            )
            if saved:
                ok += 1
                print(f"  ✓  {brand}")
            else:
                skip += 1
        except Exception as exc:
            fail += 1
            print(f"  ✗  {brand}: {exc}")
        time.sleep(args.pause)

    print(f"\nDone: {ok} descargados, {skip} omitidos, {fail} errores")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
