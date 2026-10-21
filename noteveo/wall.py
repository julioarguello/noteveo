"""La pared que tapa la tele: luz continuada desde la pared de alrededor (research.md R2, R4).

Dentro de la pantalla se resuelve la ecuación de Laplace con los bordes fijados a la pared que
se ve justo fuera de cada lado. Una función armónica no tiene máximos ni mínimos dentro, así que
no puede inventar manchas ni bordes; solo continúa lo que el ojo ve junto al marco.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from noteveo import HEIGHT, WIDTH
from noteveo.color import luminance
from noteveo.geometry import Rectified, polygon_mask, rectify, warp
from noteveo.params import Params

# Resolución del espacio rectificado donde se calcula la luz: basta para un campo suave.
FIT_WIDTH = 480
# Por debajo de esto el anillo no dice nada fiable de la luz.
MIN_RING_PIXELS = 2000
# Un lado con menos pared medida que esto no fija su borde: la luz llega a él libre (Neumann).
MIN_COVERAGE = 0.3
SIDES = ("top", "bottom", "left", "right")
# Fracción de cada lado sobre la que se reparte el ajuste de una esquina (join_corners).
CORNER_BLEND = 0.3
# Jacobi se para cuando ninguna celda cambia más que esto (relativo al nivel medio).
TOLERANCE = 1e-7
MAX_ITERATIONS = 200_000


class WallError(ValueError):
    """La foto no permite estimar la luz de la pared."""


@dataclass
class Light:
    field: np.ndarray  # luminancia dentro de la pantalla, en la escala de la foto (alto × ancho)
    edges: dict[str, float]  # luminancia media de la pared en cada lado fijado
    coverage: dict[str, float]  # fracción de cada lado con pared medida
    ring_pixels: int

    @property
    def relative(self) -> np.ndarray:
        return self.field / self.field.mean()


def ring_mask(rect: Rectified, gap: float, width: float) -> np.ndarray:
    """1 en el anillo entre gap y gap + width (fracciones del ancho de pantalla) fuera del marco."""
    cols, rows = rect.size
    mask = np.zeros((rows, cols), dtype=np.uint8)
    m = rect.margin
    inner = int(round(gap * rect.width))
    outer = int(round((gap + width) * rect.width))
    top, left = max(0, m - outer), max(0, m - outer)
    bottom = min(rows, m + rect.height + outer)
    right = min(cols, m + rect.width + outer)
    mask[top:bottom, left:right] = 1
    mask[m - inner : m + rect.height + inner, m - inner : m + rect.width + inner] = 0
    return mask


def _band_mean(values: np.ndarray, usable: np.ndarray, axis: int):
    """Media por fila o columna de los píxeles utilizables, y cuántos hubo."""
    count = usable.sum(axis=axis)
    total = np.where(usable, values, 0.0).sum(axis=axis)
    mean = np.divide(total, count, out=np.full(count.shape, np.nan), where=count > 0)
    return mean, count > 0


def _smooth_fill(values: np.ndarray, valid: np.ndarray, sigma: float) -> np.ndarray:
    """Suaviza a lo largo del borde y rellena los tramos tapados por una máscara."""
    radius = max(1, int(3 * sigma))
    x = np.arange(-radius, radius + 1)
    kernel = np.exp(-0.5 * (x / sigma) ** 2)
    weight = np.convolve(valid.astype(float), kernel, mode="same")
    total = np.convolve(np.where(valid, values, 0.0), kernel, mode="same")
    known = weight > 0.05 * kernel.sum()
    smooth = np.divide(total, weight, out=np.zeros_like(total), where=known)
    index = np.arange(len(values))
    return np.interp(index, index[known], smooth[known])


def edge_profiles(y: np.ndarray, usable: np.ndarray, rect: Rectified, gap: float, width: float):
    """Perfil de la pared junto a cada lado y qué fracción del lado se pudo medir."""
    m, w, h = rect.margin, rect.width, rect.height
    inner = int(round(gap * w))
    outer = int(round((gap + width) * w))
    bands = {
        "top": (np.s_[m - outer : m - inner, m : m + w], 0),
        "bottom": (np.s_[m + h + inner : m + h + outer, m : m + w], 0),
        "left": (np.s_[m : m + h, m - outer : m - inner], 1),
        "right": (np.s_[m : m + h, m + w + inner : m + w + outer], 1),
    }
    profiles, coverage = {}, {}
    for side, (region, axis) in bands.items():
        mean, valid = _band_mean(y[region], usable[region], axis)
        coverage[side] = float(valid.mean())
        if coverage[side] >= MIN_COVERAGE:
            profiles[side] = mean, valid
    return profiles, coverage


def join_corners(edges: dict[str, np.ndarray], fraction: float) -> dict[str, np.ndarray]:
    """Lleva los dos perfiles que llegan a cada esquina al mismo valor.

    Si arriba y la izquierda no coinciden en su esquina, la membrana da un escalón allí. Cada
    perfil se corrige con una rampa que vale 1 en la esquina y 0 a `fraction` de su longitud.
    """
    out = {side: profile.copy() for side, profile in edges.items()}
    # (lado A, extremo de A, lado B, extremo de B) para cada esquina: 0 = principio, -1 = final.
    corners = [("top", 0, "left", 0), ("top", -1, "right", 0),
               ("bottom", 0, "left", -1), ("bottom", -1, "right", -1)]  # fmt: skip
    for side_a, end_a, side_b, end_b in corners:
        if side_a not in edges or side_b not in edges:
            continue
        target = 0.5 * (edges[side_a][end_a] + edges[side_b][end_b])
        for side, end in ((side_a, end_a), (side_b, end_b)):
            n = len(out[side])
            ramp = np.clip(1 - np.arange(n) / max(1.0, fraction * n), 0, 1)
            if end == -1:
                ramp = ramp[::-1]
            out[side] += (target - edges[side][end]) * ramp
    return out


def _resample(profile: np.ndarray, n: int) -> np.ndarray:
    old = (np.arange(len(profile)) + 0.5) / len(profile)
    new = (np.arange(n) + 0.5) / n
    return np.interp(new, old, profile)


def solve_laplace(height: int, width: int, edges: dict[str, np.ndarray]) -> np.ndarray:
    """Campo armónico con los lados de edges fijados y los demás libres (derivada normal nula).

    Jacobi de grueso a fino: cada nivel parte del anterior ampliado.
    """
    if not edges:
        raise WallError("ningún lado de la pantalla tiene pared medida")
    start = float(np.mean([e.mean() for e in edges.values()]))
    levels = []
    w, h = width, height
    while w >= 30:
        levels.append((h, w))
        w, h = w // 2, max(2, h // 2)
    field = None
    for h, w in reversed(levels):
        grid = np.full((h + 2, w + 2), start)
        if field is not None:
            grid[1:-1, 1:-1] = cv2.resize(field, (w, h), interpolation=cv2.INTER_LINEAR)
        fixed = {
            side: _resample(profile, w if side in ("top", "bottom") else h)
            for side, profile in edges.items()
        }
        for _ in range(MAX_ITERATIONS):
            grid[0, 1:-1] = fixed["top"] if "top" in fixed else grid[1, 1:-1]
            grid[-1, 1:-1] = fixed["bottom"] if "bottom" in fixed else grid[-2, 1:-1]
            grid[1:-1, 0] = fixed["left"] if "left" in fixed else grid[1:-1, 1]
            grid[1:-1, -1] = fixed["right"] if "right" in fixed else grid[1:-1, -2]
            update = 0.25 * (grid[:-2, 1:-1] + grid[2:, 1:-1] + grid[1:-1, :-2] + grid[1:-1, 2:])
            change = np.abs(update - grid[1:-1, 1:-1]).max()
            grid[1:-1, 1:-1] = update
            if change < TOLERANCE * start:
                break
        else:
            raise WallError(f"la luz no converge en {MAX_ITERATIONS} pasadas ({w}×{h})")
        field = grid[1:-1, 1:-1].astype(np.float32)
    return field.astype(np.float64)


def estimate_light(photo_linear: np.ndarray, params: Params) -> Light:
    gap, width = params.ring_gap / 100.0, params.ring_width / 100.0
    rect = rectify(params.corners, FIT_WIDTH, gap + width)
    y = warp(luminance(photo_linear), rect, border=np.nan)
    usable = ring_mask(rect, gap, width) & polygon_mask(y.shape, params.masks.values(), rect)
    usable = usable.astype(bool) & np.isfinite(y)
    if usable.sum() < MIN_RING_PIXELS:
        raise WallError(
            f"solo {int(usable.sum())} píxeles de pared en el anillo (mínimo {MIN_RING_PIXELS}): "
            "revisa screen.corners, ring y masks en config/wall.toml"
        )
    profiles, coverage = edge_profiles(np.nan_to_num(y), usable, rect, gap, width)
    if len(profiles) < 2:
        raise WallError(
            "hace falta pared medida en al menos dos lados; cobertura: "
            + ", ".join(f"{s} {c:.0%}" for s, c in coverage.items())
        )
    sigma = params.light_smoothing / 100.0 * rect.width
    edges = {side: _smooth_fill(mean, valid, sigma) for side, (mean, valid) in profiles.items()}
    edges = join_corners(edges, CORNER_BLEND)
    field = solve_laplace(rect.height, rect.width, edges)
    if field.min() <= 0:
        raise WallError("la luz calculada sale nula o negativa dentro de la pantalla")
    return Light(
        field=field,
        edges={side: float(edge.mean()) for side, edge in edges.items()},
        coverage=coverage,
        ring_pixels=int(usable.sum()),
    )


def gain_field(params: Params, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Ganancia por canal en cada punto: gain · (1 + gain_x·(u − ½) + gain_y·(v − ½))."""
    gain = np.asarray(params.gain)
    gx, gy = np.asarray(params.gain_x), np.asarray(params.gain_y)
    return gain * (1 + gx * (u[..., None] - 0.5) + gy * (v[..., None] - 0.5))


