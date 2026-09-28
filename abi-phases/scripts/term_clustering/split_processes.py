# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas", "pyarrow"]
# ///
"""One-off: pull the probabilistic-process items out of the dump into tables.

Those items were extracted in BFO process form already: a participant, the
subject process it takes part in, a direction, and the target process whose
probability changes. Each becomes one row; the distinct process phrases (subject
and target together, since both are processes) and the distinct participants
become two phrase tables for embedding and clustering.

    uv run scripts/term_clustering/split_processes.py

Reads ``phases_v2_extracted_items.meta.parquet``; writes ``processes.parquet``,
``process_phrases.parquet`` and ``participants.parquet`` next to it.
"""

from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

import pandas as pd

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "storage/spikes/term_clustering"
PROMPT = "probabilistic_processes"
DIRECTIONS = {"increases", "decreases", "no-effect"}


def normalize_key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().rstrip(".").casefold()


def parse_item(text: str) -> dict | None:
    """The item text is the Python repr of the extracted object."""
    try:
        d = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None
    if not isinstance(d, dict):
        return None
    fields = {k: str(d.get(k, "")).strip() for k in ("subject_participant", "subject_process", "target_process", "direction", "evidence_text")}
    if not (fields["subject_participant"] and fields["subject_process"] and fields["target_process"]):
        return None
    if fields["direction"] not in DIRECTIONS:
        fields["direction"] = "none"
    return fields


def split(items: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, int]:
    rows, bad = [], 0
    for r in items.itertuples():
        parsed = parse_item(r.text)
        if parsed is None:
            bad += 1
            continue
        rows.append({
            "item_id": r.item_id, "paper_id": r.paper_id, "chunk_id": r.chunk_id, "prompt_id": r.prompt_id,
            "participant": parsed["subject_participant"], "participant_key": normalize_key(parsed["subject_participant"]),
            "subject": parsed["subject_process"], "subject_key": normalize_key(parsed["subject_process"]),
            "target": parsed["target_process"], "target_key": normalize_key(parsed["target_process"]),
            "direction": parsed["direction"], "evidence": parsed["evidence_text"],
        })
    processes = pd.DataFrame(rows)
    subj = processes[["subject_key", "subject"]].rename(columns={"subject_key": "key", "subject": "text"})
    tgt = processes[["target_key", "target"]].rename(columns={"target_key": "key", "target": "text"})
    phrases = pd.concat([subj, tgt]).drop_duplicates("key").set_index("key")["text"]
    phrases = pd.concat([phrases, subj.groupby("key").size().rename("as_subject"), tgt.groupby("key").size().rename("as_target")], axis=1)
    phrases = phrases.fillna({"as_subject": 0, "as_target": 0}).astype({"as_subject": int, "as_target": int}).reset_index().sort_values("key").reset_index(drop=True)
    participants = processes.groupby("participant_key").agg(text=("participant", "first"), n=("item_id", "size"), papers=("paper_id", "nunique")).reset_index().rename(columns={"participant_key": "key"})
    return processes, phrases, participants, bad


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args()

    items = pd.read_parquet(args.dir / "phases_v2_extracted_items.meta.parquet")
    items = items[items["prompt_name"].fillna("") == PROMPT]
    processes, phrases, participants, bad = split(items)
    print(f"probabilistic-process items: {len(items)}; parsed: {len(processes)}; unparseable: {bad}")
    print(f"directions: {processes['direction'].value_counts().to_dict()}")
    print(f"distinct process phrases: {len(phrases)} (subject-only {(phrases.as_target == 0).sum()}, target-only {(phrases.as_subject == 0).sum()}, both {((phrases.as_subject > 0) & (phrases.as_target > 0)).sum()})")
    print(f"distinct participants: {len(participants)}; papers: {processes['paper_id'].nunique()}")
    processes.to_parquet(args.dir / "processes.parquet", index=False)
    phrases.to_parquet(args.dir / "process_phrases.parquet", index=False)
    participants.to_parquet(args.dir / "participants.parquet", index=False)
    print("wrote processes.parquet, process_phrases.parquet, participants.parquet")


if __name__ == "__main__":
    main()
