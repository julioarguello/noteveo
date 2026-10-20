import numpy as np
import pytest

from noteveo.color import delta_e, luminance
from noteveo.correct import corrected
from noteveo.measure import SIDES, WALL_Y, MeasureError, measure
from tests.synthetic import calibration_scene
from tests.test_wall import make_params

OUTSIDE = np.array([0.50, 0.52, 0.55])
INSIDE = OUTSIDE * np.array([0.90, 1.00, 1.08])


def expected_delta_e() -> float:
    scale = WALL_Y / luminance(OUTSIDE)
    return delta_e(INSIDE * scale, OUTSIDE * scale)


def test_measures_known_offset_on_three_sides():
    sides = measure(calibration_scene(INSIDE, OUTSIDE), saturation=0.97)
    assert set(sides) == set(SIDES)
    expected = expected_delta_e()
    assert expected > 3  # el control tiene que ser un desfase que se note
    for side in SIDES:
        assert sides[side].delta_e == pytest.approx(expected, abs=0.5)
        assert sides[side].ratio == pytest.approx(OUTSIDE / INSIDE, rel=0.02)


def test_matching_screen_gives_near_zero():
    sides = measure(calibration_scene(OUTSIDE, OUTSIDE), saturation=0.97)
    assert max(s.delta_e for s in sides.values()) < 0.5


def test_burnt_strip_is_rejected():
    with pytest.raises(MeasureError, match="quemada"):
        measure(calibration_scene(np.array([0.99, 0.99, 0.99]), OUTSIDE), saturation=0.97)


def test_no_bezel_is_rejected():
    flat = np.ones((1200, 1600, 3)) * OUTSIDE
    with pytest.raises(MeasureError):
        measure(flat, saturation=0.97)


def test_correction_closes_the_gap():
    """Aplicar la corrección y volver a medir deja ΔE ≤ 1 en los tres lados."""
    p = make_params()
    sides = measure(calibration_scene(INSIDE, OUTSIDE), saturation=0.97)
    gain, gain_x, gain_y = corrected(p, {s: sides[s].ratio for s in SIDES})
    # La tele es lineal en la simulación: lo de dentro escala con la ganancia.
    new_inside = INSIDE * np.asarray(gain)
    after = measure(calibration_scene(new_inside, OUTSIDE), saturation=0.97)
    assert max(s.delta_e for s in after.values()) <= 1.0
    assert np.abs(gain_x).max() < 0.05 and np.abs(gain_y).max() < 0.05


def test_free_side_does_not_pull_the_correction():
    """La derecha muy oscura no cuenta si la imagen la deja libre: gain_x se queda en 0."""
    p = make_params()
    ratios = {"top": np.ones(3), "left": np.ones(3), "right": np.full(3, 0.3)}
    gain, gain_x, gain_y = corrected(p, ratios, ["top", "left"])
    assert gain == pytest.approx([1, 1, 1]) and gain_x == pytest.approx([0, 0, 0])
    assert gain_y == pytest.approx([0, 0, 0], abs=1e-9)
    # Control: con los tres lados, la derecha sí arrastra la corrección.
    _, gain_x_all, _ = corrected(p, ratios)
    assert min(gain_x_all) < -0.5
