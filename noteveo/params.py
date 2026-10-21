"""Parámetros de la imagen: config/wall.toml (data-model.md)."""

import hashlib
import math
import tomllib
from dataclasses import dataclass
from pathlib import Path

import numpy as np


class ParamsError(ValueError):
    """Un parámetro falta o no es válido."""


@dataclass
class Params:
    reference_photo: str
    corners: list[list[float]]
    masks: dict[str, list[list[float]]]
    ring_width: float
    ring_gap: float
    light_smoothing: float
    level: float
    gain: list[float]
    gain_x: list[float]
    gain_y: list[float]
    seconds: int
    tv_device: str
    apl_max: float | None = None


def _require(table: dict, key: str, where: str):
    if key not in table:
        raise ParamsError(f"falta «{where}.{key}» en config/wall.toml")
    return table[key]


def _number(value, name: str, low: float | None = None, high: float | None = None) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool) or math.isnan(value):
        raise ParamsError(f"«{name}» tiene que ser un número; vale {value!r}")
    if (low is not None and value < low) or (high is not None and value > high):
        raise ParamsError(f"«{name}» vale {value}; admitido: de {low} a {high}")
    return float(value)


def _positive(value, name: str, high: float) -> float:
    number = _number(value, name, 0.0, high)
    if number == 0:
        raise ParamsError(f"«{name}» tiene que ser mayor que 0")
    return number


def _triple(value, name: str, positive: bool) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ParamsError(f"«{name}» tiene que ser una lista de tres números (R, G, B)")
    out = [_number(v, name) for v in value]
    if positive and min(out) <= 0:
        raise ParamsError(f"«{name}» tiene que ser positivo en los tres canales; vale {out}")
    return out


def _polygon(value, name: str, minimum: int) -> list[list[float]]:
    if not isinstance(value, list) or len(value) < minimum:
        raise ParamsError(f"«{name}» necesita {minimum} puntos o más")
    points = []
    for point in value:
        if not isinstance(point, list) or len(point) != 2:
            raise ParamsError(f"«{name}»: cada punto es [x, y]; encontrado {point!r}")
        points.append([_number(point[0], name), _number(point[1], name)])
    return points


def _check_convex(corners: list[list[float]]) -> None:
    pts = np.asarray(corners)
    signs = []
    for i in range(4):
        a, b, c = pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4]
        signs.append(np.sign((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])))
    if len(set(signs)) != 1 or signs[0] == 0:
        raise ParamsError(
            "«screen.corners» no es un cuadrilátero convexo en el orden "
            "arriba-izquierda, arriba-derecha, abajo-derecha, abajo-izquierda"
        )


def parse(data: dict) -> Params:
    """Valida el contenido de wall.toml ya leído."""
    reference = _require(data, "reference", "")
    screen = _require(data, "screen", "")
    ring = _require(data, "ring", "")
    light = _require(data, "light", "")
    color = _require(data, "color", "")
    output = _require(data, "output", "")
    tv = _require(data, "tv", "")
    oled = data.get("oled", {})

    photo = _require(reference, "photo", "reference")
    if not isinstance(photo, str) or not photo or Path(photo).is_absolute() or "/" in photo:
        raise ParamsError("«reference.photo» es el nombre de un fichero de entrada/, sin ruta")

    corners = _polygon(_require(screen, "corners", "screen"), "screen.corners", 4)
    if len(corners) != 4:
        raise ParamsError("«screen.corners» son exactamente cuatro puntos")
    _check_convex(corners)

    masks = {
        name: _polygon(points, f"masks.{name}", 3) for name, points in data.get("masks", {}).items()
    }

    seconds = _require(output, "seconds", "output")
    if not isinstance(seconds, int) or isinstance(seconds, bool) or seconds < 1:
        raise ParamsError(f"«output.seconds» vale {seconds!r}; admitido: un entero ≥ 1")

    width = _number(_require(ring, "width", "ring"), "ring.width", 0.0)
    if width == 0:
        raise ParamsError("«ring.width» tiene que ser mayor que 0")

    apl_max = oled.get("apl_max")
    if apl_max is not None:
        apl_max = _number(apl_max, "oled.apl_max", 0.0, 100.0)

    device = _require(tv, "device", "tv")
    if not isinstance(device, str) or ":" not in device:
        raise ParamsError(f"«tv.device» es «ip:puerto»; vale {device!r}")

    return Params(
        reference_photo=photo,
        corners=corners,
        masks=masks,
        ring_width=width,
        ring_gap=_number(_require(ring, "gap", "ring"), "ring.gap", 0.0),
        light_smoothing=_positive(_require(light, "smoothing", "light"), "light.smoothing", 20.0),
        level=_positive(_require(color, "level", "color"), "color.level", 1.0),
        gain=_triple(_require(color, "gain", "color"), "color.gain", positive=True),
        gain_x=_triple(_require(color, "gain_x", "color"), "color.gain_x", positive=False),
        gain_y=_triple(_require(color, "gain_y", "color"), "color.gain_y", positive=False),
        seconds=seconds,
        tv_device=device,
        apl_max=apl_max,
    )


