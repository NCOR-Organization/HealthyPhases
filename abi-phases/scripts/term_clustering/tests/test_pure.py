"""Tests for the pure logic in the term-clustering scripts.

Run with:
    uv run --no-project --with pytest --with pandas --with pyarrow --with rdflib \
        --with scikit-learn --with numpy pytest scripts/term_clustering/tests -q
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from split_conditionals import FORM, normalize_part, split  # noqa: E402
from split_processes import normalize_key, parse_item  # noqa: E402
from bfo_proposal import enforce  # noqa: E402


# ---- conditionals ----

def test_split_at_last_then_keeps_commas_in_the_antecedent():
    m = FORM.match("If A, B and C, then D.")
    assert m.group(1) == "A, B and C"
    assert m.group(2) == "D"


def test_split_accepts_dash_and_comma_after_then():
    assert FORM.match("If an ending is near—then goals shift.").group(2) == "goals shift"
    assert FORM.match("If parents overprotect, then, in combination, risk rises.").group(2) == "in combination, risk rises"


def test_split_rejects_sentences_not_in_the_form():
    assert FORM.match("Solitude allows reflection.") is None


def test_normalize_part_folds_case_spacing_and_trailing_period():
    assert normalize_part("  Older  Adults. ") == "older adults"


def test_split_selects_both_prompt_names_and_reports_failures():
    items = pd.DataFrame({
        "item_id": ["1", "2", "3", "4"], "paper_id": ["p"] * 4, "chunk_id": ["c"] * 4,
        "prompt_id": ["conditional_statement_x", "logical_sentences_y", "solitude_how_z", "conditional_statement_x"],
        "prompt_name": ["conditional_statement", "logical_sentences", "solitude_how", "conditional_statement"],
        "text": ["If a, then b.", "If c, then d.", "Solitude helps.", "Not a conditional."],
    })
    good, bad = split(items)
    assert list(good["antecedent"]) == ["a", "c"]
    assert list(bad["text"]) == ["Not a conditional."]


# ---- probabilistic processes ----

def test_parse_item_reads_the_repr_and_normalises_direction():
    text = "{'subject_process': 'spending time alone', 'subject_participant': 'older adult', 'target_process': 'onset of loneliness', 'direction': 'increases', 'evidence_text': 'q'}"
    p = parse_item(text)
    assert p["subject_participant"] == "older adult" and p["direction"] == "increases"


def test_parse_item_rejects_garbage_and_missing_fields():
    assert parse_item("not a dict") is None
    assert parse_item("{'subject_process': 'x'}") is None


def test_parse_item_maps_unknown_direction_to_none():
    p = parse_item("{'subject_process': 'a', 'subject_participant': 'b', 'target_process': 'c', 'direction': 'modulates'}")
    assert p["direction"] == "none"


def test_normalize_key_is_stable_under_spacing_and_case():
    assert normalize_key("Older  Adults.") == normalize_key("older adults")


# ---- BFO pattern enforcement ----

def test_disposition_needs_a_process_target_unless_quality_wrapping_is_on():
    assert enforce("disposition", "quality", "quality")[0] == "evidence_only"
    assert enforce("disposition", "quality", "quality", wrap_quality=True)[0] == "disposition"
    assert enforce("disposition", "quality", "process")[0] == "disposition"


def test_a_decrease_claim_needs_a_decrease_target():
    assert enforce("disposition", "process", "process", direction="decreases", dst_label="decrease in loneliness")[0] == "disposition"
    assert enforce("disposition", "process", "process", direction="decreases", dst_label="increase in loneliness")[0] == "evidence_only"
    assert enforce("disposition", "process", "process", direction="decreases", dst_label="peer rejection")[0] == "evidence_only"


def test_subclass_needs_one_category_and_quality_attribution_needs_a_bearer():
    assert enforce("subclass", "process", "quality")[0] == "evidence_only"
    assert enforce("subclass", "process", "process")[0] == "subclass"
    assert enforce("quality_attribution", "process", "quality")[0] == "evidence_only"
    assert enforce("quality_attribution", "object", "quality")[0] == "quality_attribution"
