"""Read a claim about more or less of a process as a claim about the process.

The model reports what the text states: "reduced social support increases
depression" arrives as subject_process="social support", subject_change="less",
direction="increases". Stored relations keep one plain node per process, so
the direction is rewritten here: social support decreases depression.

Each "less" is a negative sign, and the signs multiply. That deduction assumes
more of a process has the opposite effect of less of it, which a U-shaped or
threshold effect breaks, so every rewritten relation is flagged as deduced.
"""

from typing import NamedTuple

DIRECTIONS = ("increases", "decreases", "no-effect")
CHANGES = ("none", "more", "less")

_OPPOSITE = {"increases": "decreases", "decreases": "increases"}


class Normalized(NamedTuple):
    direction: str
    deduced_by_inversion: bool


def normalize(
    direction: str, subject_change: str = "none", target_change: str = "none"
) -> Normalized:
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}, got {direction!r}")
    for name, change in (
        ("subject_change", subject_change),
        ("target_change", target_change),
    ):
        if change not in CHANGES:
            raise ValueError(f"{name} must be one of {CHANGES}, got {change!r}")

    inversions = (subject_change, target_change).count("less")
    if inversions % 2:
        direction = _OPPOSITE.get(direction, direction)
    return Normalized(direction, deduced_by_inversion=inversions > 0)
