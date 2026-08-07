from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
UTILS_DIR = ROOT_DIR / "scrapers" / "utils"
if str(UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(UTILS_DIR))

from cleaners import convert_file_to_png
from downloader import (
    ensure_brand_dir,
    read_metadata,
    slugify_brand_name,
    update_brand_metadata,
)

DEFAULT_REPO_URL = (
    "https://raw.githubusercontent.com/tanchez1236/autoparts-brands-logos-dataset/master"
)
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".svg"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Agregar una marca/nuevo logo o actualizar el logo de una marca existente."
    )
    parser.add_argument(
        "--action",
        choices=["add", "update"],
        help=(
            "Modo de operación: 'add' para agregar marca + logo, "
            "'update' para reemplazar solo el logo existente. Si se omite, se pedirá interactivo."
        ),
    )
    parser.add_argument("--brand", help="Nombre de la marca, por ejemplo: Bosch")
    parser.add_argument("--logo", help="Ruta local al archivo de logo")
    parser.add_argument(
        "--dataset-dir",
        default="dataset",
        help="Directorio raíz del dataset (default: dataset)",
    )
    parser.add_argument(
        "--brand-list-file",
        default="brands-list.txt",
        help="Ruta al archivo brands-list.txt (default: brands-list.txt)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Permite sobrescribir un logo existente cuando se agrega o actualiza.",
    )
    parser.add_argument(
        "--generate-data",
        action="store_true",
        help="Ejecuta process_logos.py y generate_data.py al final para sincronizar logos/ y data/logos.json.",
    )
    parser.add_argument(
        "--repo-url",
        default=DEFAULT_REPO_URL,
        help="URL base raw de GitHub para generar data/logos.json si se usa --generate-data.",
    )
    return parser.parse_args()


def prompt_action() -> str:
    prompt = (
        "Selecciona una opción:\n"
        "  1) Agregar marca y logo\n"
        "  2) Actualizar logo existente\n"
        "Elige 1 o 2: "
    )
    while True:
        choice = input(prompt).strip()
        if choice == "1":
            return "add"
        if choice == "2":
            return "update"
        print("Opción inválida. Ingresa 1 o 2.")


def prompt_text(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("Este valor es obligatorio. Intenta de nuevo.")


def prompt_yes_no(prompt: str, default: bool = True) -> bool:
    default_suffix = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{prompt} ({default_suffix}): ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes", "s", "si"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Por favor ingresa 'y' o 'n'.")


def prompt_brand() -> str:
    return prompt_text("Nombre de la marca: ")


def prompt_logo() -> str:
    return prompt_text("Ruta local del archivo de logo: ")


