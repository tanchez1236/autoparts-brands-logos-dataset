"""Scrapes auto-parts brand logos from autodoc.es.

The scraper hits the autodoc.es manufacturers/brands listing page,
discovers every brand entry (name + logo image URL), downloads each
logo into  dataset/<slug>/logo.png  and records the canonical display
name in the brand's metadata.json.

Usage
-----
    python scrapers/autodoc_scraper.py
    python scrapers/autodoc_scraper.py --dataset-dir dataset --pause 1.0
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

try:
    import cloudscraper
    _HAVE_CLOUDSCRAPER = True
except ImportError:
    _HAVE_CLOUDSCRAPER = False

CURRENT_DIR = Path(__file__).resolve().parent
UTILS_DIR = CURRENT_DIR / "utils"
if str(UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(UTILS_DIR))

from downloader import download_image, ensure_brand_dir, slugify_brand_name, update_brand_metadata

SOURCE_NAME = "autodoc"

# Seed the session with cookies from the homepage before hitting other pages
# Warm-up URLs visited in order before the brand listing page; the first URL
# that returns any 2xx/4xx HTML response seeds the Cloudflare clearance cookie.
_WARMUP_URLS = [
    "https://www.autodoc.es/api/brands",        # 404 HTML — reliably bypasses CF
    "https://www.autodoc.es/api/v1/brands",     # 404 HTML fallback
    "https://www.autodoc.es/",                  # homepage
]
SEED_URL = _WARMUP_URLS[0]  # kept for the Referer header

# autodoc.es pages to try for brand listings (order matters — first match wins)
CANDIDATE_URLS: list[str] = [
    "https://www.autodoc.es/marcas-piezas-coche",   # primary – 800+ brands
    "https://www.autodoc.es/",
]

# Realistic browser headers to reduce bot-detection 403s
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}


# ---------------------------------------------------------------------------
# Brand discovery helpers
# ---------------------------------------------------------------------------

def _seed_session(session: requests.Session, pause: float) -> None:
    """Visit warm-up URLs to obtain a Cloudflare clearance cookie."""
    for url in _WARMUP_URLS:
        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            # Any HTML response (even 404) means CF let us through
            if resp.status_code != 403 and "text/html" in resp.headers.get("content-type", ""):
                time.sleep(pause)
                return
        except requests.RequestException:
            pass
        time.sleep(pause)


def _extract_from_json_ld(soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
    """Try to pull brand data from any JSON-LD or inline JSON blobs."""
    results: list[tuple[str, str]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(script.string or "")
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                name = item.get("name") or item.get("brand")
                image = item.get("image") or item.get("logo")
                if name and image:
                    image_url = image if image.startswith("http") else urljoin(base_url, image)
                    results.append((str(name), image_url))
        except (json.JSONDecodeError, AttributeError):
            continue
    return results


def _extract_brand_grid(soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
    """Look for the common grid/list patterns autodoc uses for brand tiles."""
    results: list[tuple[str, str]] = []

    # Selector candidates ordered by specificity
    grid_selectors = [
        "img.brand-item-full__img",            # autodoc.es /marcas-piezas-coche (primary)
        "li.manufacturers__item",
        "div.manufacturers__item",
        "a.manufacturers__item",
        ".manufacturers-list li",
        ".brands-list li",
        ".brands-list a",
        ".brand-list__item",
        ".manufacturer-item",
        "li[class*='manufacturer']",
        "li[class*='brand']",
        "a[class*='manufacturer']",
        "a[class*='brand']",
    ]

    # Strip autodoc SEO alt-text prefixes ("tienda recambios coche BOSCH" → "BOSCH")
    _alt_seo = re.compile(
        r"^(?:tienda\s+(?:de\s+)?(?:recambios?|repuestos?)(?:\s+(?:de\s+)?coches?)?"
        r"(?:\s+cerca\s+de\s+mi)?(?:\s+online)?|mejor\s+tienda\s+recambios\s+coche\s+online)\s+",
        re.IGNORECASE,
    )

    for selector in grid_selectors:
        items = soup.select(selector)
        if not items:
            continue
        # Direct <img> selector path (autodoc /marcas-piezas-coche)
        if selector.startswith("img"):
            for img in items:
                src = img.get("data-src") or img.get("src") or ""
                if not src or src.startswith("data:"):
                    continue
                name = _alt_seo.sub("", (img.get("alt") or "")).strip()
                if not name:
                    continue
                image_url = src if src.startswith("http") else urljoin(base_url, src)
                results.append((name, image_url))
            if results:
                break
            continue
        for item in items:
            img = item.find("img")
            if not img:
                continue
            src = img.get("data-src") or img.get("src") or ""
            if not src or src.startswith("data:"):
                continue
            # Derive name: alt > title > sibling text > inner span/p
            name = (
                img.get("alt")
                or img.get("title")
                or (item.find(["span", "p", "div", "h3", "h4"]) or {}).get_text(strip=True)
                or ""
            )
            name = name.strip()
            if not name:
                continue
            image_url = src if src.startswith("http") else urljoin(base_url, src)
            results.append((name, image_url))
        if results:
            break

    return results


def _extract_inline_json(soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
    """Some SPAs embed initial state as a JSON blob in a <script> tag."""
    results: list[tuple[str, str]] = []
    brand_pattern = re.compile(r'"(?:name|brand|manufacturer)"\s*:\s*"([^"]+)"')
    logo_pattern = re.compile(r'"(?:logo|image|img|imageUrl|logoUrl)"\s*:\s*"([^"]+)"')

    for script in soup.find_all("script"):
        text = script.string or ""
        if "manufacturer" not in text.lower() and "brand" not in text.lower():
            continue
        for name, logo in zip(brand_pattern.findall(text), logo_pattern.findall(text)):
            if not name or not logo:
                continue
            image_url = logo if logo.startswith("http") else urljoin(base_url, logo)
            results.append((name, image_url))

    return results


def scrape_brands(session: requests.Session, pause: float) -> list[tuple[str, str]]:
    """Return a list of (canonical_name, logo_url) for all discovered brands."""
    _seed_session(session, pause)

    for url in CANDIDATE_URLS:
        try:
            response = session.get(url, headers={**HEADERS, "Referer": SEED_URL}, timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"  [warn] {url} → {exc}")
            time.sleep(pause)
            continue

        soup = BeautifulSoup(response.text, "lxml")
        base_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"

        brands = (
            _extract_brand_grid(soup, base_url)
            or _extract_from_json_ld(soup, base_url)
            or _extract_inline_json(soup, base_url)
        )

        if brands:
            print(f"  Found {len(brands)} brands at {url}")
            return brands

        time.sleep(pause)

    print("  [warn] Could not discover any brand entries from autodoc.es")
    return []


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Descarga logos de marcas de partes desde autodoc.es"
    )
    parser.add_argument("--dataset-dir", default="dataset",
                        help="Directorio raíz del dataset (default: dataset)")
    parser.add_argument("--pause", type=float, default=1.0,
                        help="Pausa entre requests en segundos (default: 1.0)")
    parser.add_argument("--min-size", nargs=2, type=int, default=[32, 16],
                        metavar=("W", "H"),
                        help="Tamaño mínimo aceptable del logo en píxeles (default: 32 16)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.dataset_dir)
    if _HAVE_CLOUDSCRAPER:
        session = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "darwin", "mobile": False}
        )
    else:
        session = requests.Session()

    print("Scraping autodoc.es …")
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
            # Update metadata with canonical name even if logo already downloaded
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
