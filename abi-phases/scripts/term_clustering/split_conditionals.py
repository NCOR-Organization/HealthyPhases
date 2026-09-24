# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas", "pyarrow"]
# ///
"""One-off: pick the "If X, then Y." items out of the dump and split them in two.

The prompt forces exactly that form, so the split is a regex, not a model. The
two halves are what get embedded and clustered separately: an antecedent and a
consequent are each a candidate term, and the sentence is an edge between them.

    uv run scripts/term_clustering/split_conditionals.py

Reads ``phases_v2_extracted_items.meta.parquet`` written by ``dump_vectors.py``
and writes ``conditionals.parquet`` next to it. ``row`` is the row index into
the items dump, so the existing sentence vectors can be reused without
re-embedding.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "storage/spikes/term_clustering"
# The prompt was renamed once; both names are the same extraction.
CONDITIONAL_PROMPTS = ("conditional_statement", "logical_sentences")
# Greedy first group: split on the LAST ", then" so antecedents containing
# their own commas ("If A, B and C, then D") stay whole. A few items close the
# antecedent with a dash instead of a comma, or follow "then" with a comma.
FORM = re.compile(r"^\s*If\s+(.*)[,—–]\s*then,?\s+(.*?)\s*\.?\s*$", re.IGNORECASE | re.DOTALL)


def normalize_part(text: str) -> str:
    """Key used to deduplicate parts before embedding; the display text is kept as-is."""
    return re.sub(r"\s+", " ", text).strip().rstrip(".").casefold()


def split(items: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    prompt_name = items["prompt_name"].fillna("")
    prompt_id = items["prompt_id"].fillna("")
    is_conditional = prompt_name.isin(CONDITIONAL_PROMPTS) | prompt_id.str.startswith(
        CONDITIONAL_PROMPTS
    )
    selected = items.loc[is_conditional].copy()
    selected["row"] = selected.index

    parsed = selected["text"].str.extract(FORM)
    selected["antecedent"] = parsed[0].str.strip()
    selected["consequent"] = parsed[1].str.strip()
    ok = selected["antecedent"].notna() & selected["consequent"].notna()

    good = selected.loc[ok].copy()
    good["antecedent_key"] = good["antecedent"].map(normalize_part)
    good["consequent_key"] = good["consequent"].map(normalize_part)
    columns = [
        "row", "item_id", "paper_id", "chunk_id", "prompt_id", "prompt_name",
        "text", "antecedent", "consequent", "antecedent_key", "consequent_key",
    ]
    return good[columns].reset_index(drop=True), selected.loc[~ok, ["text"]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args()

    items = pd.read_parquet(args.dir / "phases_v2_extracted_items.meta.parquet")
    good, bad = split(items)

    print(f"items in dump:            {len(items)}")
    print(f"conditional items:        {len(good) + len(bad)}")
    print(f"  parsed as If/then:      {len(good)}")
    print(f"  not in the form:        {len(bad)}")
    for text in bad["text"].head(8):
        print(f"    - {text[:140]}")
    print(f"distinct antecedents:     {good['antecedent_key'].nunique()}")
    print(f"distinct consequents:     {good['consequent_key'].nunique()}")
    both = set(good["antecedent_key"]) & set(good["consequent_key"])
    print(f"parts used in both roles: {len(both)}")
    print(f"papers:                   {good['paper_id'].nunique()}")

    out = args.dir / "conditionals.parquet"
    good.to_parquet(out, index=False)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
