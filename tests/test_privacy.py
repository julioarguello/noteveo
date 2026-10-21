"""Constitución V: de la casa solo se publican las fotos reducidas y sin metadatos de los tests."""

import subprocess
from pathlib import Path

import exifread
import pytest

from noteveo import ROOT

MEDIA = {".jpg", ".jpeg", ".png", ".heic", ".dng", ".webp", ".gif", ".tif", ".tiff",
         ".mp4", ".mov", ".mkv", ".webm"}  # fmt: skip
ALLOWED_DIR = "tests/fixtures/salon/"


def media_files(paths: list[str]) -> list[str]:
    return [p for p in paths if any(p.lower().endswith(ext) for ext in MEDIA)]


def exif_tags(path: Path) -> int:
    with path.open("rb") as fh:
        return len(exifread.process_file(fh, details=False))


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    files = out.stdout.splitlines()
    assert len(files) > 20, "git ls-files devolvió casi nada: el test no estaría mirando"
    return files


def test_control_detects_an_image():
    assert media_files(["README.md", "salida/a.PNG", "x/clip.mp4"]) == [
        "salida/a.PNG",
        "x/clip.mp4",
    ]


def test_control_detects_exif():
    """El original, con GPS, tiene que dar etiquetas; si no, el test de abajo no prueba nada."""
    original = ROOT / "entrada" / "PXL_20261020_130130671.jpg"
    if not original.exists():
        pytest.skip("sin el original en entrada/ (fuera de git) no hay control")
    assert exif_tags(original) > 0


def test_media_only_in_the_fixtures_folder():
    outside = [p for p in media_files(tracked()) if not p.startswith(ALLOWED_DIR)]
    assert outside == []


def test_published_photos_carry_no_metadata():
    photos = [p for p in media_files(tracked()) if p.startswith(ALLOWED_DIR)]
    assert photos, "no hay fotos publicadas: el test no estaría mirando"
    with_exif = [p for p in photos if exif_tags(ROOT / p) > 0]
    assert with_exif == [], f"fotos con metadatos (pueden llevar el GPS): {with_exif}"
