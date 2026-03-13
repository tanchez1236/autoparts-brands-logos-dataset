"""Scrapes auto-parts brand logos from eurocarparts.com/brands.

The scraper fetches https://www.eurocarparts.com/brands, extracts every
brand entry (name + logo image URL), downloads the logos into
dataset/<slug>/logo.png and records the canonical display name in each
brand's metadata.json.

Usage
-----
    python scrapers/eurocarparts_scraper.py
    python scrapers/eurocarparts_scraper.py --dataset-dir dataset --pause 1.0
"""
from __future__ import annotations

import argparse
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

SOURCE_NAME = "eurocarparts"
BRANDS_URL = "https://www.eurocarparts.com/brands"
BASE_URL = "https://www.eurocarparts.com"

# Words in a name that strongly indicate a nav/category item, not a brand
_NAV_WORDS = frozenset({
    "store", "locator", "sign", "wish", "list", "car parts", "car accessories",
    "tools", "performance", "service", "kits", "brakes", "engine", "suspension",
    "steering", "transmission", "cooling", "heating", "electrics", "lighting",
    "body", "exhaust", "lubricants", "fluids", "tech", "cleaning", "maintenance",
    "components", "security", "safety", "winter", "summer", "power", "hand",
    "lifting", "recovery", "workshop", "storage", "styling", "essentials",
    "delivery", "returns", "payment", "app", "deals", "click", "collect",
    "flexible", "exclusive", "easy", "ireland",
})

# Src path fragments that indicate an icon / UI graphic, not a brand logo
_ICON_PATH_FRAGMENTS = (
    "/icon", "/icons/", "/nav/", "/navigation/", "/menu/",
    "/ui/", "/arrow", "/chevron", "/sprite", "data:image",
    "/categories/", "/category/",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Referer": BASE_URL,
}


# ---------------------------------------------------------------------------
# Brand discovery
# ---------------------------------------------------------------------------

def _img_src(img_tag) -> str:
    """Return the best available src attribute from an <img> tag."""
    for attr in ("data-src", "data-lazy", "src"):
        val = img_tag.get(attr, "")
        if val and not val.startswith("data:"):
            return val
    return ""


def _resolve(src: str) -> str:
    return src if src.startswith("http") else urljoin(BASE_URL, src)


def _brand_name(item) -> str:
    """Extract a brand name from a brand tile element."""
    img = item.find("img")
    if img:
        for attr in ("alt", "title"):
            val = (img.get(attr) or "").strip()
            if val:
                return val

    for tag in ("span", "p", "h2", "h3", "h4", "div"):
        el = item.find(tag, class_=lambda c: c and ("name" in c or "title" in c or "label" in c))
        if el:
            text = el.get_text(strip=True)
            if text:
                return text

    text = item.get_text(separator=" ", strip=True)
    return text[:60] if text else ""


def _is_nav_noise(name: str, src: str) -> bool:
    """Return True when name or image src strongly suggest a non-brand item."""
    name_lower = name.lower()
    if any(word in name_lower for word in _NAV_WORDS):
        return True
    src_lower = src.lower()
    if any(frag in src_lower for frag in _ICON_PATH_FRAGMENTS):
        return True
    return False


def scrape_brands(session: requests.Session) -> list[tuple[str, str]]:
    """Return (canonical_name, logo_url) for every brand on the page."""
    response = session.get(BRANDS_URL, headers=HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "lxml")

    results: list[tuple[str, str]] = []
    seen_slugs: set[str] = set()

    # ---- Strategy 1: dedicated brand-tile components ----
    tile_selectors = [
        "li.brand-item",
        "div.brand-item",
        "a.brand-item",
        "li[class*='brand']",
        "div[class*='brand-card']",
        "div[class*='brand-tile']",
        "div[class*='brand-logo']",
        "li[class*='manufacturer']",
        "div[class*='manufacturer']",
        ".brands-list li",
        ".brands-list > a",
        ".brands-grid li",
        ".brands-grid > a",
        "[data-brand] img",
    ]

    for selector in tile_selectors:
        items = soup.select(selector)
        if not items:
            continue
        for item in items:
            img = item.find("img") if item.name != "img" else item
            if not img:
                continue
            src = _img_src(img)
            if not src:
                continue
            name = _brand_name(item if item.name != "img" else item.parent)
            if not name:
                continue
            slug = slugify_brand_name(name)
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            results.append((name, _resolve(src)))
        if results:
            break

    # Strip any navigation / category noise that leaked through
    results = [(n, u) for n, u in results if not _is_nav_noise(n, u)]

    if results:
        return results

    # ---- Strategy 2: any <a> containing an <img> inside a brands section ----
    brands_section = (
        soup.find(id=lambda i: i and "brand" in i.lower())
        or soup.find(class_=lambda c: c and "brand" in " ".join(c).lower())
        or soup
    )
    for anchor in brands_section.find_all("a", href=True):
        img = anchor.find("img")
        if not img:
            continue
        src = _img_src(img)
        if not src:
            continue
        name = _brand_name(anchor)
        if not name:
            continue
        if _is_nav_noise(name, src):
            continue
        slug = slugify_brand_name(name)
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        results.append((name, _resolve(src)))

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Descarga logos de marcas de partes desde eurocarparts.com/brands"
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
    session = requests.Session()

    print(f"Scraping {BRANDS_URL} …")
    try:
        brands = scrape_brands(session)
    except requests.RequestException as exc:
        print(f"Error al obtener la página de marcas: {exc}")
        return 1

    if not brands:
        print("No se encontraron marcas. Abortando.")
        return 1

    print(f"  Found {len(brands)} brands")

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
