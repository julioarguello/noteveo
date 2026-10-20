"""Conversiones de color: sRGB, luz lineal, Lab y ΔE2000.

ΔE2000 sigue a Sharma, Wu y Dalal, «The CIEDE2000 color-difference formula» (Color Research &
Application 30, 2005); tests/test_color.py lo comprueba con los pares de su tabla 1.
"""

import numpy as np

# sRGB/BT.709 a XYZ, blanco D65 (IEC 61966-2-1).
_RGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ]
)
_WHITE_D65 = _RGB_TO_XYZ.sum(axis=1)


def srgb_to_linear(values: np.ndarray) -> np.ndarray:
    """Valores sRGB en [0, 1] a luz lineal."""
    v = np.clip(values, 0.0, 1.0)
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def luminance(rgb: np.ndarray) -> np.ndarray:
    """Luminancia relativa Y de RGB lineal con primarios sRGB/BT.709."""
    return rgb[..., 0] * 0.2126729 + rgb[..., 1] * 0.7151522 + rgb[..., 2] * 0.0721750


def xyz_to_lab(xyz: np.ndarray, white: np.ndarray = _WHITE_D65) -> np.ndarray:
    t = np.asarray(xyz, dtype=np.float64) / white
    delta = 6 / 29
    f = np.where(t > delta**3, np.cbrt(t), t / (3 * delta**2) + 4 / 29)
    return np.stack(
        [116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])],
        axis=-1,
    )


def linear_to_lab(rgb: np.ndarray) -> np.ndarray:
    """RGB lineal con primarios sRGB a CIE Lab (D65)."""
    return xyz_to_lab(np.asarray(rgb, dtype=np.float64) @ _RGB_TO_XYZ.T)


def delta_e2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """ΔE2000 entre colores Lab (kL = kC = kH = 1)."""
    l1, a1, b1 = np.moveaxis(np.asarray(lab1, dtype=np.float64), -1, 0)
    l2, a2, b2 = np.moveaxis(np.asarray(lab2, dtype=np.float64), -1, 0)
    c_mean = (np.hypot(a1, b1) + np.hypot(a2, b2)) / 2
    g = 0.5 * (1 - np.sqrt(c_mean**7 / (c_mean**7 + 25.0**7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    h1p = np.where(c1p == 0, 0.0, h1p)
    h2p = np.where(c2p == 0, 0.0, h2p)

    dl = l2 - l1
    dc = c2p - c1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(c1p * c2p == 0, 0.0, dh)
    dhh = 2 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh / 2))

    l_mean = (l1 + l2) / 2
    cp_mean = (c1p + c2p) / 2
    h_sum = h1p + h2p
    h_mean = np.where(
        np.abs(h1p - h2p) > 180,
        np.where(h_sum < 360, (h_sum + 360) / 2, (h_sum - 360) / 2),
        h_sum / 2,
    )
    h_mean = np.where(c1p * c2p == 0, h_sum, h_mean)
    t = (
        1
        - 0.17 * np.cos(np.radians(h_mean - 30))
        + 0.24 * np.cos(np.radians(2 * h_mean))
        + 0.32 * np.cos(np.radians(3 * h_mean + 6))
        - 0.20 * np.cos(np.radians(4 * h_mean - 63))
    )
    sl = 1 + 0.015 * (l_mean - 50) ** 2 / np.sqrt(20 + (l_mean - 50) ** 2)
    sc = 1 + 0.045 * cp_mean
    sh = 1 + 0.015 * cp_mean * t
    rt = (
        -2
        * np.sqrt(cp_mean**7 / (cp_mean**7 + 25.0**7))
        * np.sin(np.radians(60 * np.exp(-(((h_mean - 275) / 25) ** 2))))
    )
    return np.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dhh / sh) ** 2 + rt * (dc / sc) * (dhh / sh))


def delta_e(rgb_a: np.ndarray, rgb_b: np.ndarray) -> float:
    """ΔE2000 entre dos colores en RGB lineal."""
    return float(delta_e2000(linear_to_lab(rgb_a), linear_to_lab(rgb_b)))
