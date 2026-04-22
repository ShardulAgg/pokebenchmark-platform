import pytest
from pokebenchmark_platform.orchestrator.play.keymap import GBA_KEYS, bit


def test_key_bits_match_mgba_enum():
    # mGBA GBA_KEY_* enum: A=0, B=1, Select=2, Start=3, Right=4, Left=5, Up=6, Down=7, R=8, L=9
    assert GBA_KEYS == {
        "A": 0, "B": 1, "Select": 2, "Start": 3,
        "Right": 4, "Left": 5, "Up": 6, "Down": 7,
        "R": 8, "L": 9,
    }


def test_bit_for_each_key():
    assert bit("A") == 1
    assert bit("B") == 2
    assert bit("Right") == 1 << 4
    assert bit("L") == 1 << 9


def test_bit_unknown_key_raises():
    with pytest.raises(KeyError):
        bit("Turbo")
