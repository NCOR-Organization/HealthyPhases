# /// script
# requires-python = ">=3.12"
# dependencies = ["openai>=1.40", "pandas", "pyarrow"]
# ///
"""One-off: classify every sentence behind a relation on its own, then count.

A relation between two clusters is backed by several "If X, then Y." claims.
Whether they agree is arithmetic once each claim is read separately: its
direction (the target becomes more likely, less likely, is unaffected, or the
claim says nothing about likelihood) and the condition it states, if any
("intrinsically motivated", "older adults", "by preference"). Contested is
then a minority share above a threshold with papers behind it, and the
conditions are the candidate narrower terms that resolve the disagreement.

    OPENAI_API_KEY=... uv run scripts/term_clustering/vote_directions.py --min-papers 2

Reads the parts clustering and the conditionals; writes ``edge_votes.parquet``
(one row per edge with counts, majority direction, contested flag and the
qualifiers) and ``sentence_votes.parquet`` (one row per sentence).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "storage/spikes/term_clustering"
MAX_SENTENCES = 24

SYSTEM = """You read claims of the form "If X, then Y." that all connect the same two concepts, and classify each one on its own.

For each claim report:
- direction, about the target concept Y as named in the claim: "increases" if the claim says Y becomes more likely, larger or stronger given X; "decreases" if less likely, smaller or weaker; "no_effect" if the claim explicitly says X makes no difference to Y; "none" if the claim relates X and Y without saying anything about likelihood or degree (a definition, a description, a measurement).
- qualifier: the condition or population the claim restricts itself to, as a short noun phrase copied or lightly normalised from the claim ("intrinsically motivated", "older adults", "by preference rather than anxiety"), or an empty string if the claim is general.
Judge each claim independently; do not harmonise them."""

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "properties": {
                    "index": {"type": "integer"},
                    "direction": {"type": "string", "enum": ["increases", "decreases", "no_effect", "none"]},
                    "qualifier": {"type": "string"},
                },
                "required": ["index", "direction", "qualifier"],
            },
        }
    },
    "required": ["claims"],
}


def vote(client, model: str, src_label: str, dst_label: str, sentences: list[str]) -> list[dict]:
    user = f"Source concept X: {src_label}\nTarget concept Y: {dst_label}\n\nClaims:\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(sentences))
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        response_format={"type": "json_schema", "json_schema": {"name": "votes", "strict": True, "schema": SCHEMA}},
        temperature=0,
    )
    out = json.loads(response.choices[0].message.content)["claims"]
    by_index = {c["index"]: c for c in out}
    return [by_index.get(i, {"index": i, "direction": "none", "qualifier": ""}) for i in range(len(sentences))]


def summarise(votes: pd.DataFrame, minority: float) -> dict:
    """Majority direction, whether the minority is large enough to call it contested, and the qualifiers."""
    counts = votes["direction"].value_counts()
    directional = counts.drop(labels=["none"], errors="ignore")
    total = int(directional.sum())
    if total == 0:
        return {"majority": "none", "share": 0.0, "contested": False}
    majority = str(directional.idxmax())
    share = float(directional.max() / total)
    opposing = votes[votes["direction"].isin({"increases", "decreases", "no_effect"} - {majority})]
    contested = (1 - share) >= minority and opposing["paper_id"].nunique() >= 2
    return {"majority": majority, "share": share, "contested": bool(contested)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--min-papers", type=int, default=2)
    parser.add_argument("--minority", type=float, default=0.25, help="minority share that makes a relation contested")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set")
    from openai import OpenAI

    client = OpenAI()
    cond = pd.read_parquet(args.dir / "conditionals.parquet")
    parts = pd.read_parquet(args.dir / "parts.parquet")
    assigned = pd.read_parquet(args.dir / "assignments_parts_mcs15_umap10.parquet").set_index("id")
    key_to_cluster = dict(zip(parts["key"], assigned.loc[parts["key"], "cluster"].to_numpy().tolist()))
    edges = pd.read_parquet(args.dir / "edges_parts_mcs15_umap10.parquet")
    edges = edges[(edges.src != edges.dst) & (edges.papers >= args.min_papers)]
    labels = {}
    try:
        for line in open(args.dir / "bfo_c/proposal_classes.jsonl"):
            p = json.loads(line)
            labels[p["cluster"]] = p["label"] or ", ".join(p["keywords"][:2])
    except FileNotFoundError:
        pass
    src_c = cond["antecedent_key"].map(key_to_cluster)
    dst_c = cond["consequent_key"].map(key_to_cluster)

    def one(row):
        sel = cond[(src_c == row.src) & (dst_c == row.dst)].drop_duplicates("text").head(MAX_SENTENCES)
        votes = vote(client, args.model, labels.get(int(row.src), f"C{row.src}"), labels.get(int(row.dst), f"C{row.dst}"), sel["text"].tolist())
        return [
            {"src": int(row.src), "dst": int(row.dst), "item_id": item_id, "paper_id": paper_id, "text": text,
             "direction": v["direction"], "qualifier": v["qualifier"].strip()}
            for (item_id, paper_id, text), v in zip(sel[["item_id", "paper_id", "text"]].itertuples(index=False), votes)
        ]

    print(f"voting on {len(edges)} edges with >= {args.min_papers} papers using {args.model}", file=sys.stderr)
    with ThreadPoolExecutor(args.workers) as pool:
        sentence_votes = pd.DataFrame([r for rows in pool.map(one, list(edges.itertuples())) for r in rows])
    sentence_votes.to_parquet(args.dir / "sentence_votes.parquet", index=False)

    rows = []
    for (s, d), grp in sentence_votes.groupby(["src", "dst"]):
        summary = summarise(grp, args.minority)
        qualifiers = grp.loc[grp["qualifier"] != "", "qualifier"].value_counts()
        rows.append({
            "src": s, "dst": d, "n": len(grp), "papers": grp["paper_id"].nunique(),
            "increases": int((grp.direction == "increases").sum()), "decreases": int((grp.direction == "decreases").sum()),
            "no_effect": int((grp.direction == "no_effect").sum()), "none": int((grp.direction == "none").sum()),
            "qualified": int((grp["qualifier"] != "").sum()), "qualifiers": [f"{q} ({n})" for q, n in qualifiers.head(6).items()],
            **summary,
        })
    edge_votes = pd.DataFrame(rows).sort_values(["papers", "n"], ascending=False)
    edge_votes.to_parquet(args.dir / "edge_votes.parquet", index=False)

    print(f"sentences classified: {len(sentence_votes)}; edges: {len(edge_votes)}")
    print(f"majority direction: {edge_votes['majority'].value_counts().to_dict()}")
    print(f"contested (minority >= {args.minority:.0%} with 2+ papers): {int(edge_votes['contested'].sum())}")
    print(f"edges with at least one qualified claim: {int((edge_votes['qualified'] > 0).sum())}")
    print("\ncontested edges:")
    for r in edge_votes[edge_votes.contested].itertuples():
        print(f"  {labels.get(r.src, r.src)} -> {labels.get(r.dst, r.dst)}: +{r.increases} -{r.decreases} ={r.no_effect} ~{r.none} | qualifiers: {'; '.join(r.qualifiers[:4])}")


if __name__ == "__main__":
    main()