def load(path: Path) -> Params:
    if not path.exists():
        raise ParamsError(f"no existe {path}")
    with path.open("rb") as fh:
        try:
            data = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise ParamsError(f"{path} no es TOML válido: {exc}") from exc
    return parse(data)


def _fmt(value: float) -> str:
    return repr(round(float(value), 6))


def _points(points: list[list[float]]) -> str:
    return "[" + ", ".join(f"[{_fmt(x)}, {_fmt(y)}]" for x, y in points) + "]"


def _list(values: list[float]) -> str:
    return "[" + ", ".join(_fmt(v) for v in values) + "]"


def dump(params: Params) -> str:
    """Texto de wall.toml, siempre con la misma forma para que el diff sea legible."""
    lines = [
        "# Parámetros de la imagen de la pared (specs/001-imagen-fija/data-model.md).",
        "# Los escriben las órdenes locate y correct; se pueden ajustar a mano, son texto.",
        "",
        "[reference]",
        f'photo = "{params.reference_photo}"',
        "",
        "[screen]",
        "# Esquinas en la foto: arriba-izquierda, arriba-derecha, abajo-derecha, abajo-izquierda.",
        f"corners = {_points(params.corners)}",
        "",
        "[masks]",
        "# Polígonos en la foto que no son pared.",
    ]
    lines += [f"{name} = {_points(points)}" for name, points in sorted(params.masks.items())]
    lines += [
        "",
        "[ring]",
        "# Anillo de pared alrededor del marco, en % del ancho de la pantalla.",
        f"gap = {_fmt(params.ring_gap)}",
        f"width = {_fmt(params.ring_width)}",
        "",
        "[light]",
        "# Suavizado a lo largo de cada borde, en % del ancho de la pantalla.",
        f"smoothing = {_fmt(params.light_smoothing)}",
        "",
        "[color]",
        "# Nivel lineal medio de la pared en la tele (0 a 1). La pintura, NCS S 0300-N, es neutra:",
        "# no tiñe; el tinte y el nivel los fija la calibración (research.md R2).",
        f"level = {_fmt(params.level)}",
        "# Ganancia lineal por canal (R, G, B) y su variación de izquierda a derecha (x)",
        "# y de arriba abajo (y), relativa al centro.",
        f"gain = {_list(params.gain)}",
        f"gain_x = {_list(params.gain_x)}",
        f"gain_y = {_list(params.gain_y)}",
        "",
        "[output]",
        f"seconds = {params.seconds}",
        "",
        "[tv]",
        f'device = "{params.tv_device}"',
        "",
        "[oled]",
        "# APL máximo admitido; sin valor hasta la primera medida en la tele (FR-010).",
    ]
    if params.apl_max is not None:
        lines.append(f"apl_max = {_fmt(params.apl_max)}")
    return "\n".join(lines) + "\n"


def save(params: Params, path: Path) -> None:
    text = dump(params)
    parse(tomllib.loads(text))  # lo que se escribe tiene que poder leerse
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]
