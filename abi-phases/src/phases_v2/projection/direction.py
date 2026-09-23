"""Preserve source qualification and target effect without sign arithmetic."""

DIRECTIONS = (
    "increases",
    "decreases",
    "no-effect",
    "prevents-increase",
    "prevents-decrease",
)
CHANGES = ("none", *DIRECTIONS)


def qualify(direction: str, subject_change: str = "none") -> dict[str, str]:
    """Read legacy amount labels without ever reversing a saved target effect.

    `none` means no source change was stated, not a finding of no effect.
    Legacy target_change is deliberately not an input: it duplicated direction.
    """
    subject_change = {"more": "increases", "less": "decreases"}.get(
        subject_change, subject_change
    )
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}, got {direction!r}")
    if subject_change not in CHANGES:
        raise ValueError(
            f"subject_change must be one of {CHANGES}, got {subject_change!r}"
        )
    return {"direction": direction, "subject_change": subject_change}
