"""Self-contained review page; no network or automatic decision submission."""

import html
import json
from collections import Counter

from phases_v2.review.review_domain import CLAIM_FIELDS


def render_report(rows: list[dict]) -> str:
    esc = html.escape
    parts = [
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Effects review</title>',
        "<style>body{font:16px/1.5 system-ui;max-width:1050px;margin:32px auto;padding:20px}article{border:1px solid #bbc;padding:18px;margin:18px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}textarea{width:95%;height:70px}select,input,button{padding:8px}blockquote{background:#eef2f6;padding:12px;margin:12px 0}</style>",
        "<h1>Effects review</h1><p>Only approved, unchanged claims with exact evidence enter Effects search. Model approval is a review decision, not proof of causation. Keyword and semantic search remain raw extraction views.</p>",
        "<p>Inspect each claim and its full source. Any manual override requires a reason. Download decisions, then apply them with the review command. This page does not send data anywhere.</p>",
        '<label>Reviewer name <input id="reviewer"></label> <button id="download">Download selected decisions</button><p id="message"></p>',
    ]
    counts = Counter(row["status"] for row in rows)
    parts.append(
        "<p>This page: "
        + esc(", ".join(f"{n} {status}" for status, n in sorted(counts.items())))
        + "</p>"
    )
    parts.append(
        '<label>Show <select id="status-filter"><option value="">All claims</option><option>approved</option><option>rejected</option><option>uncertain</option><option>pending</option><option>blocked</option></select></label>'
    )
    for i, row in enumerate(rows):
        claim = {k: row[k] for k in CLAIM_FIELDS}
        parts.append(
            f'<article data-index="{i}" data-status="{esc(row["status"])}"><h2>'
            + esc(row.get("paper_name") or row["paper_id"])
            + "</h2><p>Status: <strong>"
            + esc(row["status"])
            + "</strong> | Previous reviewer: "
            + esc(row.get("previous_reviewer") or "none")
            + "</p><h3>"
            + esc(
                f"{row['subject_process']} [{row['subject_change']}] -> {row['direction']} -> {row['target_process']}"
            )
            + "</h3><p>Participant: "
            + esc(row["subject_participant"])
            + "</p><blockquote>"
            + esc(row["evidence_text"])
            + "</blockquote><details><summary>Claim fields</summary><pre>"
            + esc(json.dumps(claim, ensure_ascii=False, indent=2))
            + "</pre></details><p>Blockers: "
            + esc(", ".join(x.replace("_", " ") for x in row["blockers"]) or "none")
            + "</p><p>Review flags: "
            + esc(", ".join(x.replace("_", " ") for x in row["flags"]) or "none")
            + "</p><p>Previous note: "
            + esc(row.get("previous_note") or "none")
            + "</p><details><summary>Full source chunk</summary><pre>"
            + esc(row.get("chunk_text") or "")
            + "</pre></details><details><summary>Reviewer prompt and response</summary><pre>"
            + esc(row.get("previous_review_prompt") or "")
            + "</pre><pre>"
            + esc(row.get("previous_review_response") or "")
            + "</pre></details><details><summary>Extraction provenance</summary><pre>"
            + esc(
                json.dumps(
                    {
                        k: row.get(k)
                        for k in (
                            "relation_id",
                            "chunk_id",
                            "paper_id",
                            "model_id",
                            "prompt_id",
                            "fingerprint",
                        )
                    },
                    indent=2,
                )
            )
            + '</pre></details><label>New decision <select><option value="">Leave unchanged</option>'
            + ("" if row["blockers"] else '<option value="approved">Approve</option>')
            + '<option value="rejected">Reject</option><option value="uncertain">Uncertain / revoke approval</option></select></label><p><textarea placeholder="Reason for this decision"></textarea></p></article>'
        )
    identities = [
        {k: row[k] for k in ("relation_id", "fingerprint", "previous_event_id")}
        for row in rows
    ]
    # Prevent data containing </script> from terminating the inert JSON block.
    parts.append(
        '<script id="identities" type="application/json">'
        + json.dumps(identities).replace("<", "\\u003c")
        + "</script>"
    )
    parts.append("""<script>
document.getElementById('status-filter').addEventListener('change', (event) => {
  document.querySelectorAll('article').forEach(article => {
    article.hidden = !!(event.target.value && article.dataset.status !== event.target.value);
  });
});
document.getElementById('download').addEventListener('click', () => {
  const reviewer = document.getElementById('reviewer').value.trim();
  const identities = JSON.parse(document.getElementById('identities').textContent);
  const decisions = [];
  for (const article of document.querySelectorAll('article')) {
    const decision = article.querySelector('select').value;
    if (!decision) continue;
    const note = article.querySelector('textarea').value.trim();
    if (!note) { document.getElementById('message').textContent = 'Each selected decision needs a reason.'; return; }
    decisions.push({...identities[Number(article.dataset.index)], decision, note});
  }
  if (!reviewer || !decisions.length) { document.getElementById('message').textContent = 'Enter your name and select at least one decision.'; return; }
  const url = URL.createObjectURL(new Blob([JSON.stringify({reviewer, decisions}, null, 2)], {type: 'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = 'effect-decisions.json'; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
</script></html>""")
    return "\n".join(parts)
