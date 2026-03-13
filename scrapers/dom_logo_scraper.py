from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

CURRENT_DIR = Path(__file__).resolve().parent
UTILS_DIR = CURRENT_DIR / "utils"
if str(UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(UTILS_DIR))

from cleaners import normalize_image_bytes
from downloader import ensure_brand_dir, update_brand_metadata
from validators import validate_image_bytes


def normalize_domain(domain: str) -> str:
    if domain.startswith("http://") or domain.startswith("https://"):
        return domain
    return f"https://{domain}"


def find_logo_candidate(soup: BeautifulSoup, brand: str) -> tuple[str, str] | None:
    brand_lower = brand.lower()

    selectors = [
        "img.logo",
        "img.brand",
        "img.site-logo",
        "header img",
    ]
    for selector in selectors:
        element = soup.select_one(selector)
        if element and element.get("src"):
            return "img", element["src"]

    for image in soup.find_all("img"):
        alt_text = (image.get("alt") or "").lower()
        classes = " ".join(image.get("class", [])).lower()
        if image.get("src") and ((brand_lower in alt_text and "logo" in alt_text) or "logo" in classes):
            return "img", image["src"]

    for anchor in soup.select('a[href="/"] img, a[href=""] img'):
        if anchor.get("src"):
            return "img", anchor["src"]

    header = soup.find("header")
    if header:
        inline_svg = header.find("svg")
        if inline_svg:
            return "svg", str(inline_svg)

    return None


def save_inline_svg(svg_markup: str, dataset_dir: str | Path, brand: str) -> Path:
    brand_dir = ensure_brand_dir(dataset_dir, brand)
    png_bytes = normalize_image_bytes(svg_markup.encode("utf-8"), source_extension=".svg")
    is_valid, errors = validate_image_bytes(png_bytes, allowed_formats={"PNG"})
    if not is_valid:
        raise ValueError(f"logo SVG invalido: {', '.join(errors)}")
    target_path = brand_dir / "site.png"
    target_path.write_bytes(png_bytes)
    update_brand_metadata(dataset_dir, brand, source="dom")
    return target_path


def download_dom_logo(
    domain: str,
    brand: str,
    dataset_dir: str | Path,
    timeout: int = 30,
    min_size: tuple[int, int] = (32, 32),
) -> Path:
    normalized_domain = normalize_domain(domain)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; brands-logos-dataset/1.0; +https://github.com/)"
    }
    response = requests.get(normalized_domain, timeout=timeout, headers=headers)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    candidate = find_logo_candidate(soup, brand)
    if candidate is None:
        raise LookupError("No se encontro un logo en el DOM con las heuristicas definidas.")

    kind, value = candidate
    if kind == "svg":
        return save_inline_svg(value, dataset_dir, brand)

    absolute_url = urljoin(normalized_domain, value)
    brand_dir = ensure_brand_dir(dataset_dir, brand)
    image_response = requests.get(absolute_url, timeout=timeout, headers=headers)
    image_response.raise_for_status()
    extension = Path(absolute_url).suffix.lower() or ".png"
    png_bytes = normalize_image_bytes(image_response.content, source_extension=extension)
    is_valid, errors = validate_image_bytes(png_bytes, min_size=min_size, allowed_formats={"PNG"})
    if not is_valid:
        raise ValueError(f"logo DOM invalido: {', '.join(errors)}")

    target_path = brand_dir / "site.png"
    target_path.write_bytes(png_bytes)
    update_brand_metadata(dataset_dir, brand, source="dom")
    return target_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extrae el logo principal desde el DOM de un sitio web.")
    parser.add_argument("--brand", required=True)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--dataset-dir", default="dataset")
    parser.add_argument("--timeout", type=int, default=30)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    saved_path = download_dom_logo(args.domain, args.brand, args.dataset_dir, timeout=args.timeout)
    print(f"[dom] Logo guardado en {saved_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
