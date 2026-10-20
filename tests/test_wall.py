import numpy as np
import pytest

from noteveo import params
from noteveo.encode import max_neighbor_step, quantize, sha256, to_codes, write_png
from noteveo.wall import (
    CORNER_BLEND,
    WallError,
    estimate_light,
    join_corners,
    render_linear,
    solve_laplace,
)
from tests.synthetic import CORNERS, room_with_tv_off


def make_params(**changes) -> params.Params:
    base = params.Params(
        reference_photo="sintetica.png",
        corners=CORNERS.tolist(),
        masks={},
        ring_width=6.0,
        ring_gap=1.0,
        light_smoothing=3.0,
        level=0.25,
        gain=[1.0, 1.0, 1.0],
        gain_x=[0.0, 0.0, 0.0],
        gain_y=[0.0, 0.0, 0.0],
        seconds=10,
        tv_device="192.0.2.1:5555",
    )
    for key, value in changes.items():
        setattr(base, key, value)
    return base


def test_laplace_reproduces_a_harmonic_function():
    """Una función armónica en píxeles: fijando sus bordes, el campo tiene que ser ella misma."""
    h, w = 270, 480
    x, y = np.arange(w) + 0.5, np.arange(h) + 0.5

    def f(px, py):
        u, v = px / w, py / w  # mismas unidades en los dos ejes
        return 0.3 + 0.2 * u - 0.1 * v + 0.15 * u * v + 0.05 * (u**2 - v**2)

    edges = {"top": f(x, -0.5), "bottom": f(x, h + 0.5), "left": f(-0.5, y), "right": f(w + 0.5, y)}
    xx, yy = np.meshgrid(x, y)
    assert np.abs(solve_laplace(h, w, edges) - f(xx, yy)).max() < 5e-4


def test_free_side_takes_no_value_of_its_own():
    """Con abajo libre y los otros tres a 0,5, todo el campo vale 0,5."""
    edges = {s: np.full(n, 0.5) for s, n in (("top", 240), ("left", 135), ("right", 135))}
    assert np.abs(solve_laplace(135, 240, edges) - 0.5).max() < 1e-6


def test_light_follows_the_wall_gradient():
    p = make_params()
    light = estimate_light(room_with_tv_off(), p)
    frame = render_linear(light, p, 384, 216)
    # El degradado sintético sube de izquierda a derecha: la pantalla también.
    assert frame[108, 380, 1] > frame[108, 4, 1] * 1.2
    assert set(light.edges) == {"top", "bottom", "left", "right"}


def test_mean_level_is_the_configured_level():
    p = make_params(level=0.3)
    frame = render_linear(estimate_light(room_with_tv_off(), p), p, 384, 216)
    assert frame[..., 1].mean() == pytest.approx(0.3, rel=0.01)


def test_masked_side_is_left_free():
    below = [[0.0, 700.0], [1600.0, 700.0], [1600.0, 1200.0], [0.0, 1200.0]]
    light = estimate_light(room_with_tv_off(), make_params(masks={"mueble": below}))
    assert "bottom" not in light.edges and light.coverage["bottom"] == 0


def test_masking_the_whole_ring_is_an_error():
    everything = [[0.0, 0.0], [1600.0, 0.0], [1600.0, 1200.0], [0.0, 1200.0]]
    with pytest.raises(WallError, match="píxeles de pared"):
        estimate_light(room_with_tv_off(), make_params(masks={"todo": everything}))


def test_edges_full_size_frame_is_smooth():
    """SC-005 sobre el fotograma real de 3840×2160."""
    p = make_params()
    frame = render_linear(estimate_light(room_with_tv_off(), p), p)
    assert frame.shape == (2160, 3840, 3)
    assert max_neighbor_step(to_codes(frame)) <= 1.0


def test_edge_check_catches_a_two_level_step():
    """Control de mutación: un escalón de dos niveles tiene que detectarse."""
    codes = np.full((10, 10, 3), 900.0)
    codes[:, 5:] += 2.0
    assert max_neighbor_step(codes) == pytest.approx(2.0)


def test_same_inputs_same_png(tmp_path):
    """SC-003: el fotograma sale idéntico byte a byte."""
    p = make_params()
    photo = room_with_tv_off()
    hashes = []
    for name in ("a.png", "b.png"):
        frame = render_linear(estimate_light(photo, p), p, 384, 216)
        write_png(quantize(to_codes(frame)), tmp_path / name)
        hashes.append(sha256(tmp_path / name))
    assert hashes[0] == hashes[1]


def test_corners_meet_after_joining():
    edges = {"top": np.linspace(0.6, 0.2, 100), "left": np.full(50, 0.4), "right": np.full(50, 0.1)}
    joined = join_corners(edges, 0.15)
    assert joined["top"][0] == pytest.approx(joined["left"][0])
    assert joined["top"][-1] == pytest.approx(joined["right"][0])
    assert joined["top"][50] == pytest.approx(edges["top"][50])  # lejos de las esquinas, igual


def test_mismatched_corner_stays_smooth_at_full_size():
    """Arriba claro y laterales oscuros: sin unir las esquinas habría un escalón (SC-005)."""
    edges = {"top": np.full(480, 0.6), "left": np.full(270, 0.15), "right": np.full(270, 0.15)}
    from noteveo.wall import Light

    joined = join_corners(edges, CORNER_BLEND)
    light = Light(solve_laplace(270, 480, joined), {}, {}, 0)
    frame = render_linear(light, make_params())
    assert max_neighbor_step(to_codes(frame)) <= 1.0
