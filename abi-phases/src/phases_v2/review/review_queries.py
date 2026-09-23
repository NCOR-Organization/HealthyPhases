"""Dataset SQL for the same fail-closed gate in search, counts and export."""

from phases_v2.review.review_domain import FINGERPRINT_FIELDS, POLICY
from phases_v2.sql import literal

LATEST_JOIN = """
LEFT JOIN (
  SELECT * FROM effect_reviews
  QUALIFY row_number() OVER (
    PARTITION BY relation_id ORDER BY reviewed_at DESC, event_id DESC
  ) = 1
) review ON review.relation_id = r.relation_id
"""


def fingerprint_sql() -> str:
    overrides = {
        "raw_item": "ei.text",
        "chunk_text": "c.text",
        "prompt_template": "pr.template",
        "current_extraction_id": "ei.extraction_id",
        "current_chunk_id": "ei.chunk_id",
        "current_paper_id": "ei.paper_id",
        "current_prompt_id": "ei.prompt_id",
        "current_model_id": "e.model_id",
    }
    values = [literal(POLICY)] + [
        f"coalesce(CAST({overrides.get(k, 'r.' + k)} AS VARCHAR), '')"
        for k in FINGERPRINT_FIELDS
    ]
    return (
        "sha256("
        + " || ".join(f"CAST(length({v}) AS VARCHAR) || ':' || {v}" for v in values)
        + ")"
    )


def approved_sql() -> str:
    return (
        f"review.decision = 'approved' AND review.policy = {literal(POLICY)} "
        f"AND review.fingerprint = {fingerprint_sql()} "
        "AND e.status = 'succeeded' "
        "AND length(trim(r.evidence_text)) > 0 "
        "AND contains(c.text, r.evidence_text) "
        "AND NOT EXISTS (SELECT 1 FROM effect_reviews sibling "
        "WHERE sibling.relation_id = review.relation_id "
        "AND sibling.previous_event_id = review.previous_event_id "
        "AND sibling.event_id <> review.event_id)"
    )


QUEUE_FROM = (
    """
FROM probabilistic_relations r
LEFT JOIN extracted_items ei ON ei.item_id = r.item_id
LEFT JOIN extractions e ON e.extraction_id = ei.extraction_id
LEFT JOIN chunks c ON c.chunk_id = ei.chunk_id
LEFT JOIN prompts pr ON pr.prompt_id = ei.prompt_id
LEFT JOIN papers p ON p.paper_id = ei.paper_id
"""
    + LATEST_JOIN
)
QUEUE_COLUMNS = """
r.*, ei.text AS raw_item, c.text AS chunk_text,
ei.extraction_id AS current_extraction_id, ei.chunk_id AS current_chunk_id,
ei.paper_id AS current_paper_id, ei.prompt_id AS current_prompt_id,
e.model_id AS current_model_id,
pr.template AS prompt_template, e.status AS extraction_status,
p.file_name AS paper_name, review.event_id AS previous_event_id,
review.fingerprint AS reviewed_fingerprint, review.decision AS previous_decision,
review.reviewer AS previous_reviewer, review.note AS previous_note,
review.reviewer_prompt AS previous_review_prompt,
review.reviewer_response AS previous_review_response,
EXISTS (SELECT 1 FROM effect_reviews sibling
  WHERE sibling.relation_id = review.relation_id
  AND sibling.previous_event_id = review.previous_event_id
  AND sibling.event_id <> review.event_id) AS review_conflict
"""
