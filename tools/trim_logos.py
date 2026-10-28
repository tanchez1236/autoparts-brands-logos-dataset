"""Recorta los márgenes vacíos de los logos ya existentes en el dataset.

Para cada marca toma la mejor imagen fuente de `dataset/<slug>/`, elimina el
espacio transparente o blanco que rodea al logo, la guarda en su sitio y
regenera las variantes publicables (`logos/`) y `data/logos.json`.

Es idempotente: si un logo ya está recortado no se toca (ni se vuelve a
escribir el archivo).

Uso
---
    python tools/trim_logos.py --dry-run      # ver qué cambiaría, sin escribir nada
    python tools/trim_logos.py                # recortar todo y republicar
    python tools/trim_logos.py --slug bosch   # una sola marca
    python tools/trim_logos.py --no-publish   # recortar sin regenerar logos/ ni logos.json
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image

ROOT_DIR = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT_DIR / "tools"
UTILS_DIR = ROOT_DIR / "scrapers" / "utils"
for path in (str(UTILS_DIR), str(TOOLS_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

import generate_data  # noqa: E402
import process_logos  # noqa: E402
from cleaners import trim_margins  # noqa: E402
from validators import validate_image_bytes  # noqa: E402

# Mismos límites que usa tools/verify.py para dar una imagen por válida
VALIDATION_MIN_SIZE = (64, 64)


def _is_valid_image(payload: bytes) -> bool:
    is_valid, _ = validate_image_bytes(payload, min_size=VALIDATION_MIN_SIZE, allowed_formats={"PNG"})
    return is_valid


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recorta los márgenes vacíos de los logos del dataset."
    )
    parser.add_argument("--dataset-dir", default="dataset", help="Directorio del dataset (default: dataset)")
    parser.add_argument("--logos-dir", default="logos", help="Directorio de logos publicados (default: logos)")
    parser.add_argument("--slug", default=None, help="Procesar solo esta marca (slug)")
    parser.add_argument(
        "--min-gain",
        type=float,
        default=2.0,
        metavar="PCT",
        help=(
            "Recortar solo si se elimina al menos este porcentaje de área (default: 2). "
            "Usa 0 para quitar también bordes de 1 px."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar qué cambiaría, sin escribir nada")
    parser.add_argument("--no-publish", action="store_true", help="Recortar sin regenerar logos/ ni data/logos.json")
    parser.add_argument("--repo-url", default=generate_data.DEFAULT_REPO_URL, help="URL base raw para data/logos.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset_dir = (ROOT_DIR / args.dataset_dir).resolve()
    logos_dir = (ROOT_DIR / args.logos_dir).resolve()

    if not dataset_dir.is_dir():
        print(f"Error: no se encontró el dataset en {dataset_dir}", file=sys.stderr)
        return 1

    if args.slug:
        brand_dirs = [dataset_dir / args.slug]
        if not brand_dirs[0].is_dir():
            print(f"Error: la marca '{args.slug}' no existe en {dataset_dir}", file=sys.stderr)
            return 1
    else:
        brand_dirs = sorted(path for path in dataset_dir.iterdir() if path.is_dir())

    trimmed = 0
    untouched = 0
    no_source = 0
    kept_original = 0
    saved_pixels = 0

    for brand_dir in brand_dirs:
        slug = brand_dir.name
        source = process_logos._best_logo_path(brand_dir)
        if source is None:
            no_source += 1
            continue

        try:
            with Image.open(source) as opened:
                opened.load()
                original = opened.convert("RGBA")
        except Exception as exc:
            print(f"  [skip] {slug}: no se pudo abrir {source.name} — {exc}")
            no_source += 1
            continue

        cropped = trim_margins(original)
        if cropped.size == original.size:
            untouched += 1
            continue

        gain = 100 * (1 - (cropped.width * cropped.height) / (original.width * original.height))
        if gain < args.min_gain:
            untouched += 1
            continue

        buffer = BytesIO()
        cropped.save(buffer, format="PNG", optimize=True)
        payload = buffer.getvalue()

        # El recorte nunca debe empeorar el resultado de tools/verify.py
        original_valid = _is_valid_image(source.read_bytes())
        if original_valid and not _is_valid_image(payload):
            print(f"  [conservar] {slug}: el recorte no supera la validación, se deja el original")
            kept_original += 1
            continue

        trimmed += 1
        saved_pixels += original.width * original.height - cropped.width * cropped.height
        print(f"  {slug:28} {original.width}x{original.height} -> {cropped.width}x{cropped.height}")

        if args.dry_run:
            continue

        source.write_bytes(payload)
        if not args.no_publish:
            process_logos.process_brand(brand_dir, logos_dir, slug, True)

    if trimmed and not args.dry_run and not args.no_publish:
        print("\nRegenerando data/logos.json...")
        subprocess.run(
            [
                sys.executable,
                str(TOOLS_DIR / "generate_data.py"),
                "--dataset-dir",
                str(dataset_dir),
                "--logos-dir",
                str(logos_dir),
                "--repo-url",
                args.repo_url,
                "--quiet",
            ],
            check=True,
        )

    mode = " (simulación, sin cambios en disco)" if args.dry_run else ""
    print(
        f"\nRecortadas: {trimmed} · sin cambios: {untouched} · sin imagen: {no_source}"
        f" · conservadas por validación: {kept_original}"
        f" · píxeles liberados: {saved_pixels:,}{mode}"
    )
    if args.dry_run and trimmed:
        print("Ejecuta sin --dry-run para aplicar los cambios.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
