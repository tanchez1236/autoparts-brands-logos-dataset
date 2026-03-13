"""Scrapes brand logos from Wikimedia Commons (SVG-first, highest quality).

Strategy
--------
1. Search Wikimedia Commons File namespace for "{brand} logo" — SVG preferred.
2. Score results: brand name match + "logo" keyword + SVG extension.
3. Render SVG logos at 512 px width via Wikimedia thumbnail URL  →  pixel-perfect
   at any output size; cairosvg then re-rasterises to a clean internal PNG.
4. Fall back to the Wikipedia article's page-image if Commons search yields nothing.

All results are saved as  dataset/<slug>/logo.png, which has highest priority
in the process_logos pipeline (outranks numbered and site.png files).

Usage
-----
    python scrapers/wikimedia_scraper.py
    python scrapers/wikimedia_scraper.py --brands-file brands-list.txt \\
        --dataset-dir dataset --pause 0.5 --force
    python scrapers/wikimedia_scraper.py --slug ngk        # single brand
    python scrapers/wikimedia_scraper.py --slug ngk --force  # re-fetch
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import requests

CURRENT_DIR = Path(__file__).resolve().parent
UTILS_DIR = CURRENT_DIR / "utils"
if str(UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(UTILS_DIR))

from cleaners import normalize_image_bytes
from downloader import ensure_brand_dir, load_brands, slugify_brand_name, update_brand_metadata
from validators import validate_image_bytes

SOURCE_NAME = "wikimedia"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
# Width requested when rendering an SVG via the Wikimedia thumb service.
# At 512 px the cairosvg re-rasterisation in cleaners.py produces a crisp PNG.
SVG_RENDER_WIDTH = 512

HEADERS = {
    "User-Agent": (
        "brands-logos-dataset/2.0 "
        "(autoparts brand logos; https://github.com/tanchez1236/autoparts-brands-logos-dataset; "
        "contact via GitHub issues) Python/requests"
    )
}

# ---------------------------------------------------------------------------
# Wikimedia Commons search
# ---------------------------------------------------------------------------

def _commons_search(query: str, session: requests.Session, limit: int = 10) -> list[str]:
    """Search Commons File namespace; return list of file titles."""
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srnamespace": 6,
        "srlimit": limit,
        "srprop": "snippet",
        "format": "json",
    }
    resp = session.get(COMMONS_API, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return [hit["title"] for hit in data.get("query", {}).get("search", [])]


def _get_image_info(
    file_title: str,
    session: requests.Session,
    url_width: int = 0,
) -> dict | None:
    """Return an imageinfo dict for a File: page, or None on failure."""
    params: dict = {
        "action": "query",
        "titles": file_title,
        "prop": "imageinfo",
        "iiprop": "url|mime|size|canonicaltitle",
        "format": "json",
    }
    if url_width:
        params["iiurlwidth"] = url_width
    resp = session.get(COMMONS_API, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    for page in pages.values():
        ii_list = page.get("imageinfo", [])
        if ii_list:
            return ii_list[0]
    return None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_file(title: str, brand: str) -> int:
    """Return a quality score (higher = better) for a candidate file title.

    Returns 0 when the brand name is not present — those files are skipped.
    """
    t = title.lower()
    b_slug = slugify_brand_name(brand)           # e.g. "ngk", "mann-filter"
    b_plain = re.sub(r"[^a-z0-9]+", "", brand.lower())  # e.g. "ngk", "mannfilter"

    score = 0

    # ---- brand name presence (required) ----
    if b_slug in t or b_plain in t:
        score += 25
    else:
        # Try matching each meaningful token
        tokens = [tok for tok in b_slug.split("-") if len(tok) > 2]
        if tokens and all(tok in t for tok in tokens):
            score += 18
        elif tokens and tokens[0] in t:
            score += 8
        else:
            return 0  # No brand name found — skip completely

    # ---- "logo" keyword ----
    if "logo" in t:
        score += 12

    # ---- format preference ----
    if t.endswith(".svg"):
        score += 20         # Infinite resolution — always prefer SVG
    elif t.endswith(".png"):
        score += 0
    else:
        score -= 5

    # ---- penalise derivative / product images ----
    for bad in (
        "shirt", "mug", "hat", "decal", "sticker", "patch", "jacket",
        "racing", "iridium", "platinum", "product", "bottle", "can",
        "packaging", "box", "white", "dark", "black", "mono",
    ):
        if bad in t:
            score -= 12

    return score


# ---------------------------------------------------------------------------
# Main finder
# ---------------------------------------------------------------------------

def find_best_commons_file(
    brand: str, session: requests.Session, pause: float
) -> tuple[str, dict] | None:
    """Return (file_title, image_info) for the best Commons logo, or None."""
    candidates: list[tuple[int, str]] = []

    for query in [f"{brand} logo", f"{brand} logo filetype:svg"]:
        try:
            titles = _commons_search(query, session)
        except requests.RequestException:
            titles = []
        time.sleep(pause * 0.5)
        for title in titles:
            score = _score_file(title, brand)
            if score > 0:
                candidates.append((score, title))

    if not candidates:
        return None

    candidates.sort(key=lambda x: -x[0])
    seen: set[str] = set()

    for _, title in candidates[:6]:
        if title in seen:
            continue
        seen.add(title)
        is_svg = title.lower().endswith(".svg")
        url_width = SVG_RENDER_WIDTH if is_svg else 0
        try:
            info = _get_image_info(title, session, url_width=url_width)
        except requests.RequestException:
            info = None
        time.sleep(pause * 0.3)
        if info and (info.get("thumburl") or info.get("url")):
            return title, info

    return None


def _wikipedia_fallback(
    brand: str, session: requests.Session, pause: float
) -> dict | None:
    """Fallback: get the brand's Wikipedia article page-image."""
    params = {
        "action": "query",
        "prop": "pageimages",
        "piprop": "original",
        "generator": "search",
        "gsrsearch": f"{brand} company manufacturer auto parts",
        "gsrnamespace": 0,
        "gsrlimit": 3,
        "format": "json",
        "redirects": 1,
    }
    try:
        resp = session.get(WIKIPEDIA_API, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    data = resp.json()
    time.sleep(pause)
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        orig = page.get("original")
        if orig:
            url = orig.get("source", "")
            if not url:
                continue
            mime = "image/svg+xml" if url.endswith(".svg") else "image/png"
            return {"url": url, "thumburl": url, "mime": mime}
    return None


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _download_logo(info: dict, session: requests.Session) -> bytes:
    """Download image bytes from an imageinfo dict and normalise to PNG."""
    url = info.get("thumburl") or info.get("url")
    if not url:
        raise ValueError("no URL in imageinfo")
    resp = session.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    ct = resp.headers.get("Content-Type", "")
    if "svg" in ct or url.lower().endswith(".svg"):
        ext = ".svg"
    else:
        ext = ".png"
    return normalize_image_bytes(resp.content, source_extension=ext)


# ---------------------------------------------------------------------------
# Per-brand logic
# ---------------------------------------------------------------------------

def scrape_brand(
    brand: str,
    dataset_dir: Path,
    session: requests.Session,
    *,
    pause: float = 0.5,
    force: bool = False,
) -> bool:
    """Scrape one brand. Returns True if a logo was saved."""
    brand_dir = ensure_brand_dir(dataset_dir, brand)
    dest = brand_dir / "logo.png"
    if dest.exists() and not force:
        return False

    result = find_best_commons_file(brand, session, pause)
    info = result[1] if result else None

    if info is None:
        info = _wikipedia_fallback(brand, session, pause)

    if info is None:
        return False

    try:
        png_bytes = _download_logo(info, session)
    except Exception as exc:
        print(f"  [error] {brand}: download failed — {exc}")
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
        description="Descarga logos desde Wikimedia Commons (prioridad SVG)."
    )
    parser.add_argument("--brands-file", default="brands-list.txt")
    parser.add_argument("--dataset-dir", default="dataset")
    parser.add_argument(
        "--pause", type=float, default=0.5,
        help="Pausa entre peticiones API (segundos)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Sobreescribir logo.png existente"
    )
    parser.add_argument(
        "--slug", default=None,
        help="Procesar sólo esta marca (por nombre exacto del brands-list)"
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
