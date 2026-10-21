"""Dónde está la pantalla en una foto y cómo se pasa de la foto a la pantalla (research.md R3)."""

from dataclasses import dataclass

import cv2
import numpy as np

from noteveo.color import luminance

# La pantalla tiene que ocupar al menos esta fracción de la foto (contracts/cli.md, locate).
MIN_AREA_FRACTION = 0.05


def order_corners(points: np.ndarray) -> np.ndarray:
    """Arriba-izquierda, arriba-derecha, abajo-derecha, abajo-izquierda."""
    pts = np.asarray(points, dtype=np.float64).reshape(4, 2)
    total = pts.sum(axis=1)
    diff = pts[:, 0] - pts[:, 1]
    return np.array(
        [pts[total.argmin()], pts[diff.argmax()], pts[total.argmax()], pts[diff.argmin()]]
    )


def find_dark_quad(rgb_linear: np.ndarray) -> np.ndarray | None:
    """Esquinas del cuadrilátero oscuro más grande (la tele apagada), o None si no hay."""
    height, width = rgb_linear.shape[:2]
    scale = min(1.0, 1200.0 / width)
    small = cv2.resize(
        rgb_linear.astype(np.float32), None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
    )
    # Canal más brillante, no luminancia: la madera del mueble es oscura pero roja, y la pantalla
    # apagada es oscura en los tres canales (medido en la foto de referencia el 2026-10-20:
    # pantalla 0,03; madera de 0,09 a 0,11; mediana de la foto 0,27).
    dark = (small.max(axis=2) < 0.15 * np.median(luminance(small))).astype(np.uint8)
    size = max(3, int(small.shape[1] * 0.01) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, kernel)
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, kernel)
    contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    hull = cv2.convexHull(contour)
    if cv2.contourArea(hull) < MIN_AREA_FRACTION * small.shape[0] * small.shape[1]:
        return None
    rough = order_corners(cv2.boxPoints(cv2.minAreaRect(hull)))
    corners = fit_edges(contour.reshape(-1, 2).astype(np.float64), rough)
    return None if corners is None else corners / scale


def _fit_line(points: np.ndarray, tolerance: float) -> tuple[np.ndarray, np.ndarray] | None:
    """Recta por mínimos cuadrados que descarta, en tres pasadas, los puntos que se alejan."""
    keep = np.ones(len(points), dtype=bool)
    for _ in range(3):
        if keep.sum() < 10:
            return None
        center = points[keep].mean(axis=0)
        _, _, vt = np.linalg.svd(points[keep] - center)
        direction = vt[0]
        normal = np.array([-direction[1], direction[0]])
        keep = np.abs((points - center) @ normal) <= tolerance
    return center, direction


def _intersect(a, b) -> np.ndarray:
    (p, d), (q, e) = a, b
    t = np.linalg.solve(np.column_stack([d, -e]), q - p)[0]
    return p + t * d


def fit_edges(points: np.ndarray, rough: np.ndarray) -> np.ndarray | None:
    """Esquinas como cruce de las rectas de cada lado.

    Un reflejo claro en una esquina de la pantalla muerde el contorno oscuro; los puntos del
    mordisco se descartan al ajustar cada lado, y la esquina sale del cruce de los dos lados.
    """
    lines = []
    for i in range(4):
        a, b = rough[i], rough[(i + 1) % 4]
        length = np.linalg.norm(b - a)
        direction = (b - a) / length
        normal = np.array([-direction[1], direction[0]])
        along = (points - a) @ direction
        across = np.abs((points - a) @ normal)
        near = (across <= 0.04 * length) & (along >= 0.1 * length) & (along <= 0.9 * length)
        line = _fit_line(points[near], tolerance=max(1.5, 0.004 * length))
        if line is None:
            return None
        lines.append(line)
    return order_corners(np.array([_intersect(lines[i - 1], lines[i]) for i in range(4)]))


@dataclass
class Rectified:
    """Espacio rectificado: la pantalla ocupa [m, m + width] × [m, m + height], con m = margin."""

    homography: np.ndarray
    width: int
    height: int
    margin: int

    @property
    def size(self) -> tuple[int, int]:
        return (self.width + 2 * self.margin, self.height + 2 * self.margin)

    def uv(self) -> tuple[np.ndarray, np.ndarray]:
        """Coordenadas normalizadas de cada píxel: 0 a 1 dentro de la pantalla."""
        cols, rows = self.size
        x = (np.arange(cols) + 0.5 - self.margin) / self.width
        y = (np.arange(rows) + 0.5 - self.margin) / self.height
        return np.meshgrid(x, y)


def rectify(corners, screen_width: int, margin_fraction: float) -> Rectified:
    """Homografía de la foto a un espacio donde la pantalla mide screen_width × 9/16 de alto."""
    width = screen_width
    height = round(screen_width * 9 / 16)
    margin = int(np.ceil(margin_fraction * width))
    dst = np.array(
        [
            [margin, margin],
            [margin + width, margin],
            [margin + width, margin + height],
            [margin, margin + height],
        ],
        dtype=np.float32,
    )
    homography = cv2.getPerspectiveTransform(np.asarray(corners, dtype=np.float32), dst)
    return Rectified(homography, width, height, margin)


def warp(image: np.ndarray, rect: Rectified, border: float = 0.0) -> np.ndarray:
    return cv2.warpPerspective(
        image.astype(np.float32),
        rect.homography,
        rect.size,
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=border,
    )


def polygon_mask(shape: tuple[int, int], polygons, rect: Rectified) -> np.ndarray:
    """1 donde hay pared utilizable, 0 dentro de los polígonos (dados en coordenadas de la foto)."""
    mask = np.ones(shape, dtype=np.uint8)
    for points in polygons:
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 1, 2)
        warped = cv2.perspectiveTransform(pts, rect.homography)
        cv2.fillPoly(mask, [np.round(warped).astype(np.int32)], 0)
    return mask


def draw_outline(rgb_linear: np.ndarray, corners, masks) -> np.ndarray:
    """Vista previa en sRGB de 8 bits con la pantalla y las máscaras dibujadas."""
    preview = (np.clip(rgb_linear, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)[..., ::-1].copy()
    thickness = max(2, preview.shape[1] // 400)
    pts = np.round(np.asarray(corners)).astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(preview, [pts], True, (0, 0, 255), thickness)
    for points in masks:
        poly = np.round(np.asarray(points)).astype(np.int32).reshape(-1, 1, 2)
        cv2.polylines(preview, [poly], True, (255, 160, 0), thickness)
    return preview
