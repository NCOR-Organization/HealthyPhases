# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy", "pandas", "pyarrow", "scikit-learn>=1.4", "umap-learn>=0.5.6"]
# ///
"""One-off: do the conditional statements form clusters we could name as terms?

Two variants of the same pipeline (L2-normalise -> UMAP -> HDBSCAN):

- ``sentences``: whole "If X, then Y." sentences, using the vectors already in
  the corpus. This is the baseline: what you get for free.
- ``parts``: the antecedents and consequents on their own (see
  ``embed_parts.py``). Each cluster is a candidate term, and every sentence
  becomes an edge between two clusters, so this variant also reports the
  term graph.

    uv run scripts/term_clustering/cluster.py --variant parts --min-cluster-size 15

Writes a markdown report and a parquet of assignments (with 2-D map
coordinates) into the spike directory. HDBSCAN leaves points it cannot place
as noise (label -1); the noise fraction is reported, not hidden.
"""

from __future__ import annotations

import argparse
import math
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import HDBSCAN
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, CountVectorizer

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "storage/spikes/term_clustering"
# Hedges the prompt asks for; they would otherwise top every keyword list.
HEDGES = {"may", "might", "tend", "tends", "likely", "often", "generally", "typically", "usually"}


@dataclass
class Corpus:
    variant: str
    ids: list[str]
    texts: list[str]
    vectors: np.ndarray
    extra: pd.DataFrame  # per-point columns worth showing (paper_id, role counts, ...)


def load(variant: str, directory: Path) -> Corpus:
    if variant == "sentences":
        conditionals = pd.read_parquet(directory / "conditionals.parquet")
        all_vectors = np.load(directory / "phases_v2_extracted_items.vectors.npy", mmap_mode="r")
        vectors = np.asarray(all_vectors[conditionals["row"].to_numpy()], dtype=np.float32)
        return Corpus(
            variant,
            conditionals["item_id"].tolist(),
            conditionals["text"].tolist(),
            vectors,
            conditionals[["paper_id"]],
        )
    if variant == "parts":
        parts = pd.read_parquet(directory / "parts.parquet")
        return Corpus(
            variant,
            parts["key"].tolist(),
            parts["text"].tolist(),
            np.load(directory / "parts.vectors.npy"),
            parts[["as_antecedent", "as_consequent"]],
        )
    raise ValueError(variant)