def load_brand_list(brand_list_path: Path) -> list[str]:
    if not brand_list_path.exists():
        return []
    return [line.strip() for line in brand_list_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def save_brand_list(brand_list_path: Path, brands: list[str]) -> None:
    brand_list_path.write_text("\n".join(brands) + "\n", encoding="utf-8")


def add_brand_to_list(brand_list_path: Path, brand_name: str) -> bool:
    brands = load_brand_list(brand_list_path)
    if brand_name in brands:
        return False
    brands.append(brand_name)
    save_brand_list(brand_list_path, sorted(brands, key=str.casefold))
    return True


def validate_logo_path(logo_path: Path) -> None:
    if not logo_path.exists() or not logo_path.is_file():
        raise FileNotFoundError(f"Logo no encontrado: {logo_path}")
    if logo_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Extensión de logo no soportada: {logo_path.suffix}. "
            f"Soportadas: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )


def ensure_dataset_dir(dataset_root: Path) -> None:
    if not dataset_root.exists():
        dataset_root.mkdir(parents=True, exist_ok=True)


def update_logo(
    dataset_root: Path,
    brand_name: str,
    logo_path: Path,
    action: str,
    force: bool,
    brand_list_path: Path,
) -> tuple[str, Path]:
    slug = slugify_brand_name(brand_name)
    brand_dir = ensure_brand_dir(dataset_root, brand_name)
    existing = read_metadata(brand_dir, slug)
    logo_dest = brand_dir / "logo.png"
    brand_exists = logo_dest.exists() or any(brand_dir.iterdir())

    if action == "add" and brand_exists and not force:
        raise FileExistsError(
            f"La marca '{brand_name}' ya existe en {brand_dir}. Usa --force para reemplazar su logo."
        )
    if action == "update" and not brand_exists:
        raise FileNotFoundError(
            f"La marca '{brand_name}' no existe. Usa action 'add' para crearla."
        )

    if logo_dest.exists() and not force and action == "update":
        print(f"Reemplazando logo existente de '{brand_name}'...")
    elif logo_dest.exists() and force:
        print(f"Sobrescribiendo logo existente de '{brand_name}' (force)...")

    convert_file_to_png(logo_path, target_path=logo_dest)
    update_brand_metadata(dataset_root, brand_name, source="manual", name=brand_name)

    brand_added = add_brand_to_list(brand_list_path, brand_name)
    if brand_added:
        print(f"Marca '{brand_name}' agregada a {brand_list_path}")

    return slug, brand_dir


def run_pipeline(slug: str, generate_data: bool, repo_url: str) -> None:
    print("Ejecutando process_logos.py para el slug procesado...")
    subprocess.run(
        [sys.executable, str(ROOT_DIR / "tools" / "process_logos.py"), "--slug", slug, "--force"],
        check=True,
    )
    if generate_data:
        print("Generando data/logos.json...")
        subprocess.run(
            [
                sys.executable,
                str(ROOT_DIR / "tools" / "generate_data.py"),
                "--repo-url",
                repo_url,
                "--quiet",
            ],
            check=True,
        )


def main() -> int:
    args = parse_args()
    if args.action is None:
        args.action = prompt_action()
    if args.brand is None:
        args.brand = prompt_brand()
    if args.logo is None:
        args.logo = prompt_logo()

    if not args.generate_data:
        args.generate_data = prompt_yes_no(
            "¿Deseas ejecutar process_logos.py y generar data/logos.json al final?",
            default=True,
        )

    dataset_root = (ROOT_DIR / args.dataset_dir).resolve()
    brand_list_path = (ROOT_DIR / args.brand_list_file).resolve()
    logo_path = Path(args.logo).expanduser().resolve()

    try:
        validate_logo_path(logo_path)
        ensure_dataset_dir(dataset_root)
        slug, brand_dir = update_logo(
            dataset_root,
            args.brand,
            logo_path,
            args.action,
            args.force,
            brand_list_path,
        )

        print(f"\n✓ Marca procesada: {args.brand} ({slug})")
        print(f"  dataset dir: {brand_dir}")
        print(f"  logo guardado en: {brand_dir / 'logo.png'}")

        if args.generate_data:
            run_pipeline(slug, args.generate_data, args.repo_url)

        return 0
    except FileExistsError as exc:
        if args.action == "add" and prompt_yes_no(
            f"{exc} ¿Deseas sobrescribir el logo existente?", default=False
        ):
            args.force = True
            try:
                slug, brand_dir = update_logo(
                    dataset_root,
                    args.brand,
                    logo_path,
                    args.action,
                    args.force,
                    brand_list_path,
                )
                print(f"\n✓ Marca procesada: {args.brand} ({slug})")
                print(f"  dataset dir: {brand_dir}")
                print(f"  logo guardado en: {brand_dir / 'logo.png'}")
                if args.generate_data:
                    run_pipeline(slug, args.generate_data, args.repo_url)
                return 0
            except Exception as inner_exc:
                print(f"Error: {inner_exc}", file=sys.stderr)
                return 1
        print("Operación cancelada.")
        return 1
    except FileNotFoundError as exc:
        if args.action == "update" and prompt_yes_no(
            f"{exc} ¿Deseas crear la marca y agregar el logo?", default=True
        ):
            args.action = "add"
            try:
                slug, brand_dir = update_logo(
                    dataset_root,
                    args.brand,
                    logo_path,
                    args.action,
                    args.force,
                    brand_list_path,
                )
                print(f"\n✓ Marca procesada: {args.brand} ({slug})")
                print(f"  dataset dir: {brand_dir}")
                print(f"  logo guardado en: {brand_dir / 'logo.png'}")
                if args.generate_data:
                    run_pipeline(slug, args.generate_data, args.repo_url)
                return 0
            except Exception as inner_exc:
                print(f"Error: {inner_exc}", file=sys.stderr)
                return 1
        print("Operación cancelada.")
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
