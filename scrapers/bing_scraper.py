from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import requests

CURRENT_DIR = Path(__file__).resolve().parent
UTILS_DIR = CURRENT_DIR / "utils"
if str(UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(UTILS_DIR))

from downloader import download_image, load_brands, update_brand_metadata


def search_bing_images(
    brand: str,
    api_key: str,
    endpoint: str,
    limit: int,
    pause_seconds: float,
    session: requests.Session,
) -> list[str]:
    urls: list[str] = []
    offset = 0

    while len(urls) < limit:
        batch_size = min(50, limit - len(urls))
        headers = {"Ocp-Apim-Subscription-Key": api_key}
        params = {
            "q": f"{brand} logo png",
            "count": batch_size,
            "offset": offset,
            "safeSearch": "Off",
            "imageType": "Transparent",
            # Request only images with sufficient resolution for a high-quality original
            "minWidth": 300,
            "minHeight": 300,
        }
        response = session.get(endpoint, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        items = payload.get("value", [])
        if not items:
            break

        urls.extend(item["contentUrl"] for item in items if item.get("contentUrl"))
        offset += len(items)
        time.sleep(pause_seconds)

        if len(items) < batch_size:
            break

    return urls[:limit]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Descarga logos usando Bing Image Search API.")
    parser.add_argument("--brands-file", default="brands-list.txt")
    parser.add_argument("--dataset-dir", default="dataset")
    parser.add_argument("--api-key", default=os.getenv("BING_IMAGE_SEARCH_API_KEY"))
    parser.add_argument(
        "--endpoint",
        default=os.getenv("BING_IMAGE_SEARCH_ENDPOINT", "https://api.bing.microsoft.com/v7.0/images/search"),
    )
    parser.add_argument("--per-brand", type=int, default=5)
    parser.add_argument("--pause", type=float, default=0.5)
    parser.add_argument("--strip-background", action="store_true")
    parser.add_argument("--target-size", nargs=2, type=int, metavar=("WIDTH", "HEIGHT"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.api_key:
        raise SystemExit("Falta la credencial de Bing: --api-key o BING_IMAGE_SEARCH_API_KEY.")

    session = requests.Session()
    brands = load_brands(args.brands_file)
    total_downloaded = 0

    for brand in brands:
        downloaded_for_brand = 0
        try:
            image_urls = search_bing_images(
                brand=brand,
                api_key=args.api_key,
                endpoint=args.endpoint,
                limit=args.per_brand,
                pause_seconds=args.pause,
                session=session,
            )
        except requests.RequestException as exc:
            print(f"[bing] Error consultando {brand}: {exc}")
            continue

        for image_url in image_urls:
            try:
                download_image(
                    image_url,
                    args.dataset_dir,
                    brand,
                    source="bing",
                    session=session,
                    target_size=tuple(args.target_size) if args.target_size else None,
                    strip_background=args.strip_background,
                )
                downloaded_for_brand += 1
            except Exception as exc:  # noqa: BLE001
                print(f"[bing] Fallo descargando {brand} desde {image_url}: {exc}")

        if downloaded_for_brand:
            update_brand_metadata(args.dataset_dir, brand, source="bing")
        total_downloaded += downloaded_for_brand
        print(f"[bing] {brand}: {downloaded_for_brand} imagen(es) guardadas")

    print(f"[bing] Total descargado: {total_downloaded}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
