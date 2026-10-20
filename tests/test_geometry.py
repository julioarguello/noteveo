import cv2
import numpy as np

from noteveo.geometry import find_dark_quad, order_corners
from tests.synthetic import CORNERS, room_with_tv_off, scale_quad


def test_finds_the_screen_within_3_px():
    found = find_dark_quad(room_with_tv_off())
    assert found is not None
    assert np.abs(found - CORNERS).max() < 3


def test_small_dark_quad_is_not_a_screen():
    # Un 3 % de la foto: por debajo del 5 % que exige locate.
    small = scale_quad(CORNERS, 0.4)
    assert find_dark_quad(room_with_tv_off(small)) is None


def test_corner_order_does_not_depend_on_input_order():
    shuffled = CORNERS[[2, 0, 3, 1]]
    assert np.array_equal(order_corners(shuffled), CORNERS)


def test_reflection_in_a_corner_does_not_move_it():
    """Un reflejo claro en la esquina de arriba a la derecha muerde el contorno oscuro."""
    room = room_with_tv_off()
    cv2.circle(room, (1150, 335), 90, (0.5, 0.5, 0.55), -1)
    found = find_dark_quad(room)
    assert found is not None
    assert np.abs(found - CORNERS).max() < 3
