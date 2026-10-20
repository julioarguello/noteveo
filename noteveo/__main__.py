"""python -m noteveo <orden> (specs/001-imagen-fija/contracts/cli.md)."""

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from noteveo import (
    CONFIG_FILE,
    MEASUREMENTS_FILE,
    OUTPUT_DIR,
    ROOT,
    encode,
    geometry,
    params,
    photo,
    tv,
    wall,
)
from noteveo.correct import corrected
from noteveo.measure import SIDES, MeasureError, measure

OK, USAGE, REJECTED = 0, 1, 2
RENDER_INFO = OUTPUT_DIR / "render.json"
TV_STATE = OUTPUT_DIR / "tv-state.json"
COLUMNS = [
    "taken_at", "photo", "params_sha", "de_top", "de_left", "de_right",
    "ratio_top", "ratio_left", "ratio_right", "exposure", "iso",
    "apl", "tv_settings", "reflections",
]  # fmt: skip


def _input_photo(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    if path.parent.resolve() != (ROOT / "entrada").resolve():
        raise params.ParamsError(f"la foto tiene que estar en entrada/: {value}")
    return path


def cmd_locate(args) -> int:
    path = _input_photo(args.photo)
    rgb = photo.load_linear(path)
    corners = geometry.find_dark_quad(rgb)
    if corners is None:
        print(
            "No encuentro un cuadrilátero oscuro que ocupe al menos el 5 % de la foto.",
            file=sys.stderr,
        )
        return USAGE
    current = params.load(CONFIG_FILE)
    current.reference_photo = path.name
    current.corners = np.round(corners, 1).tolist()
    params.save(current, CONFIG_FILE)
    preview = OUTPUT_DIR / "locate.png"
    preview.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(preview), geometry.draw_outline(rgb, corners, current.masks.values()))
    print("Esquinas de la pantalla (arriba-izq., arriba-der., abajo-der., abajo-izq.):")
    for x, y in current.corners:
        print(f"  ({x:.1f}, {y:.1f})")
    print(f"Escritas en {CONFIG_FILE.relative_to(ROOT)}. Vista previa: {preview.relative_to(ROOT)}")
    return OK


def cmd_render(args) -> int:
    current = params.load(CONFIG_FILE)
    reference = ROOT / "entrada" / current.reference_photo
    reference_rgb = photo.load_linear(reference)
    light = wall.estimate_light(reference_rgb, current)
    linear = wall.render_linear(light, current)
    codes = encode.to_codes(linear)
    step = encode.max_neighbor_step(codes)
    quantized = encode.quantize(codes)
    png, clip = OUTPUT_DIR / "wall.png", OUTPUT_DIR / "wall.mp4"
    encode.write_png(quantized, png)
    level = encode.apl(quantized)
    names = {"top": "arriba", "bottom": "abajo", "left": "izquierda", "right": "derecha"}
    print(f"Anillo de pared: {light.ring_pixels} píxeles. Pared medida por lado:")
    for side, coverage in light.coverage.items():
        edge = light.edges.get(side)
        state = f"luz media {edge:.3f}" if edge is not None else "libre (sin pared que medir)"
        print(f"  {names[side]:>9}: {coverage:4.0%} del lado, {state}")
    print(f"APL: {level:.1f} %")
    if current.apl_max is not None and level > current.apl_max:
        print(f"  supera oled.apl_max = {current.apl_max} %", file=sys.stderr)
    print(f"Mayor salto entre píxeles vecinos: {step:.3f} niveles de 10 bits")
    if step > 1.0:
        print("Hay un borde de más de un nivel (SC-005): no se genera el clip.", file=sys.stderr)
        return USAGE
    preview = OUTPUT_DIR / "preview.jpg"
    cv2.imwrite(str(preview), wall.preview_in_photo(reference_rgb, light, current))
    print(f"Vista previa en la foto: {preview.relative_to(ROOT)}")
    if not args.no_clip:
        encode.encode_clip(png, clip, current.seconds)
    info = {
        "params_sha": params.digest(CONFIG_FILE),
        "png_sha256": encode.sha256(png),
        "mp4_sha256": encode.sha256(clip) if clip.exists() and not args.no_clip else None,
        "apl": round(level, 2),
        "max_step": round(step, 4),
    }
    RENDER_INFO.write_text(json.dumps(info, indent=2) + "\n")
    print(f"wall.png  {info['png_sha256']}")
    if info["mp4_sha256"]:
        print(f"wall.mp4  {info['mp4_sha256']}  (la huella del clip no tiene por qué repetirse)")
    return OK


def cmd_push(args) -> int:
    current = params.load(CONFIG_FILE)
    device = args.device or current.tv_device
    clip = OUTPUT_DIR / "wall.mp4"
    if not clip.exists():
        print("No hay salida/wall.mp4: ejecuta antes «render».", file=sys.stderr)
        return USAGE
    try:
        previous = tv.push(device, clip, args.minutes, args.start, TV_STATE)
    except tv.TvError as exc:
        print(str(exc), file=sys.stderr)
        return REJECTED
    print(f"Clip copiado a {device}:{tv.FOLDER}/{tv.CLIP_NAME}.")
    if previous:
        print(f"Apartado mientras dura la prueba: {', '.join(previous)}")
    print(f"Se quita solo a los {args.minutes} minutos, o antes con «remove».")
    if args.start:
        print("Salvapantallas arrancado.")
    return OK


def cmd_remove(args) -> int:
    current = params.load(CONFIG_FILE)
    device = args.device or current.tv_device
    try:
        tv.remove(device, TV_STATE)
    except tv.TvError as exc:
        print(str(exc), file=sys.stderr)
        return REJECTED
    print("Prueba quitada; la carpeta de la tele vuelve a como estaba.")
    return OK


