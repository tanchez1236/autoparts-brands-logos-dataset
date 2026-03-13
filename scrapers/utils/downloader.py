from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

import requests

from cleaners import normalize_image_bytes
from validators import is_supported_extension, validate_image_bytes


def load_brands(brands_file: str | Path) -> list[str]:
    path = Path(brands_file)
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def slugify_brand_name(brand: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", brand.lower()).strip("-")
    return slug or "unknown-brand"


def ensure_brand_dir(dataset_root: str | Path, brand: str) -> Path:
    brand_dir = Path(dataset_root) / slugify_brand_name(brand)
    brand_dir.mkdir(parents=True, exist_ok=True)
    return brand_dir


def _guess_extension(url: str, content_type: str = "") -> str:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".svg"}:
        return suffix

    content_type = content_type.lower()
    if "svg" in content_type:
        return ".svg"
    if "png" in content_type:
        return ".png"
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    if "webp" in content_type:
        return ".webp"
    if "gif" in content_type:
        return ".gif"
    if "bmp" in content_type:
        return ".bmp"
    return ".png"


def _next_incremental_path(brand_dir: Path) -> Path:
    indices = []
    for image_path in brand_dir.glob("*.png"):
        if image_path.stem.isdigit():
            indices.append(int(image_path.stem))
    next_index = (max(indices) + 1) if indices else 1
    return brand_dir / f"{next_index:03d}.png"


def _metadata_path(brand_dir: Path) -> Path:
    return brand_dir / "metadata.json"


def read_metadata(brand_dir: Path, brand: str) -> dict:
    metadata_path = _metadata_path(brand_dir)
    if metadata_path.exists():
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    return {"brand": brand, "count": 0, "sources": []}


def write_metadata(brand_dir: Path, brand: str, sources: set[str] | None = None, name: str | None = None) -> dict:
    existing = read_metadata(brand_dir, brand)
    sources = sources or set(existing.get("sources", []))
    count = len([path for path in brand_dir.glob("*.png") if path.name != "site.png"]) + (1 if (brand_dir / "site.png").exists() else 0)
    canonical_name = name or existing.get("name") or brand
    metadata = {
        "brand": slugify_brand_name(brand),
        "name": canonical_name,
        "count": count,
        "sources": sorted(sources),
    }
    _metadata_path(brand_dir).write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return metadata


def update_brand_metadata(dataset_root: str | Path, brand: str, source: str | None = None, name: str | None = None) -> dict:
    brand_dir = ensure_brand_dir(dataset_root, brand)
    metadata = read_metadata(brand_dir, brand)
    sources = set(metadata.get("sources", []))
    if source:
        sources.add(source)
    return write_metadata(brand_dir, brand, sources=sources, name=name)


def download_image(
    image_url: str,
    dataset_root: str | Path,
    brand: str,
    source: str,
    *,
    filename: str | None = None,
    timeout: int = 30,
    session: requests.Session | None = None,
    target_size: tuple[int, int] | None = None,
    strip_background: bool = False,
    min_size: tuple[int, int] = (64, 64),
    skip_logo_heuristic: bool = False,
) -> Path | None:
    client = session or requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; brands-logos-dataset/1.0; +https://github.com/)"
    }
    response = client.get(image_url, timeout=timeout, headers=headers)
    response.raise_for_status()

    extension = _guess_extension(image_url, response.headers.get("Content-Type", ""))
    if not is_supported_extension(extension):
        return None

    png_bytes = normalize_image_bytes(
        response.content,
        source_extension=extension,
        target_size=target_size,
        strip_background=strip_background,
    )
    is_valid, errors = validate_image_bytes(
        png_bytes,
        min_size=min_size,
        allowed_formats={"PNG"},
        skip_logo_heuristic=skip_logo_heuristic,
    )
    if not is_valid:
        raise ValueError(f"imagen invalida: {', '.join(errors)}")

    brand_dir = ensure_brand_dir(dataset_root, brand)
    target_path = brand_dir / filename if filename else _next_incremental_path(brand_dir)
    target_path.write_bytes(png_bytes)
    update_brand_metadata(dataset_root, brand, source)
    return target_path
