"""Leer fotos en luz lineal y sus datos EXIF."""

from dataclasses import dataclass
from pathlib import Path

import cv2
import exifread
import numpy as np
import rawpy

from noteveo.color import srgb_to_linear


class PhotoError(ValueError):
    """La foto no se puede leer."""


@dataclass
class Exif:
    taken_at: str
    exposure: str
    iso: str


def load_linear(path: Path) -> np.ndarray:
    """RGB lineal en [0, 1] con primarios sRGB: DNG sin curva de tono; JPEG o PNG, desde sRGB."""
    if not path.exists():
        raise PhotoError(f"no existe {path}")
    if path.suffix.lower() == ".dng":
        with rawpy.imread(str(path)) as raw:
            rgb = raw.postprocess(
                gamma=(1, 1),
                no_auto_bright=True,
                use_camera_wb=True,
                output_color=rawpy.ColorSpace.sRGB,
                output_bps=16,
            )
        return rgb.astype(np.float64) / 65535.0
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise PhotoError(f"no se puede leer {path}")
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    rgb = image[..., :3][..., ::-1]
    scale = 65535.0 if rgb.dtype == np.uint16 else 255.0
    return srgb_to_linear(rgb.astype(np.float64) / scale)


def saturation_level(path: Path) -> float:
    """Valor a partir del cual un canal se considera quemado."""
    return 0.98 if path.suffix.lower() == ".dng" else 0.97


def read_exif(path: Path) -> Exif:
    with path.open("rb") as fh:
        tags = exifread.process_file(fh, details=False)

    def tag(name: str) -> str:
        value = tags.get(name)
        return str(value).strip() if value is not None else ""

    taken = tag("EXIF DateTimeOriginal") or tag("Image DateTime")
    if taken:
        date, _, time = taken.partition(" ")
        taken = f"{date.replace(':', '-')}T{time}{tag('EXIF OffsetTimeOriginal')}"
    return Exif(
        taken_at=taken,
        exposure=tag("EXIF ExposureTime"),
        iso=tag("EXIF ISOSpeedRatings") or tag("EXIF PhotographicSensitivity"),
    )
