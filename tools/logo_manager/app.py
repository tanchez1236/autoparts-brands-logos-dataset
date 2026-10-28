"""Gestor web interactivo de logos del dataset.

Servidor local (Flask) para listar, buscar, agregar, reemplazar y eliminar
marcas y logos sin ejecutar los scripts a mano.

Cada cambio mantiene sincronizadas todas las capas del dataset:

    dataset/<slug>/logo.png            imagen fuente + metadata.json
    logos/{original,optimized,thumb}/  variantes publicables
    brands-list.txt                    listado de marcas
    data/logos.json                    archivo publicable

Uso
---
    python tools/logo_manager/app.py
    python tools/logo_manager/app.py --port 5050 --no-browser
    python tools/logo_manager/app.py --host 0.0.0.0 --port 5000
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory
from PIL import Image
from werkzeug.exceptions import HTTPException

ROOT_DIR = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT_DIR / "tools"
UTILS_DIR = ROOT_DIR / "scrapers" / "utils"
for path in (str(UTILS_DIR), str(TOOLS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

import generate_data  # noqa: E402
import process_logos  # noqa: E402
from cleaners import convert_file_to_png  # noqa: E402
from downloader import (  # noqa: E402
    ensure_brand_dir,
    read_metadata,
    slugify_brand_name,
    write_metadata,
)

LOGOS_DIR = ROOT_DIR / "logos"
DATASET_DIR = ROOT_DIR / "dataset"
BRANDS_FILE = ROOT_DIR / "brands-list.txt"
DATA_FILE = ROOT_DIR / "data" / "logos.json"

VARIANTS = ("thumb", "optimized", "original")
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".svg"}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
# Las subidas se reducen (nunca se amplían) para no inflar el repositorio
MAX_SOURCE_SIZE = (1200, 1200)

REPO_URL = generate_data.DEFAULT_REPO_URL

# Serializa las escrituras sobre dataset/, logos/ y data/
_lock = threading.Lock()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0
app.config["JSON_SORT_KEYS"] = False


# ---------------------------------------------------------------------------
# brands-list.txt helpers
# ---------------------------------------------------------------------------

def _load_brand_list() -> list[str]:
    if not BRANDS_FILE.exists():
        return []
    return [line.strip() for line in BRANDS_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]


def _save_brand_list(brands: list[str]) -> None:
    BRANDS_FILE.write_text("\n".join(brands) + "\n", encoding="utf-8")


_listed_cache: tuple[float, dict[str, str]] = (0.0, {})


def _listed_names() -> dict[str, str]:
    """Map slug -> nombre tal como aparece en brands-list.txt (con caché por mtime)."""
    global _listed_cache
    mtime = BRANDS_FILE.stat().st_mtime if BRANDS_FILE.exists() else 0.0
    cached_mtime, cached_map = _listed_cache
    if cached_mtime == mtime and cached_map:
        return cached_map
    mapping: dict[str, str] = {}
    for line in _load_brand_list():
        mapping.setdefault(slugify_brand_name(line), line)
    _listed_cache = (mtime, mapping)
    return mapping


def _add_to_brand_list(brand_name: str) -> bool:
    brands = _load_brand_list()
    if slugify_brand_name(brand_name) in {slugify_brand_name(b) for b in brands}:
        return False
    brands.append(brand_name)
    _save_brand_list(sorted(brands, key=str.casefold))
    return True


def _remove_from_brand_list(slug: str) -> bool:
    brands = _load_brand_list()
    kept = [b for b in brands if slugify_brand_name(b) != slug]
    if len(kept) == len(brands):
        return False
    _save_brand_list(kept)
    return True


# ---------------------------------------------------------------------------
# Dataset helpers
# ---------------------------------------------------------------------------

def _display_name(slug: str, listed: dict[str, str] | None = None) -> str:
    """Mismo criterio que generate_data: metadata > brands-list > slug legible."""
    brand_dir = DATASET_DIR / slug
    if brand_dir.is_dir():
        metadata = read_metadata(brand_dir, slug)
        name = metadata.get("name") or metadata.get("brand") or ""
        if name and name != slug:
            return name
    listed = listed if listed is not None else _listed_names()
    if slug in listed:
        return listed[slug]
    return generate_data._slug_to_display_name(slug)


_dim_cache: dict[str, tuple[int, tuple[int, int] | None]] = {}


def _image_size(path: Path) -> tuple[int, int] | None:
    try:
        mtime = int(path.stat().st_mtime)
    except OSError:
        return None
    cached = _dim_cache.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with Image.open(path) as image:
            size = image.size
    except Exception:
        size = None
    _dim_cache[str(path)] = (mtime, size)
    return size


def _all_slugs() -> list[str]:
    slugs = {p.name for p in DATASET_DIR.iterdir() if p.is_dir()} if DATASET_DIR.is_dir() else set()
    original_dir = LOGOS_DIR / "original"
    if original_dir.is_dir():
        slugs.update(p.stem for p in original_dir.glob("*.png"))
    return sorted(slugs)


def _serialize(slug: str, listed: dict[str, str] | None = None) -> dict:
    # Solo se leen dimensiones de las variantes que usa la interfaz (las originales
    # pesan demasiado y se muestran en un contenedor de tamaño fijo).
    variants: dict[str, dict] = {}
    for variant in ("thumb", "optimized"):
        path = LOGOS_DIR / variant / f"{slug}.png"
        if not path.exists():
            continue
        size = _image_size(path)
        variants[variant] = {
            "url": f"/logos/{variant}/{slug}.png?v={int(path.stat().st_mtime)}",
            "width": size[0] if size else None,
            "height": size[1] if size else None,
        }

    original = LOGOS_DIR / "original" / f"{slug}.png"
    detail_url = f"/logos/original/{slug}.png?v={int(original.stat().st_mtime)}" if original.exists() else None

    image = variants.get("thumb") or variants.get("optimized")
    if image is None and detail_url:
        image = {"url": detail_url, "width": None, "height": None}

    return {
        "slug": slug,
        "name": _display_name(slug, listed),
        "variants": variants,
        "image": image["url"] if image else None,
        "width": image["width"] if image else None,
        "height": image["height"] if image else None,
        "hasLogo": image is not None,
        "detail": detail_url or (image["url"] if image else None),
    }


def _write_logos_json() -> None:
    original_dir = LOGOS_DIR / "original"
    slugs = sorted(p.stem for p in original_dir.glob("*.png")) if original_dir.is_dir() else []
    entries = [generate_data.build_entry(slug, DATASET_DIR, REPO_URL) for slug in slugs]
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _publish(slugs: list[str]) -> None:
    """Regenera las variantes de los slugs indicados y reescribe data/logos.json."""
    for slug in slugs:
        brand_dir = DATASET_DIR / slug
        if brand_dir.is_dir():
            process_logos.process_brand(brand_dir, LOGOS_DIR, slug, True)
    _write_logos_json()


def _remove_variants(slug: str) -> None:
    for variant in VARIANTS:
        target = LOGOS_DIR / variant / f"{slug}.png"
        if target.exists():
            target.unlink()


def _save_upload(file_storage, brand_dir: Path) -> None:
    filename = (file_storage.filename or "").strip()
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ApiError(
            f"Formato no soportado: '{suffix or filename}'. "
            f"Usa {', '.join(sorted(SUPPORTED_EXTENSIONS))}."
        )
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / f"upload{suffix}"
        file_storage.save(tmp_path)
        if tmp_path.stat().st_size == 0:
            raise ApiError("El archivo está vacío.")
        try:
            convert_file_to_png(
                tmp_path,
                target_path=brand_dir / "logo.png",
                target_size=MAX_SOURCE_SIZE,
                auto_trim=True,
            )
        except RuntimeError as exc:
            raise ApiError(str(exc)) from exc
        except Exception as exc:  # Pillow lanza distintos errores según el formato
            raise ApiError(f"No se pudo leer la imagen: {exc}") from exc


def _touch_metadata(brand: str, slug: str) -> None:
    """Marca la fuente 'manual' y refresca el conteo de imágenes de la marca."""
    brand_dir = DATASET_DIR / slug
    metadata = read_metadata(brand_dir, brand)
    sources = set(metadata.get("sources", [])) | {"manual"}
    write_metadata(brand_dir, brand, sources=sources, name=metadata.get("name") or brand)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@app.errorhandler(ApiError)
def _handle_api_error(error: ApiError):
    return jsonify({"error": error.message}), error.status


@app.errorhandler(HTTPException)
def _handle_http_error(error: HTTPException):
    if request.path.startswith("/api/"):
        return jsonify({"error": error.description}), error.code
    return error


@app.errorhandler(Exception)
def _handle_unexpected_error(error: Exception):
    app.logger.exception("Error inesperado")
    if request.path.startswith("/api/"):
        return jsonify({"error": f"Error inesperado: {error}"}), 500
    return "<h1>Error interno</h1>", 500


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/logos/<variant>/<path:filename>")
def logo_file(variant: str, filename: str):
    if variant not in VARIANTS:
        raise ApiError("Variante inválida.", 404)
    return send_from_directory(LOGOS_DIR / variant, filename, max_age=31536000)


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/api/brands")
def list_brands():
    listed = _listed_names()
    brands = [_serialize(slug, listed) for slug in _all_slugs()]
    brands.sort(key=lambda b: b["name"].casefold())
    return jsonify(
        {
            "brands": brands,
            "total": len(brands),
            "missing": sum(1 for b in brands if not b["hasLogo"]),
        }
    )


@app.post("/api/brands")
def create_brand():
    name = (request.form.get("name") or "").strip()
    if not name:
        raise ApiError("El nombre de la marca es obligatorio.")

    slug = slugify_brand_name(name)
    upload = request.files.get("file")

    with _lock:
        brand_dir = DATASET_DIR / slug
        if brand_dir.is_dir() or (LOGOS_DIR / "original" / f"{slug}.png").exists():
            raise ApiError(f"La marca '{name}' ya existe ({slug}).", 409)

        brand_dir = ensure_brand_dir(DATASET_DIR, name)
        if upload and upload.filename:
            try:
                _save_upload(upload, brand_dir)
            except ApiError:
                # La marca recién creada no debe quedar a medias si la imagen falla
                shutil.rmtree(brand_dir, ignore_errors=True)
                raise

        _touch_metadata(name, slug)
        _add_to_brand_list(name)
        _publish([slug])

    return jsonify(_serialize(slug)), 201


@app.post("/api/brands/<slug>/logo")
def replace_logo(slug: str):
    upload = request.files.get("file")
    if not upload or not upload.filename:
        raise ApiError("Falta el archivo de imagen.")

    with _lock:
        brand_dir = DATASET_DIR / slug
        if not brand_dir.is_dir():
            raise ApiError(f"La marca '{slug}' no existe.", 404)

        _save_upload(upload, brand_dir)
        _touch_metadata(slug, slug)
        _publish([slug])

    return jsonify(_serialize(slug))


@app.delete("/api/brands/<slug>/logo")
def delete_logo(slug: str):
    with _lock:
        brand_dir = DATASET_DIR / slug
        if not brand_dir.is_dir():
            raise ApiError(f"La marca '{slug}' no existe.", 404)
        if not any(brand_dir.glob("*.png")):
            raise ApiError("La marca no tiene logo.", 409)

        for image in brand_dir.glob("*.png"):
            image.unlink()
        _remove_variants(slug)
        _touch_metadata(slug, slug)
        _write_logos_json()

    return jsonify(_serialize(slug))


@app.delete("/api/brands/<slug>")
def delete_brand(slug: str):
    with _lock:
        brand_dir = DATASET_DIR / slug
        exists = brand_dir.is_dir() or (LOGOS_DIR / "original" / f"{slug}.png").exists()
        if not exists:
            raise ApiError(f"La marca '{slug}' no existe.", 404)

        if brand_dir.is_dir():
            shutil.rmtree(brand_dir)
        _remove_variants(slug)
        _remove_from_brand_list(slug)
        _write_logos_json()

    return jsonify({"deleted": slug})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gestor web interactivo de logos.")
    parser.add_argument("--host", default="127.0.0.1", help="Host del servidor (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Puerto (default: 5000)")
    parser.add_argument("--no-browser", action="store_true", help="No abrir el navegador automáticamente")
    parser.add_argument(
        "--repo-url",
        default=generate_data.DEFAULT_REPO_URL,
        help="URL base raw de GitHub usada para regenerar data/logos.json",
    )
    return parser.parse_args()


def main() -> int:
    global REPO_URL
    args = parse_args()
    REPO_URL = args.repo_url

    if not DATASET_DIR.is_dir():
        print(f"Error: no se encontró el directorio del dataset: {DATASET_DIR}", file=sys.stderr)
        return 1

    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.port}/"
    print(f"Gestor de logos disponible en {url}")
    print("Ctrl+C para detener el servidor.\n")
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