def screen_uv(width: int = WIDTH, height: int = HEIGHT) -> tuple[np.ndarray, np.ndarray]:
    u = (np.arange(width, dtype=np.float32) + 0.5) / width
    v = (np.arange(height, dtype=np.float32) + 0.5) / height
    return np.meshgrid(u, v)


def render_linear(light: Light, params: Params, width: int = WIDTH, height: int = HEIGHT):
    """Fotograma en RGB lineal: nivel × luz relativa × ganancia. Neutro: la pintura no tiñe."""
    relative = cv2.resize(
        light.relative.astype(np.float32), (width, height), interpolation=cv2.INTER_CUBIC
    )
    u, v = screen_uv(width, height)
    frame = params.level * relative[..., None] * gain_field(params, u, v)
    return np.clip(frame, 0.0, 1.0)


def preview_in_photo(photo_linear: np.ndarray, light: Light, params: Params) -> np.ndarray:
    """La foto con la luz calculada pegada en la pantalla, en sRGB de 8 bits (BGR).

    Solo para mirar la forma de la luz: va en la escala de la foto, sin nivel ni ganancia.
    """
    height, width = photo_linear.shape[:2]
    h, w = light.field.shape
    corners = np.asarray(params.corners, dtype=np.float32)
    src = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype=np.float32)
    homography = cv2.getPerspectiveTransform(src, corners)
    gray = cv2.warpPerspective(light.field.astype(np.float32), homography, (width, height))
    inside = cv2.warpPerspective(np.ones((h, w), np.float32), homography, (width, height))
    out = np.where(inside[..., None] > 0.5, gray[..., None], photo_linear)
    return (np.clip(out, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)[..., ::-1]
