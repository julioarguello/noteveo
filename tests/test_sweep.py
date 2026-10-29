"""El barrido de brillo: pasos neutros, numerados, de oscuro a claro."""

import numpy as np
import pytest

from noteveo import encode, sweep


def test_brightness_steps_are_neutral_and_geometric():
    steps = sweep.brightness_steps(15, 0.04, 1.0)
    assert [s.number for s in steps] == list(range(1, 16))
    levels = np.array([s.rgb[0] for s in steps])
    assert levels[0] == pytest.approx(0.04) and levels[-1] == pytest.approx(1.0)
    assert all(s.rgb[0] == s.rgb[1] == s.rgb[2] for s in steps)
    ratios = levels[1:] / levels[:-1]
    assert np.allclose(ratios, ratios[0])  # el mismo salto relativo entre pasos


@pytest.mark.parametrize("level", [0.04, 0.2, 1.0])
def test_step_frame_carries_its_number_in_the_top_right(level):
    codes = sweep.step_codes(sweep.Step(7, (level, level, level)))
    assert codes.shape == (sweep.HEIGHT, sweep.WIDTH, 3)
    base = encode.to_codes(np.array([level]))[0]
    corner = codes[:400, -600:].astype(float)
    rest = codes[600:, :2000].astype(float)
    assert abs(rest.mean() - base) < 1  # fondo del color del paso (con tramado de ±1)
    assert np.abs(corner - base).max() > sweep.LABEL_OFFSET / 2  # el número se ve
