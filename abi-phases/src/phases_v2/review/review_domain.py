"""Evidence checks and version binding; no model or storage dependencies."""

import hashlib
import json
import re

from phases_v2.projection.direction import qualify
from phases_v2.structured_text import canonical_payload_text

POLICY = "effects-review-v1"
AUTOMATIC_HOLD_FLAGS = {
    "verify_source_qualification",
    "verify_temporal_context",
    "compound_endpoint",
    "age_comparison",
    "attenuation_or_moderation",
    "ambiguous_null_evidence",
    "verify_generic_process_endpoint",
}
CLAIM_FIELDS = (
    "subject_process",
    "subject_change",
    "subject_participant",
    "target_process",
    "direction",
    "evidence_text",
)
FINGERPRINT_FIELDS = (
    "relation_id",
    "item_id",
    "relation_index",
    "extraction_id",
    "chunk_id",
    "paper_id",
    "prompt_id",
    "model_id",
    *CLAIM_FIELDS,
    "raw_item",
    "chunk_text",
    "prompt_template",
    "current_extraction_id",
    "current_chunk_id",
    "current_paper_id",
    "current_prompt_id",
    "current_model_id",
)


def fingerprint(row: dict) -> str:
    values = [
        POLICY,
        *(
            str(row.get(k) if row.get(k) is not None else "")
            for k in FINGERPRINT_FIELDS
        ),
    ]
    return hashlib.sha256("".join(f"{len(v)}:{v}" for v in values).encode()).hexdigest()


def assess(row: dict) -> dict:
    """Hard blockers require re-extraction; flags require explicit review."""
    blockers, flags = [], []
    quote, text = row.get("evidence_text") or "", row.get("chunk_text") or ""
    if not quote.strip() or quote not in text:
        blockers.append("evidence_not_exact")
    if row.get("extraction_status") != "succeeded":
        blockers.append("extraction_not_succeeded")
    if not row.get("prompt_template"):
        blockers.append("missing_prompt")
    if any(not isinstance(row.get(k), str) or not row[k].strip() for k in CLAIM_FIELDS):
        blockers.append("invalid_claim")
    if any(
        row.get("current_" + k) != row.get(k)
        for k in ("extraction_id", "chunk_id", "paper_id", "prompt_id", "model_id")
    ):
        blockers.append("stale_provenance")
    try:
        raw = json.loads(canonical_payload_text(row.get("raw_item") or ""))
        relations = raw if isinstance(raw, list) else raw.get("relations", [raw])
        relation = relations[row["relation_index"]]
        source = {
            **relation,
            **qualify(relation["direction"], relation.get("subject_change", "none")),
        }
        if any(source.get(k) != row.get(k) for k in CLAIM_FIELDS):
            blockers.append("stale_projection")
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        blockers.append("stale_projection")
    lower = quote.lower()
    if row.get("direction", "").startswith("prevents-"):
        flags.append("verify_prevention_not_attenuation")
    if row.get("direction") == "no-effect":
        flags.append("verify_null_effect_not_nonsignificance")
    if re.search(r"lesser|smaller|diminish|attenuat|buffer|moderat", lower):
        flags.append("attenuation_or_moderation")
    if re.search(r"hypothes|predict|propos|investigat|assess|explor", lower):
        flags.append("verify_finding_not_study_intent")
    if re.search(r"\bwhen\b|\bif\b|\bamong\b|\bonly\b", lower):
        flags.append("verify_conditions_preserved")
    if row.get("subject_change") == "none" and re.search(
        r"\bhigher\b|\blower\b|\bgreater\b|\bless\b", lower
    ):
        flags.append("verify_source_qualification")
    if re.search(
        r"\bcortisol\b|\bdheas\b|association between|deactivation of",
        (row.get("target_process") or "").lower(),
    ):
        flags.append("verify_generic_process_endpoint")
    endpoints = " ".join(
        row.get(k) or "" for k in ("subject_process", "target_process")
    )
    if " and " in endpoints.lower():
        flags.append("compound_endpoint")
    if row.get("subject_process", "").lower() == "solitude" and re.search(
        r"\b(momentary|overall) solitude\b", lower
    ):
        flags.append("verify_temporal_context")
    if row.get("subject_process", "").lower() == "aging" and re.search(
        r"greater age|older|age range", lower
    ):
        flags.append("age_comparison")
    if row.get("direction") == "no-effect" and re.search(
        r"not.*significant|non.?significant|unrelated|did not|does not", lower
    ):
        flags.append("ambiguous_null_evidence")
    return {"fingerprint": fingerprint(row), "blockers": blockers, "flags": flags}
