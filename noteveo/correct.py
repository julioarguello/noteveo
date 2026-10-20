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


def corrected(
    params: Params, ratios: dict[str, np.ndarray], sides: list[str] | None = None
) -> tuple[list, list, list]:
    """Ganancia, gain_x y gain_y que llevan cada lado a su objetivo (ganancia actual × cociente).

    Solo cuentan los lados de `sides`: los que la imagen fija a la pared de detrás. Sin izquierda y
    derecha a la vez no hay con qué medir la variación horizontal, y gain_x queda en 0; sin arriba,
    lo mismo con gain_y.
    """
    sides = [s for s in (sides or list(POSITIONS)) if s in POSITIONS]
    if not sides:
        raise ValueError("ningún lado medible para corregir")
    use_x = "left" in sides and "right" in sides
    use_y = "top" in sides and len(sides) > 1
    targets = np.array([gain_at(params, *POSITIONS[s]) * ratios[s] for s in sides])
    columns = [np.ones(len(sides))]
    if use_x:
        columns.append(np.array([POSITIONS[s][0] - 0.5 for s in sides]))
    if use_y:
        columns.append(np.array([POSITIONS[s][1] - 0.5 for s in sides]))
    system = np.column_stack(columns)
    solution, *_ = np.linalg.lstsq(system, targets, rcond=None)  # filas: a, (b), (c)
    a = solution[0]
    b = solution[1] if use_x else np.zeros(3)
    c = solution[-1] if use_y else np.zeros(3)
    if (a <= 0).any():
        raise ValueError("la corrección da una ganancia no positiva: la medida no es coherente")
    return a.tolist(), (b / a).tolist(), (c / a).tolist()
