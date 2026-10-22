"""Medir una foto de calibración: dentro y fuera del marco en tres lados (research.md R5)."""

from dataclasses import dataclass

import cv2
import numpy as np

from noteveo.color import delta_e, luminance
from noteveo.geometry import MIN_AREA_FRACTION, order_corners, rectify, warp

SIDES = ("top", "left", "right")  # abajo no hay pared que medir
MEASURE_WIDTH = 960
# Franjas, en fracción del ancho de la pantalla.
INSIDE = (0.005, 0.02)  # desde el borde interior del canto negro hacia dentro
OUTSIDE = 0.015  # ancho de la franja de pared, a partir de donde acaba el canto
REFERENCE = (0.05, 0.07)  # la foto tiene que llegar hasta aquí fuera del borde
SEARCH = 0.05  # hasta dónde se busca el final del canto
BEZEL_MAX = 0.03  # el punto más oscuro del canto está antes de esto
NEAR_WALL = (0.01, 0.025)  # pared justo después del canto, para saber dónde acaba
# La pared fuera se lleva a la luminancia de la pintura (L* ≈ 96) para calcular ΔE.
WALL_Y = 0.9


class MeasureError(ValueError):
    """La foto no sirve para medir; el mensaje dice por qué."""


@dataclass
class Side:
    inside: np.ndarray  # RGB lineal medio
    outside: np.ndarray
    delta_e: float

    @property
    def ratio(self) -> np.ndarray:
        return self.outside / self.inside


def find_screen(rgb_linear: np.ndarray) -> np.ndarray:
    """Esquinas del interior de la pantalla encendida: el hueco claro dentro del canto negro."""
    height, width = rgb_linear.shape[:2]
    scale = min(1.0, 1200.0 / width)
    small = cv2.resize(
        luminance(rgb_linear), None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
    )
    dark = (small < 0.3 * np.median(small)).astype(np.uint8)
    contours, hierarchy = cv2.findContours(dark, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        raise MeasureError("no se encuentra el canto negro de la tele")
    holes = [c for c, h in zip(contours, hierarchy[0], strict=True) if h[3] >= 0]
    if not holes:
        raise MeasureError("no se encuentra la pantalla dentro del canto negro")
    hull = cv2.convexHull(max(holes, key=cv2.contourArea))
    if cv2.contourArea(hull) < MIN_AREA_FRACTION * small.size:
        raise MeasureError("la pantalla ocupa menos del 5 % de la foto: acércate o encuadra mejor")
    perimeter = cv2.arcLength(hull, True)
    for epsilon in np.linspace(0.005, 0.1, 40):
        approx = cv2.approxPolyDP(hull, epsilon * perimeter, True)
        if len(approx) == 4:
            return order_corners(approx.reshape(4, 2) / scale)
    raise MeasureError("el contorno de la pantalla no es un cuadrilátero")


def _profile(image: np.ndarray, side: str, margin: int, w: int, h: int):
    """Perfil medio perpendicular al lado, del exterior (índice 0) hacia el interior."""
    if side == "top":
        band = image[:, margin + int(0.2 * w) : margin + int(0.8 * w)]
        return band[: margin + h // 2].mean(axis=1), margin
    if side == "left":
        band = image[margin + int(0.2 * h) : margin + int(0.8 * h), :]
        return band[:, : margin + w // 2].mean(axis=0), margin
    band = image[margin + int(0.2 * h) : margin + int(0.8 * h), :]
    return band[:, margin + w // 2 :][:, ::-1].mean(axis=0), margin


def measure(rgb_linear: np.ndarray, saturation: float) -> dict[str, Side]:
    corners = find_screen(rgb_linear)
    rect = rectify(corners, MEASURE_WIDTH, REFERENCE[1] + 0.01)
    w, h, m = rect.width, rect.height, rect.margin
    channels = np.stack([warp(rgb_linear[..., c], rect, np.nan) for c in range(3)], axis=-1)
    y = luminance(channels)
    px = lambda fraction: max(1, int(round(fraction * w)))  # noqa: E731

    sides: dict[str, Side] = {}
    for side in SIDES:
        profile, edge = _profile(y, side, m, w, h)
        rgb_profile = np.stack(
            [_profile(channels[..., c], side, m, w, h)[0] for c in range(3)], axis=-1
        )
        if np.isnan(profile[edge - px(REFERENCE[1]) :]).any():
            raise MeasureError(f"el lado {side} se sale de la foto: encuadra con más margen")
        # El canto se compara con la pared que tiene justo al lado: más lejos puede haber otra
        # cosa (en el salón, el frente claro del mueble colgado a unos 5 % sobre la tele).
        outward = profile[edge - px(SEARCH) : edge][::-1]  # desde el borde hacia fuera
        low = int(np.argmin(outward[: px(BEZEL_MAX)]))
        floor = outward[low]
        wall = np.median(outward[low + px(NEAR_WALL[0]) : low + px(NEAR_WALL[1])])
        bright = np.nonzero(outward[low:] >= floor + 0.8 * (wall - floor))[0]
        if wall <= 2 * floor or bright.size == 0:
            raise MeasureError(f"en el lado {side} no se ve dónde acaba el canto negro")
        bezel_end = low + int(bright[0])
        out_from = edge - bezel_end - px(0.003) - px(OUTSIDE)
        out_to = edge - bezel_end - px(0.003)
        inside = rgb_profile[edge + px(INSIDE[0]) : edge + px(INSIDE[1])].mean(axis=0)
        outside = rgb_profile[out_from:out_to].mean(axis=0)
        for name, values in (("dentro", inside), ("fuera", outside)):
            if values.max() >= saturation:
                raise MeasureError(f"franja {name} del lado {side} quemada: baja la exposición")
            if values.min() <= 0:
                raise MeasureError(f"franja {name} del lado {side} sin luz")
        sides[side] = Side(inside=inside, outside=outside, delta_e=0.0)

    scale = WALL_Y / np.mean([luminance(s.outside) for s in sides.values()])
    for s in sides.values():
        s.delta_e = delta_e(s.inside * scale, s.outside * scale)
    return sides
