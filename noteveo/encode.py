"""Del fotograma lineal al PNG de 16 bits y al clip HEVC de 10 bits (research.md R1)."""

import hashlib
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np

from noteveo.color import luminance

# La tele muestra el vídeo SDR con gamma 2,4 (BT.1886); codificar con su inversa hace que lo que
# sale de la pantalla sea proporcional al valor lineal del fotograma.
DISPLAY_GAMMA = 2.4
LEVELS = 1023  # 10 bits
DITHER_SEED = 20261020


def to_codes(linear: np.ndarray) -> np.ndarray:
    """Valores de código de 10 bits, sin redondear."""
    return np.clip(linear, 0.0, 1.0) ** (1 / DISPLAY_GAMMA) * LEVELS


def max_neighbor_step(codes: np.ndarray) -> float:
    """Mayor diferencia entre píxeles vecinos, en niveles de 10 bits (SC-005)."""
    dx = np.abs(np.diff(codes, axis=1)).max()
    dy = np.abs(np.diff(codes, axis=0)).max()
    return float(max(dx, dy))


def quantize(codes: np.ndarray) -> np.ndarray:
    """Tramado triangular de ±1 nivel con semilla fija: sin bandas y siempre igual (SC-003)."""
    rng = np.random.default_rng(DITHER_SEED)
    noise = rng.random(codes.shape) - rng.random(codes.shape)
    return np.clip(np.round(codes + noise), 0, LEVELS).astype(np.uint16)


def apl(quantized: np.ndarray) -> float:
    """Nivel medio de la imagen, en % del blanco máximo."""
    return float(luminance(quantized.astype(np.float64) / LEVELS).mean() * 100)


def write_png(quantized: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bgr = (quantized.astype(np.uint16) << 6)[..., ::-1]
    if not cv2.imwrite(str(path), np.ascontiguousarray(bgr)):
        raise OSError(f"no se pudo escribir {path}")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def encode_clip(png: Path, clip: Path, seconds: int) -> None:
    """Clip HEVC 10 bits BT.709 de un fotograma repetido."""
    if shutil.which("ffmpeg") is None:
        raise OSError("no se encuentra ffmpeg en el PATH")
    command = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-framerate", "30", "-i", str(png), "-t", str(seconds),
        "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p10le",
        "-c:v", "libx265", "-preset", "medium", "-crf", "12",
        "-x265-params", "log-level=error:colorprim=bt709:transfer=bt709:"
        "colormatrix=bt709:range=limited",
        "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
        "-color_range", "tv", "-tag:v", "hvc1", "-an",
        "-fflags", "+bitexact", "-flags:v", "+bitexact",
        str(clip),
    ]  # fmt: skip
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise OSError(f"ffmpeg falló: {result.stderr.strip()}")
