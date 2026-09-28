# /// script
# requires-python = ">=3.12"
# dependencies = ["openai>=1.40", "numpy", "pandas", "pyarrow"]
# ///
"""One-off: embed the distinct antecedents and consequents of the conditionals.

Same model and dimension as the corpus (``text-embedding-3-large`` at 3072), so
a part can later be compared with whole sentences or with ontology labels.

    OPENAI_API_KEY=... uv run scripts/term_clustering/embed_parts.py

Reads ``conditionals.parquet``; writes ``parts.parquet`` (one row per distinct
part: key, display text, how often it appears in each role) and
``parts.vectors.npy`` with rows aligned. Re-running embeds only new parts.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from openai import OpenAI

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "storage/spikes/term_clustering"
MODEL = "text-embedding-3-large"
DIMENSION = 3072
BATCH = 256


def distinct_parts(conditionals: pd.DataFrame) -> pd.DataFrame:
    ante = conditionals[["antecedent_key", "antecedent"]].rename(
        columns={"antecedent_key": "key", "antecedent": "text"}
    )
    cons = conditionals[["consequent_key", "consequent"]].rename(
        columns={"consequent_key": "key", "consequent": "text"}
    )
    ante_n = ante.groupby("key").size().rename("as_antecedent")
    cons_n = cons.groupby("key").size().rename("as_consequent")
    # One display text per key: the first spelling seen is as good as any.
    text = pd.concat([ante, cons]).drop_duplicates("key").set_index("key")["text"]
    parts = pd.concat([text, ante_n, cons_n], axis=1).fillna({"as_antecedent": 0, "as_consequent": 0})
    parts[["as_antecedent", "as_consequent"]] = parts[["as_antecedent", "as_consequent"]].astype(int)
    return parts.reset_index().sort_values("key").reset_index(drop=True)


def embed(client: OpenAI, texts: list[str]) -> np.ndarray:
    out = np.empty((len(texts), DIMENSION), dtype=np.float32)
    for start in range(0, len(texts), BATCH):
        batch = texts[start : start + BATCH]
        response = client.embeddings.create(model=MODEL, input=batch, dimensions=DIMENSION)
        for i, item in enumerate(response.data):
            out[start + i] = item.embedding
        print(f"\rembedded {min(start + BATCH, len(texts))}/{len(texts)}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--input", default="parts",
                        help="phrase table to embed: 'parts' (built from conditionals.parquet) or the stem of any parquet with key/text columns")
    args = parser.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set; export it (uv's --env-file cannot parse this repo's .env)")

    if args.input == "parts":
        conditionals = pd.read_parquet(args.dir / "conditionals.parquet")
        parts = distinct_parts(conditionals)
    else:
        parts = pd.read_parquet(args.dir / f"{args.input}.parquet")
        if not {"key", "text"} <= set(parts.columns):
            sys.exit(f"{args.input}.parquet needs 'key' and 'text' columns")
    print(f"distinct phrases in {args.input}: {len(parts)}")

    parts_path, vec_path = args.dir / f"{args.input}.parquet", args.dir / f"{args.input}.vectors.npy"
    known: dict[str, np.ndarray] = {}
    if parts_path.exists() and vec_path.exists():
        old = pd.read_parquet(parts_path)
        known = dict(zip(old["key"], np.load(vec_path)))
    missing = parts.loc[~parts["key"].isin(known)]
    print(f"already embedded: {len(parts) - len(missing)}, to embed: {len(missing)}")

    if len(missing):
        approx_tokens = int(missing["text"].str.split().str.len().sum() * 1.3)
        print(f"~{approx_tokens} tokens -> ~${approx_tokens / 1e6 * 0.13:.3f} at {MODEL} pricing")
        vectors = embed(OpenAI(), missing["text"].tolist())
        known.update(zip(missing["key"], vectors))

    matrix = np.vstack([known[k] for k in parts["key"]])
    parts.to_parquet(parts_path, index=False)
    np.save(vec_path, matrix)
    print(f"wrote {parts_path.name} and {vec_path.name} ({matrix.shape})")


if __name__ == "__main__":
    main()
