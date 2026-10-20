"""De la medida a una ganancia nueva: cociente fuera/dentro en luz lineal (research.md R5)."""

import numpy as np

from noteveo.params import Params

# Centro de la franja interior de cada lado, en coordenadas de pantalla (0 a 1).
# La franja interior va del 0,5 % al 2 % del ancho de la pantalla; en vertical, ×16/9.
_STRIP = 0.0125
POSITIONS = {
    "top": (0.5, _STRIP * 16 / 9),
    "left": (_STRIP, 0.5),
    "right": (1 - _STRIP, 0.5),
}


def gain_at(params: Params, u: float, v: float) -> np.ndarray:
    gain = np.asarray(params.gain)
    return gain * (
        1 + np.asarray(params.gain_x) * (u - 0.5) + np.asarray(params.gain_y) * (v - 0.5)
    )


def corrected(params: Params, ratios: dict[str, np.ndarray]) -> tuple[list, list, list]:
    """Ganancia, gain_x y gain_y que llevan cada lado a su objetivo (ganancia actual × cociente)."""
    sides = list(POSITIONS)
    targets = np.array([gain_at(params, *POSITIONS[s]) * ratios[s] for s in sides])
    system = np.array([[1.0, POSITIONS[s][0] - 0.5, POSITIONS[s][1] - 0.5] for s in sides])
    solution = np.linalg.solve(system, targets)  # filas: a, b, c; columnas: R, G, B
    a, b, c = solution
    if (a <= 0).any():
        raise ValueError("la corrección da una ganancia no positiva: la medida no es coherente")
    return a.tolist(), (b / a).tolist(), (c / a).tolist()