def _last_row() -> dict | None:
    if not MEASUREMENTS_FILE.exists():
        return None
    with MEASUREMENTS_FILE.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return rows[-1] if rows else None


def cmd_measure(args) -> int:
    path = _input_photo(args.photo)
    exif = photo.read_exif(path)
    last = _last_row()
    if (
        last
        and not args.new_exposure
        and (last["exposure"], last["iso"]) != (exif.exposure, exif.iso)
    ):
        print(
            "Exposición distinta a la de la medida anterior "
            f"({last['exposure']} s, ISO {last['iso']} "
            f"→ {exif.exposure} s, ISO {exif.iso}). Si es a propósito, repite con --new-exposure.",
            file=sys.stderr,
        )
        return REJECTED
    try:
        sides = measure(photo.load_linear(path), photo.saturation_level(path))
    except MeasureError as exc:
        print(f"Foto rechazada: {exc}", file=sys.stderr)
        return REJECTED
    if not RENDER_INFO.exists():
        print("No hay salida/render.json: ¿qué imagen había en la tele?", file=sys.stderr)
        return USAGE
    info = json.loads(RENDER_INFO.read_text())
    names = {"top": "arriba", "left": "izquierda", "right": "derecha"}
    for side in SIDES:
        s = sides[side]
        ratio = " / ".join(f"{r:.3f}" for r in s.ratio)
        print(f"{names[side]:>9}: ΔE2000 {s.delta_e:5.2f}   fuera/dentro R/G/B {ratio}")
    row = {
        "taken_at": exif.taken_at or datetime.now().astimezone().isoformat(timespec="seconds"),
        "photo": path.name,
        "params_sha": info["params_sha"],
        **{f"de_{side}": f"{sides[side].delta_e:.2f}" for side in SIDES},
        **{f"ratio_{side}": "/".join(f"{r:.4f}" for r in sides[side].ratio) for side in SIDES},
        "exposure": exif.exposure,
        "iso": exif.iso,
        "apl": info["apl"],
        "tv_settings": args.tv_settings,
        "reflections": args.reflections,
    }
    MEASUREMENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    new_file = not MEASUREMENTS_FILE.exists()
    with MEASUREMENTS_FILE.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)
    worst = max(sides[side].delta_e for side in SIDES)
    print(f"Peor lado: ΔE2000 {worst:.2f} ({'cumple' if worst <= 3 else 'no cumple'} SC-001: ≤ 3)")
    return OK


def cmd_correct(args) -> int:
    current = params.load(CONFIG_FILE)
    last = _last_row()
    if last is None:
        print(
            "No hay medidas en calibracion/medidas.csv: ejecuta antes «measure».", file=sys.stderr
        )
        return USAGE
    if last["params_sha"] != params.digest(CONFIG_FILE):
        print(
            "La última medida se hizo con otros parámetros: genera, pon y mide de nuevo.",
            file=sys.stderr,
        )
        return USAGE
    ratios = {s: np.array([float(x) for x in last[f"ratio_{s}"].split("/")]) for s in SIDES}
    gain, gain_x, gain_y = corrected(current, ratios)

    def fmt(values):
        return "[" + ", ".join(f"{v:.4f}" for v in values) + "]"

    print(f"gain:   {fmt(current.gain)} → {fmt(gain)}")
    print(f"gain_x: {fmt(current.gain_x)} → {fmt(gain_x)}")
    print(f"gain_y: {fmt(current.gain_y)} → {fmt(gain_y)}")
    if not args.apply:
        print("Sin cambios en config/wall.toml. Para aplicarlo: correct --apply")
        return OK
    current.gain, current.gain_x, current.gain_y = gain, gain_x, gain_y
    params.save(current, CONFIG_FILE)
    print("Aplicado en config/wall.toml. Siguiente: render y push.")
    return OK


class _Parser(argparse.ArgumentParser):
    """Un error de uso sale con 1, como dice el contrato (argparse usa 2)."""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        self.exit(USAGE, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="noteveo", description="La pared de detrás, en la tele.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("locate", help="esquinas de la pantalla en la foto de referencia")
    p.add_argument("--photo", required=True, help="foto de entrada/ con la tele apagada")
    p.set_defaults(func=cmd_locate)

    p = sub.add_parser("render", help="genera salida/wall.png y salida/wall.mp4")
    p.add_argument("--no-clip", action="store_true", help="solo el PNG, sin codificar el vídeo")
    p.set_defaults(func=cmd_render)

    for name, func, text in (
        ("push", cmd_push, "copia el clip a la tele"),
        ("remove", cmd_remove, "quita el clip de la tele"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("--device", help="ip:puerto de la tele (por defecto, tv.device)")
        if name == "push":
            p.add_argument("--minutes", type=int, default=30, help="retirada automática")
            p.add_argument("--start", action="store_true", help="arranca ya el salvapantallas")
        p.set_defaults(func=func)

    p = sub.add_parser("measure", help="mide una foto de calibración")
    p.add_argument("--photo", required=True)
    p.add_argument("--tv-settings", required=True, help="modo de imagen, temperatura, sensor")
    p.add_argument("--reflections", required=True, choices=["yes", "no"])
    p.add_argument("--new-exposure", action="store_true", help="la exposición cambió a propósito")
    p.set_defaults(func=cmd_measure)

    p = sub.add_parser("correct", help="corrige la ganancia con la última medida")
    p.add_argument("--apply", action="store_true", help="escribe config/wall.toml")
    p.set_defaults(func=cmd_correct)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (params.ParamsError, photo.PhotoError, wall.WallError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return USAGE


if __name__ == "__main__":
    sys.exit(main())
