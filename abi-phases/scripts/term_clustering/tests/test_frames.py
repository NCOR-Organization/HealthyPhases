"""Tests for the pure parts of frames.py (no model, no files)."""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from frames import (  # noqa: E402
    allowed_disposition, cluster_role, flatten, keywords_for, normalise_direction, normalize_key, polarity, split_by_polarity, summarise_direction,
)


# ---- polarity guard ----

def test_polarity_reads_degree_words_and_stays_neutral_when_mixed_or_absent():
    assert polarity("high autonomy") == "+" and polarity("low resting vagal tone") == "-"
    assert polarity("decrease in loneliness") == "-" and polarity("increase in positive affect") == "+"
    assert polarity("autonomy") == "" and polarity("low high something") == ""


def test_split_by_polarity_separates_opposite_values_and_keeps_unmarked_phrases_with_the_majority():
    texts = ["high autonomy", "higher autonomy", "low autonomy", "autonomy", "peer rejection"]
    labels = np.array([0, 0, 0, 0, 1])
    out = split_by_polarity(labels, texts)
    assert out[0] == out[1] == out[3] != out[2]   # the two '+' and the unmarked stay; the '-' moves out
    assert out[4] == 1                             # untouched cluster keeps its label
    assert out[2] not in (0, 1)                    # the new cluster gets a fresh id


def test_split_by_polarity_leaves_single_polarity_clusters_alone():
    texts = ["increase in loneliness", "increased loneliness", "loneliness"]
    assert split_by_polarity(np.array([3, 3, 3]), texts).tolist() == [3, 3, 3]


# ---- direction normalisation ----

def test_a_decreases_claim_is_rewritten_as_a_more_likely_decrease():
    c = _claim(ante={"process": "aging"}, cons={"process": "social interaction"}, direction="decreases")
    out = normalise_direction(c)
    assert out["consequent"]["process"] == "decrease in social interaction"
    assert out["relation"]["direction"] == "increases"


def test_a_decreases_claim_whose_target_already_names_the_change_is_left_alone():
    c = _claim(ante={"process": "aging"}, cons={"process": "decrease in loneliness"}, direction="decreases")
    out = normalise_direction(c)
    assert out["consequent"]["process"] == "decrease in loneliness" and out["relation"]["direction"] == "decreases"


def test_other_directions_are_untouched():
    for d in ("increases", "no_effect", "none"):
        c = normalise_direction(_claim(ante={"process": "a"}, cons={"process": "b"}, direction=d))
        assert c["consequent"]["process"] == "b" and c["relation"]["direction"] == d


def _claim(cid="c1", paper="p1", ante=None, cons=None, kind="tends_to", direction="increases"):
    frame = lambda **kw: {"process": "", "participants": [], "qualities": [], "realizables": [], "when": "", "where": "", "information": ""} | kw  # noqa: E731
    return {"claim_id": cid, "paper_id": paper, "chunk_id": "k", "antecedent": frame(**(ante or {})), "consequent": frame(**(cons or {})),
            "relation": {"kind": kind, "direction": direction}, "evidence": "q"}


# ---- flatten ----

def test_flatten_makes_one_row_per_filled_slot_and_ties_qualities_to_their_participant():
    c = _claim(ante={"process": "spending time alone", "participants": ["adolescents"], "qualities": [{"of": "adolescents", "quality": "high autonomy"}], "where": "at home"},
               cons={"process": "decrease in loneliness"})
    spans = flatten([c])
    assert sorted(spans["role"]) == ["participant", "process", "process", "quality", "where"]
    q = spans[spans.role == "quality"].iloc[0]
    # "of" is a key, so it matches the participant's key whatever the spelling
    assert q["of"] == normalize_key("adolescents") == spans[spans.role == "participant"].iloc[0]["key"]
    assert q["key"] == "high autonomy"
    assert (spans[spans.side == "consequent"]["role"] == "process").all()


