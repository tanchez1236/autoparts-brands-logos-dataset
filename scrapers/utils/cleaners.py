from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

try:
    import cairosvg
except (ImportError, OSError):  # pragma: no cover
    cairosvg = None


# Resolution used when rasterising SVG logos — keeps them crisp at original size
_SVG_RASTER_WIDTH = 512


def _load_image_from_bytes(raw_bytes: bytes, extension: str = "") -> Image.Image:
    if extension.lower() == ".svg":
        if cairosvg is None:
            raise RuntimeError("cairosvg es requerido para convertir SVG a PNG")
        # Rasterise at high resolution so the PNG source is always sharp
        raw_bytes = cairosvg.svg2png(bytestring=raw_bytes, output_width=_SVG_RASTER_WIDTH)
    image = Image.open(BytesIO(raw_bytes))
    image.load()
    return image


def remove_background(image: Image.Image, threshold: int = 245) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = []
    for red, green, blue, alpha in rgba.getdata():
        if red >= threshold and green >= threshold and blue >= threshold:
            pixels.append((red, green, blue, 0))
        else:
            pixels.append((red, green, blue, alpha))
    rgba.putdata(pixels)
    return rgba


def resize_image(image: Image.Image, size: tuple[int, int] | None = None) -> Image.Image:
    if size is None:
        return image
    resized = image.copy()
    resized.thumbnail(size, Image.Resampling.LANCZOS)
    return resized


def normalize_image_bytes(
    raw_bytes: bytes,
    source_extension: str = "",
    target_size: tuple[int, int] | None = None,
    strip_background: bool = False,
) -> bytes:
    image = _load_image_from_bytes(raw_bytes, extension=source_extension)
    image = image.convert("RGBA")

    if strip_background:
        image = remove_background(image)

    image = resize_image(image, target_size)

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def convert_file_to_png(
    image_path: str | Path,
    target_path: str | Path | None = None,
    target_size: tuple[int, int] | None = None,
    strip_background: bool = False,
) -> Path:
    source = Path(image_path)
    destination = Path(target_path) if target_path else source.with_suffix(".png")
    png_bytes = normalize_image_bytes(
        source.read_bytes(),
        source_extension=source.suffix,
        target_size=target_size,
        strip_background=strip_background,
    )
    destination.write_bytes(png_bytes)
    return destination
