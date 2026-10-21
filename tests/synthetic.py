"""Escenas sintéticas para los tests; los casos reales están en tests/fixtures/salon/."""

import cv2
import numpy as np

# Una tele vista algo en perspectiva, esquinas en el orden de geometry.order_corners.
CORNERS = np.array([[420.0, 300.0], [1180.0, 310.0], [1175.0, 735.0], [425.0, 728.0]])
SIZE = (1600, 1200)  # ancho, alto


def wall_gradient(size=SIZE) -> np.ndarray:
    """Pared en luz lineal con un degradado suave de izquierda a derecha y de arriba abajo."""
    width, height = size
    x = np.linspace(0, 1, width)
    y = np.linspace(0, 1, height)
    xx, yy = np.meshgrid(x, y)
    light = 0.55 + 0.25 * xx - 0.08 * yy
    return np.repeat(light[..., None], 3, axis=2)


def fill_quad(image: np.ndarray, corners: np.ndarray, rgb) -> None:
    cv2.fillPoly(image, [np.round(corners).astype(np.int32)], tuple(float(c) for c in rgb))


def room_with_tv_off(corners=CORNERS, size=SIZE) -> np.ndarray:
    image = wall_gradient(size)
    fill_quad(image, corners, (0.01, 0.01, 0.012))
    return image


def scale_quad(corners: np.ndarray, factor: float) -> np.ndarray:
    center = corners.mean(axis=0)
    return center + (corners - center) * factor


def calibration_scene(inside_rgb, outside_rgb, corners=CORNERS, size=SIZE) -> np.ndarray:
    """Pared uniforme, canto negro, pantalla encendida y un mueble oscuro pegado por debajo."""
    width, height = size
    image = np.ones((height, width, 3)) * np.asarray(outside_rgb, dtype=np.float64)
    bottom = corners[2:].mean(axis=0)[1]
    image[int(bottom) : int(bottom) + 120, 300:1300] = (0.05, 0.03, 0.02)
    fill_quad(image, scale_quad(corners, 1.03), (0.01, 0.01, 0.01))  # canto negro
    fill_quad(image, corners, inside_rgb)
    return image
