import numpy as np
import pytest

from noteveo.color import delta_e2000, linear_to_lab, srgb_to_linear

# Pares de la tabla 1 de Sharma, Wu y Dalal (2005): Lab 1, Lab 2, ΔE2000.
SHARMA = [
    ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
    ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
    ((50.0, 2.8361, -74.0200), (50.0, 0.0, -82.7485), 3.4412),
    ((50.0, 0.0, 0.0), (50.0, -1.0, 2.0), 2.3669),
    ((50.0, 2.4900, -0.0010), (50.0, -2.4900, 0.0009), 7.1792),
    ((50.0, 2.4900, -0.0010), (50.0, -2.4900, 0.0011), 7.2195),
    ((50.0, -0.0010, 2.4900), (50.0, 0.0009, -2.4900), 4.8045),
    ((50.0, 2.5, 0.0), (50.0, 0.0, -2.5), 4.3065),
    ((50.0, 2.5, 0.0), (73.0, 25.0, -18.0), 27.1492),
    ((50.0, 2.5, 0.0), (61.0, -5.0, 29.0), 22.8977),
    ((50.0, 2.5, 0.0), (56.0, -27.0, -3.0), 31.9030),
    ((50.0, 2.5, 0.0), (58.0, 24.0, 15.0), 19.4535),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((22.7233, 20.0904, -46.6940), (23.0331, 14.9730, -42.5619), 2.0373),
]


@pytest.mark.parametrize(("lab1", "lab2", "expected"), SHARMA)
def test_delta_e2000_matches_sharma(lab1, lab2, expected):
    assert delta_e2000(np.array(lab1), np.array(lab2)) == pytest.approx(expected, abs=1e-4)


def test_delta_e2000_is_symmetric():
    lab1, lab2 = np.array(SHARMA[8][0]), np.array(SHARMA[8][1])
    assert delta_e2000(lab1, lab2) == pytest.approx(delta_e2000(lab2, lab1))


def test_white_is_lightness_100_and_neutral():
    lab = linear_to_lab(np.array([1.0, 1.0, 1.0]))
    assert lab == pytest.approx([100.0, 0.0, 0.0], abs=1e-3)


def test_srgb_decoding_known_values():
    assert srgb_to_linear(np.array([0.0, 0.5, 1.0])) == pytest.approx(
        [0.0, 0.214041, 1.0], abs=1e-6
    )
