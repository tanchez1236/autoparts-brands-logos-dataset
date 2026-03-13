"""Scrapes auto-parts brand logos from rockauto.com.

RockAuto lists hundreds of parts manufacturers in its catalog.  This
scraper fetches the catalog overview and any dedicated brand/manufacturer
pages, extracts brand names together with their logo images, downloads
each logo as  dataset/<slug>/logo.png  and stores the canonical display
name in the brand's metadata.json.

Usage
-----
    python scrapers/rockauto_scraper.py
    python scrapers/rockauto_scraper.py --dataset-dir dataset --pause 1.5
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

CURRENT_DIR = Path(__file__).resolve().parent
UTILS_DIR = CURRENT_DIR / "utils"
if str(UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(UTILS_DIR))

from downloader import download_image, ensure_brand_dir, slugify_brand_name, update_brand_metadata

SOURCE_NAME = "rockauto"

BASE_URL = "https://www.rockauto.com"

# RockAuto pages that may contain brand/manufacturer listings
CANDIDATE_URLS: list[str] = [
    "https://www.rockauto.com/en/catalog/",
    "https://www.rockauto.com/",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

# RockAuto CDN patterns for brand logos
LOGO_CDN_PATTERN = re.compile(
    r"https?://(?:www\.)?(?:static\.rockauto\.com|cdn\.rockauto\.com)"
    r"/[^\"'\s>]+(?:logo|brand|mfr)[^\"'\s>]*\.(?:png|jpg|svg|webp)",
    re.IGNORECASE,
)

# Matches JSON-embedded brand data like {"name":"Bosch","logo":"https://…"}
BRAND_JSON_PATTERN = re.compile(
    r'\{\s*"(?:name|brand|manufacturer)"\s*:\s*"([^"]+)"'
    r'[^}]*"(?:logo|image|img|imageUrl|logoUrl)"\s*:\s*"([^"]+)"',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Brand discovery helpers
# ---------------------------------------------------------------------------

def _extract_from_table(soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
    """RockAuto sometimes renders brands in table cells with images."""
    results: list[tuple[str, str]] = []
    for td in soup.select("td.listing-col-brand, td[class*='brand'], td[class*='mfr']"):
        img = td.find("img")
        if not img:
            continue
        src = img.get("data-src") or img.get("src") or ""
        if not src or src.startswith("data:"):
            continue
        name = img.get("alt") or img.get("title") or td.get_text(strip=True)
        if not name:
            continue
        image_url = src if src.startswith("http") else urljoin(base_url, src)
        results.append((name.strip(), image_url))
    return results


def _extract_from_nav(soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
    """Some pages list brand logos in navigation/sidebar blocks."""
    results: list[tuple[str, str]] = []
    selectors = [
        "div[id*='brand'] img",
        "div[class*='brand'] img",
        "div[id*='manufacturer'] img",
        "div[class*='manufacturer'] img",
        "ul[class*='brand'] img",
        "ul[class*='manufacturer'] img",
        "a[href*='/brand/'] img",
        "a[href*='/manufacturer/'] img",
    ]
    seen: set[str] = set()
    for selector in selectors:
        for img in soup.select(selector):
            src = img.get("data-src") or img.get("src") or ""
            if not src or src.startswith("data:") or src in seen:
                continue
            name = img.get("alt") or img.get("title") or ""
            if not name:
                continue
            seen.add(src)
            image_url = src if src.startswith("http") else urljoin(base_url, src)
            results.append((name.strip(), image_url))
    return results


def _extract_from_embedded_json(html: str, base_url: str) -> list[tuple[str, str]]:
    """Extract brand + logo pairs from inline JSON blobs in <script> tags."""
    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name, logo in BRAND_JSON_PATTERN.findall(html):
        key = slugify_brand_name(name)
        if key in seen:
            continue
        seen.add(key)
        image_url = logo if logo.startswith("http") else urljoin(base_url, logo)
        results.append((name, image_url))
    return results


def _extract_cdn_logos(html: str, soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
    """Find any CDN logo URLs directly embedded in the HTML."""
    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    for logo_url in LOGO_CDN_PATTERN.findall(html):
        if logo_url in seen:
            continue
        seen.add(logo_url)
        # Try to recover the brand name from a nearby img alt attribute
        img = soup.find("img", src=logo_url)
        name = (img.get("alt") or img.get("title") or "") if img else ""
        if not name:
            # Derive from the URL path: ".../bosch_logo.png" → "bosch"
            stem = Path(urlparse(logo_url).path).stem
            name = re.sub(r"[-_](logo|brand|mfr|img)$", "", stem, flags=re.IGNORECASE)
            name = re.sub(r"[-_]+", " ", name).title()
        if name:
            results.append((name, logo_url))
    return results


def scrape_brands(session: requests.Session, pause: float) -> list[tuple[str, str]]:
    """Return (canonical_name, logo_url) pairs discovered from rockauto.com."""
    for url in CANDIDATE_URLS:
        try:
            response = session.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"  [warn] {url} → {exc}")
            time.sleep(pause)
            continue

        html = response.text
        soup = BeautifulSoup(html, "lxml")
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        brands = (
            _extract_from_table(soup, base_url)
            or _extract_from_nav(soup, base_url)
            or _extract_from_embedded_json(html, base_url)
            or _extract_cdn_logos(html, soup, base_url)
        )

        if brands:
            seen_slugs: set[str] = set()
            unique: list[tuple[str, str]] = []
            for entry in brands:
                slug = slugify_brand_name(entry[0])
                if slug not in seen_slugs:
                    seen_slugs.add(slug)
                    unique.append(entry)
            print(f"  Found {len(unique)} brands at {url}")
            return unique

        time.sleep(pause)

    print("  [warn] Could not discover any brand entries from rockauto.com")
    return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Descarga logos de marcas de partes desde rockauto.com"
    )
    parser.add_argument("--dataset-dir", default="dataset",
                        help="Directorio raíz del dataset (default: dataset)")
    parser.add_argument("--pause", type=float, default=1.5,
                        help="Pausa entre requests en segundos (default: 1.5)")
    parser.add_argument("--min-size", nargs=2, type=int, default=[32, 16],
                        metavar=("W", "H"),
                        help="Tamaño mínimo aceptable del logo en píxeles (default: 32 16)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.dataset_dir)
    session = requests.Session()

    print("Scraping rockauto.com …")
    brands = scrape_brands(session, args.pause)

    if not brands:
        print("No se encontraron marcas. Abortando.")
        return 1

    ok = 0
    skipped = 0
    for name, logo_url in brands:
        slug = slugify_brand_name(name)
        brand_dir = ensure_brand_dir(root, slug)
        logo_path = brand_dir / "logo.png"

        if logo_path.exists():
            update_brand_metadata(root, slug, source=SOURCE_NAME, name=name)
            skipped += 1
            continue

        try:
            result = download_image(
                logo_url,
                root,
                slug,
                source=SOURCE_NAME,
                filename="logo.png",
                session=session,
                min_size=(args.min_size[0], args.min_size[1]),
                skip_logo_heuristic=True,
            )
            if result:
                update_brand_metadata(root, slug, source=SOURCE_NAME, name=name)
                print(f"  ✓  {name}")
                ok += 1
            else:
                print(f"  ✗  {name} — logo descartado por validación")
                skipped += 1
        except Exception as exc:
            print(f"  ✗  {name} — {exc}")
            skipped += 1

        time.sleep(args.pause)

    print(f"\nDone: {ok} downloaded, {skipped} skipped/failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
