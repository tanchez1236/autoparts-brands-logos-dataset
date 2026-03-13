from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageStat, UnidentifiedImageError

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".svg"}


def is_supported_extension(extension: str) -> bool:
    return extension.lower() in SUPPORTED_EXTENSIONS


def _open_image(raw_bytes: bytes) -> Image.Image:
    image = Image.open(BytesIO(raw_bytes))
    image.load()
    return image


def is_not_corrupted(raw_bytes: bytes) -> bool:
    try:
        image = Image.open(BytesIO(raw_bytes))
        image.verify()
        return True
    except (UnidentifiedImageError, OSError, SyntaxError):
        return False


def validate_minimum_size(raw_bytes: bytes, min_size: tuple[int, int] = (64, 64)) -> bool:
    try:
        image = _open_image(raw_bytes)
    except (UnidentifiedImageError, OSError):
        return False
    return image.width >= min_size[0] and image.height >= min_size[1]


def looks_like_logo(raw_bytes: bytes) -> bool:
    try:
        image = _open_image(raw_bytes).convert("RGBA")
    except (UnidentifiedImageError, OSError):
        return False

    if image.width == 0 or image.height == 0:
        return False

    colors = image.getcolors(maxcolors=2048)
    alpha = image.getchannel("A")
    alpha_values = list(alpha.getdata())
    transparent_ratio = sum(1 for value in alpha_values if value < 245) / len(alpha_values)

    grayscale = image.convert("L")
    contrast = ImageStat.Stat(grayscale).stddev[0]
    aspect_ratio = image.width / image.height

    if 0.15 <= transparent_ratio <= 0.98:
        return True

    if colors is not None and 2 <= len(colors) <= 256 and contrast >= 18 and 0.3 <= aspect_ratio <= 6.0:
        return True

    if colors is None and contrast >= 28 and 0.4 <= aspect_ratio <= 5.5:
        return True

    return False


def validate_image_bytes(
    raw_bytes: bytes,
    min_size: tuple[int, int] = (64, 64),
    allowed_formats: Iterable[str] | None = None,
    skip_logo_heuristic: bool = False,
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    allowed_formats = {item.upper() for item in (allowed_formats or {"PNG", "JPEG", "WEBP", "BMP", "GIF"})}

    if not raw_bytes:
        return False, ["archivo vacio"]

    if not is_not_corrupted(raw_bytes):
        errors.append("imagen corrupta o ilegible")
        return False, errors

    try:
        image = _open_image(raw_bytes)
    except (UnidentifiedImageError, OSError):
        return False, ["no fue posible abrir la imagen"]

    if image.format and image.format.upper() not in allowed_formats:
        errors.append(f"formato no permitido: {image.format}")

    if image.width < min_size[0] or image.height < min_size[1]:
        errors.append(f"tamano insuficiente: {image.width}x{image.height}")

    if not skip_logo_heuristic and not looks_like_logo(raw_bytes):
        errors.append("heuristica de logo no superada")

    return not errors, errors


def validate_image_file(
    image_path: str | Path,
    min_size: tuple[int, int] = (64, 64),
    allowed_formats: Iterable[str] | None = None,
) -> tuple[bool, list[str]]:
    path = Path(image_path)
    if not path.exists():
        return False, ["archivo inexistente"]

    if not is_supported_extension(path.suffix):
        return False, [f"extension no soportada: {path.suffix}"]

    raw_bytes = path.read_bytes()
    return validate_image_bytes(raw_bytes, min_size=min_size, allowed_formats=allowed_formats)
