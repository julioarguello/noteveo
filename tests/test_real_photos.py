"""Casos reales: las fotos del salón de tests/fixtures/salon (ver su README)."""

from pathlib import Path

import numpy as np
import pytest

from noteveo import params
from noteveo.encode import max_neighbor_step, to_codes
from noteveo.geometry import find_dark_quad
from noteveo.photo import load_linear
from noteveo.wall import estimate_light, render_linear

FIXTURES = Path(__file__).parent / "fixtures" / "salon"
REFERENCE = "PXL_20261020_130130671.jpg"
WALL = params.load(FIXTURES / "wall.toml")

# Esquinas de la pantalla a 1600 px de ancho (README de las fotos).
CORNERS = {
    REFERENCE: np.array(WALL.corners),
    "PXL_20261020_130152148.jpg": np.array([[360, 342], [1218, 355], [1183, 819], [396, 813]]),
    "PXL_20261020_130138633.jpg": np.array([[608, 425], [1043, 397], [1036, 700], [610, 788]]),
    "PXL_20261020_130201290.jpg": np.array([[535, 457], [1033, 448], [1032, 853], [560, 790]]),
}
OBLIQUE = {
    "PXL_20261020_130138633.jpg": "el reflejo de la ventana muerde la esquina de arriba-izquierda",
    "PXL_20261020_130201290.jpg": "la esquina de abajo a la derecha se une al cajón y a la consola",
}
TOLERANCE_PX = 6


def test_all_four_photos_are_there():
    assert sorted(p.name for p in FIXTURES.glob("*.jpg")) == sorted(CORNERS)


@pytest.mark.parametrize(
    "name",
    [
        pytest.param(n, marks=pytest.mark.xfail(strict=True, reason=OBLIQUE[n]))
        if n in OBLIQUE
        else n
        for n in CORNERS
    ],
)
def test_locate_finds_the_screen(name):
    found = find_dark_quad(load_linear(FIXTURES / name))
    assert found is not None
    assert np.abs(found - CORNERS[name]).max() <= TOLERANCE_PX


def test_reference_light_uses_top_and_left_only():
    light = estimate_light(load_linear(FIXTURES / REFERENCE), WALL)
    assert set(light.edges) == {"top", "left"}
    assert light.coverage["top"] > 0.9 and light.coverage["left"] > 0.9
    # Arriba y a la izquierda la luz es del mismo orden (2026-10-20: 0,40 y 0,38).
    assert light.edges["top"] == pytest.approx(light.edges["left"], rel=0.25)


def test_reference_frame_has_no_edges():
    """SC-005 con la luz real del salón, a 3840×2160."""
    light = estimate_light(load_linear(FIXTURES / REFERENCE), WALL)
    frame = render_linear(light, WALL)
    assert max_neighbor_step(to_codes(frame)) <= 1.0
