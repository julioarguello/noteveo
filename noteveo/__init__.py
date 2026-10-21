"""noteveo: que la tele del salón muestre la pared que tiene detrás."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT / "entrada"
OUTPUT_DIR = ROOT / "salida"
CONFIG_FILE = ROOT / "config" / "wall.toml"
MEASUREMENTS_FILE = ROOT / "calibracion" / "medidas.csv"

# Resolución del panel de la KD-65A8 (docs/medidas-tele.md).
WIDTH, HEIGHT = 3840, 2160