def test_flatten_skips_empty_slots_and_normalises_keys():
    c = _claim(ante={"process": "  Spending Time Alone. "}, cons={"process": "x"})
    spans = flatten([c])
    assert len(spans) == 2
    assert spans.iloc[0]["key"] == "spending time alone" and spans.iloc[0]["text"] == "Spending Time Alone."


def test_normalize_key_folds_case_spacing_and_number_of_the_head_noun():
    assert normalize_key("Older  Adults.") == "older adult"
    assert normalize_key("parents") == normalize_key("parent")
    assert normalize_key("children") == normalize_key("child")
    assert normalize_key("solitary activities") == "solitary activity"


def test_normalize_key_leaves_words_that_only_look_plural():
    for word in ("loneliness", "process", "status", "analysis", "bias"):
        assert normalize_key(word) == word


# ---- clustering guards ----

def test_tiny_role_gets_one_cluster_per_phrase():
    unit = np.eye(5, dtype=np.float32)
    assert cluster_role(unit, mcs=5, seed=0).tolist() == [0, 1, 2, 3, 4]


def test_small_role_merges_paraphrases_but_keeps_distinct_concepts_apart():
    rng = np.random.default_rng(0)
    a = rng.normal(scale=0.3, size=(15, 8)) + np.array([5, 0, 0, 0, 0, 0, 0, 0])
    b = rng.normal(scale=0.3, size=(15, 8)) + np.array([0, 5, 0, 0, 0, 0, 0, 0])
    unit = np.vstack([a, b]); unit /= np.linalg.norm(unit, axis=1, keepdims=True)
    labels = cluster_role(unit, mcs=5, seed=0, merge_distance=0.15)
    assert (labels >= 0).all()  # agglomeration leaves no noise
    assert set(labels[:15]).isdisjoint(set(labels[15:]))
    assert len(set(labels)) <= 4  # tight paraphrase groups merge, the two concepts do not


def test_large_role_uses_density_and_can_leave_noise():
    rng = np.random.default_rng(1)
    unit = rng.normal(size=(320, 6)); unit /= np.linalg.norm(unit, axis=1, keepdims=True)
    labels = cluster_role(unit, mcs=5, seed=0, density_from=300)
    assert labels.shape == (320,) and (labels >= -1).all()


def test_empty_role_yields_empty_labels():
    assert cluster_role(np.zeros((0, 4), dtype=np.float32), mcs=5, seed=0).size == 0


def test_keywords_need_two_clusters_to_be_distinctive():
    assert keywords_for(["a b", "a c"], np.array([0, 0])) == {0: []}
    kw = keywords_for(["solitude autonomy", "solitude autonomy high", "peer rejection", "peer victimization"], np.array([0, 0, 1, 1]))
    assert "autonomy" in kw[0][0] or "autonomy" in kw[0]
    assert any("peer" in k for k in kw[1])


# ---- direction summary ----

def test_majority_and_contested_follow_the_same_rules_as_the_vote_script():
    assert summarise_direction(["increases", "increases", "none"], ["a", "b", "c"]) == ("increases", False)
    assert summarise_direction(["increases", "increases", "decreases", "decreases"], ["a", "b", "c", "d"]) == ("increases", True)
    assert summarise_direction(["increases", "increases", "decreases", "decreases"], ["a", "b", "c", "c"]) == ("increases", False)
    assert summarise_direction(["none", "none"], ["a", "b"]) == ("none", False)


# ---- disposition gate ----

def test_disposition_needs_a_process_or_quality_target():
    assert allowed_disposition("process", "process", "increases", "decrease in loneliness") == ""
    assert allowed_disposition("process", "quality", "increases", "loneliness") == ""
    assert "realization" in allowed_disposition("process", "role", "increases", "x")


def test_decreases_requires_the_change_to_be_named_and_null_findings_are_refused():
    assert allowed_disposition("process", "process", "decreases", "decrease in loneliness") == ""
    assert "less likely" in allowed_disposition("process", "process", "decreases", "peer rejection")
    assert "null finding" in allowed_disposition("process", "process", "no_effect", "peer rejection")
