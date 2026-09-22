"""A claim about more or less of a process, read as a claim about the process."""

import pytest

from phases_v2.projection.direction import normalize


@pytest.mark.parametrize(
    ("stated", "expected"),
    [
        pytest.param(
            ("decreases", "none", "none"),
            ("decreases", False),
            id="social support decreases depression",
        ),
        pytest.param(
            ("increases", "more", "none"),
            ("increases", False),
            id="increased stress increases depression",
        ),
        pytest.param(
            ("increases", "less", "none"),
            ("decreases", True),
            id="reduced social support increases depression",
        ),
        pytest.param(
            ("decreases", "less", "none"),
            ("increases", True),
            id="lack of exercise decreases wellbeing",
        ),
        pytest.param(
            ("decreases", "none", "less"),
            ("increases", True),
            id="exercise decreases loss of muscle mass",
        ),
        pytest.param(
            ("decreases", "less", "less"),
            ("decreases", True),
            id="lack of sleep decreases loss of appetite",
        ),
        pytest.param(
            ("no-effect", "less", "none"),
            ("no-effect", True),
            id="reduced screen time has no effect on anxiety",
        ),
    ],
)
def test_the_signs_multiply_into_one_direction(stated, expected):
    assert normalize(*stated) == expected


def test_a_relation_without_change_fields_is_read_as_stated():
    # Extractions made before the prompt asked for the change fields.
    assert normalize("increases") == ("increases", False)


@pytest.mark.parametrize(
    ("stated", "named"),
    [
        (("uncertain", "none", "none"), "direction"),
        (("increases", "fewer", "none"), "subject_change"),
        (("increases", "none", ""), "target_change"),
    ],
)
def test_an_unknown_value_is_rejected_by_name(stated, named):
    with pytest.raises(ValueError, match=named):
        normalize(*stated)