def normalise(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


def reduce(unit: np.ndarray, dim: int, seed: int) -> np.ndarray:
    if dim == 0:
        return unit
    import umap  # slow import (numba); keep it out of --help

    return umap.UMAP(
        n_components=dim, n_neighbors=15, min_dist=0.0, metric="cosine", random_state=seed
    ).fit_transform(unit)


def map_2d(unit: np.ndarray, seed: int) -> np.ndarray:
    import umap

    return umap.UMAP(n_components=2, n_neighbors=15, min_dist=0.1, metric="cosine", random_state=seed).fit_transform(unit)


def class_tfidf(texts: list[str], labels: np.ndarray, top: int = 8) -> dict[int, list[str]]:
    """BERTopic-style c-TF-IDF: one document per cluster, idf against clusters."""
    clusters = sorted(set(labels) - {-1})
    if not clusters:
        return {}
    docs = [" ".join(t for t, l in zip(texts, labels) if l == c) for c in clusters]
    vectoriser = CountVectorizer(
        stop_words=list(ENGLISH_STOP_WORDS | HEDGES), ngram_range=(1, 2), min_df=1
    )
    # Dense on purpose: the matrix is clusters x vocabulary, not documents x vocabulary.
    counts = vectoriser.fit_transform(docs).toarray().astype(np.float64)
    tf = counts / np.maximum(counts.sum(axis=1, keepdims=True), 1)
    words_per_class = counts.sum() / len(clusters)
    idf = np.log1p(words_per_class / np.maximum(counts.sum(axis=0), 1))
    scores = tf * idf
    vocab = vectoriser.get_feature_names_out()
    return {
        c: [vocab[i] for i in np.argsort(-scores[k])[:top] if scores[k, i] > 0]
        for k, c in enumerate(clusters)
    }


def central_examples(unit: np.ndarray, labels: np.ndarray, label: int, k: int) -> np.ndarray:
    members = np.flatnonzero(labels == label)
    centroid = unit[members].mean(axis=0)
    similarity = unit[members] @ centroid
    return members[np.argsort(-similarity)[:k]]


def term_graph(directory: Path, key_to_label: dict[str, int]) -> pd.DataFrame:
    """Every conditional whose two parts both landed in a cluster is an edge."""
    conditionals = pd.read_parquet(directory / "conditionals.parquet")
    src = conditionals["antecedent_key"].map(key_to_label)
    dst = conditionals["consequent_key"].map(key_to_label)
    edges = conditionals.assign(src=src, dst=dst)
    edges = edges[(edges["src"] >= 0) & (edges["dst"] >= 0)]
    return (
        edges.groupby(["src", "dst"])
        .agg(n=("item_id", "size"), papers=("paper_id", "nunique"), example=("text", "first"))
        .reset_index()
        .sort_values(["n", "papers"], ascending=False)
    )


def run(args: argparse.Namespace, variant: str) -> None:
    t0 = time.time()
    corpus = load(variant, args.dir)
    unit = normalise(corpus.vectors)
    reduced = reduce(unit, args.umap_dim, args.seed)
    model = HDBSCAN(
        min_cluster_size=args.min_cluster_size,
        min_samples=args.min_samples,
        cluster_selection_method="eom",
    ).fit(reduced)
    labels, probabilities = model.labels_, model.probabilities_
    coords = map_2d(unit, args.seed)
    elapsed = time.time() - t0

    n = len(labels)
    clusters = sorted(set(labels) - {-1})
    sizes = pd.Series(labels[labels >= 0]).value_counts()
    noise = int((labels == -1).sum())
    keywords = class_tfidf(corpus.texts, labels)

    stem = f"{variant}_mcs{args.min_cluster_size}_umap{args.umap_dim}"
    assignments = pd.DataFrame(
        {"id": corpus.ids, "text": corpus.texts, "cluster": labels, "probability": probabilities,
         "x": coords[:, 0], "y": coords[:, 1]}
    ).join(corpus.extra.reset_index(drop=True))
    assignments.to_parquet(args.dir / f"assignments_{stem}.parquet", index=False)

    lines = [
        f"# Term clustering spike — {variant}",
        "",
        f"- points: {n}",
        f"- UMAP dim: {args.umap_dim or 'none (raw 3072-d)'}; HDBSCAN min_cluster_size={args.min_cluster_size}, "
        f"min_samples={args.min_samples or args.min_cluster_size}; seed={args.seed}",
        f"- clusters: {len(clusters)}",
        f"- clustered: {n - noise} ({(n - noise) / n:.0%}); noise: {noise} ({noise / n:.0%})",
        f"- cluster sizes: min {sizes.min() if len(sizes) else 0}, median {int(sizes.median()) if len(sizes) else 0}, "
        f"max {sizes.max() if len(sizes) else 0}; ten largest: {sizes.head(10).tolist()}",
        f"- wall time: {elapsed:.0f}s",
        "",
    ]

    if variant == "parts":
        key_to_label = dict(zip(corpus.ids, labels.tolist()))
        edges = term_graph(args.dir, key_to_label)
        edges.to_parquet(args.dir / f"edges_{stem}.parquet", index=False)
        conditionals = pd.read_parquet(args.dir / "conditionals.parquet")
        both = int(edges["n"].sum())
        lines += [
            "## Term graph (antecedent cluster -> consequent cluster)",
            "",
            f"- conditionals with both parts clustered: {both}/{len(conditionals)} ({both / len(conditionals):.0%})",
            f"- distinct edges: {len(edges)}; edges seen in >=2 papers: {int((edges['papers'] >= 2).sum())}",
            "",
            "| n | papers | antecedent cluster | consequent cluster | example |",
            "|---|---|---|---|---|",
        ]
        for edge in edges.head(args.edges).itertuples():
            src_kw = ", ".join(keywords.get(edge.src, [])[:3])
            dst_kw = ", ".join(keywords.get(edge.dst, [])[:3])
            example = edge.example.replace("|", "/")
            lines.append(f"| {edge.n} | {edge.papers} | C{edge.src}: {src_kw} | C{edge.dst}: {dst_kw} | {example} |")
        lines.append("")

    lines += ["## Clusters (largest first)", ""]
    paper_ids = corpus.extra["paper_id"].to_numpy() if "paper_id" in corpus.extra else None
    for label in sizes.index:
        members = np.flatnonzero(labels == label)
        header = f"### C{label} — n={len(members)}"
        if paper_ids is not None:
            header += f", papers={len(set(paper_ids[members]))}"
        lines += [header, "", f"keywords: {', '.join(keywords.get(label, []))}", ""]
        for i in central_examples(unit, labels, label, args.examples):
            detail = ""
            if variant == "parts":
                a, c = corpus.extra.iloc[i]
                detail = f"  (as antecedent {a}x, as consequent {c}x)"
            lines.append(f"- {corpus.texts[i]}{detail}")
        lines.append("")

    report = args.dir / f"report_{stem}.md"
    report.write_text("\n".join(lines))
    print("\n".join(lines[: 8 if variant == "sentences" else 14]))
    print(f"\nfull report: {report}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", nargs="+", choices=("sentences", "parts"), default=["sentences", "parts"])
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--min-cluster-size", type=int, default=15)
    parser.add_argument("--min-samples", type=int, default=None)
    parser.add_argument("--umap-dim", type=int, default=10, help="0 clusters the raw vectors")
    parser.add_argument("--examples", type=int, default=6)
    parser.add_argument("--edges", type=int, default=40)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    for variant in args.variant:
        run(args, variant)


if __name__ == "__main__":
    main()
