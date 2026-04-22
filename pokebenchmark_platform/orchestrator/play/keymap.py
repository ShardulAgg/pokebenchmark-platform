"""GBA key names and bitmask helpers for the play module."""

GBA_KEYS: dict[str, int] = {
    "A": 0,
    "B": 1,
    "Select": 2,
    "Start": 3,
    "Right": 4,
    "Left": 5,
    "Up": 6,
    "Down": 7,
    "R": 8,
    "L": 9,
}


def bit(name: str) -> int:
    """Return the single-bit mask for the given GBA key name."""
    return 1 << GBA_KEYS[name]
