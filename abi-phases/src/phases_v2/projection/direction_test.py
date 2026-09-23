"""The two endpoint qualifications must never be multiplied."""

import pytest

from phases_v2.projection.direction import CHANGES, DIRECTIONS, qualify


@pytest.mark.parametrize("direction", DIRECTIONS)
@pytest.mark.parametrize("source", CHANGES)
def test_source_and_target_effects_are_preserved_independently(direction, source):
    assert qualify(direction, source) == {
        "direction": direction,
        "subject_change": source,
    }


@pytest.mark.parametrize(("old", "new"), [("less", "decreases"), ("more", "increases")])
def test_legacy_source_qualification_does_not_reverse_target(old, new):
    assert qualify("increases", old) == {
        "direction": "increases",
        "subject_change": new,
    }


def test_unspecified_source_is_distinct_from_no_effect():
    assert qualify("decreases")["subject_change"] == "none"
    assert qualify("decreases", "no-effect")["subject_change"] == "no-effect"


@pytest.mark.parametrize(
    "direction,source", [("unknown", "none"), ("increases", "fewer")]
)
def test_unknown_effect_is_rejected(direction, source):
    with pytest.raises(ValueError):
        qualify(direction, source)
