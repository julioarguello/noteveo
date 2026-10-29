"""Vídeos de barrido: pasos numerados para que Julio elija a ojo el que casa con la pared.

La cámara del móvil no ve la pantalla OLED como el ojo (research.md R5, 2026-10-22), así que el
instrumento es el ojo: cada paso se mantiene unos segundos con su número en una esquina, y Julio
dice qué número se confunde con la pared.
"""

import csv
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from noteveo import encode

WIDTH, HEIGHT = 3840, 2160
# El reloj de Aerial Views está abajo a la izquierda: el número va arriba a la derecha.
LABEL_ORIGIN = (WIDTH - 260, 150)
LABEL_SCALE = 3.0
LABEL_THICKNESS = 6
LABEL_OFFSET = 60  # niveles de 10 bits por encima (o por debajo) del fondo: se lee sin gritar


@dataclass
class Step:
    number: int
    rgb: tuple[float, float, float]  # luz lineal, 0 a 1 del blanco de la tele


def brightness_steps(count: int, low: float, high: float) -> list[Step]:
    """Grises neutros en progresión geométrica: cada paso, el mismo salto relativo de luz."""
    levels = np.geomspace(low, high, count)
    return [Step(i + 1, (float(v), float(v), float(v))) for i, v in enumerate(levels)]


def step_codes(step: Step) -> np.ndarray:
    """Fotograma de 10 bits: el color del paso y su número."""
    codes = np.broadcast_to(encode.to_codes(np.asarray(step.rgb)), (HEIGHT, WIDTH, 3)).copy()
    base = float(codes[0, 0].mean())
    label = base + LABEL_OFFSET if base + LABEL_OFFSET <= encode.LEVELS else base - LABEL_OFFSET
    mask = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)  # putText solo dibuja en 8 bits
    cv2.putText(
        mask,
        f"{step.number:02d}",
        LABEL_ORIGIN,
        cv2.FONT_HERSHEY_SIMPLEX,
        LABEL_SCALE,
        255,
        LABEL_THICKNESS,
        cv2.LINE_AA,
    )
    alpha = (mask / 255.0)[..., None]
    return encode.quantize(codes * (1 - alpha) + label * alpha)


def write_sweep(steps: list[Step], clip: Path, table: Path, hold: int) -> int:
    """Clip con los pasos seguidos, `hold` segundos cada uno, y su tabla; devuelve la duración."""
    if shutil.which("ffmpeg") is None:
        raise OSError("no se encuentra ffmpeg en el PATH")
    clip.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for step in steps:
            png = Path(tmp) / f"paso-{step.number:02d}.png"
            part = Path(tmp) / f"paso-{step.number:02d}.mp4"
            encode.write_png(step_codes(step), png)
            encode.encode_clip(png, part, hold, segment=min(hold, 2))
            parts.append(part)
        listing = Path(tmp) / "pasos.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in parts))
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(listing),
                "-c",
                "copy",
                "-tag:v",
                "hvc1",
                str(clip),
            ],  # fmt: skip
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise OSError(f"ffmpeg falló: {result.stderr.strip()}")
    with table.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["paso", "desde_s", "r_lineal", "g_lineal", "b_lineal", "codigo_10bit"])
        for i, step in enumerate(steps):
            code = encode.to_codes(np.asarray(step.rgb))
            writer.writerow(
                [step.number, i * hold, *(f"{c:.4f}" for c in step.rgb), f"{code.mean():.1f}"]
            )
    return len(steps) * hold
