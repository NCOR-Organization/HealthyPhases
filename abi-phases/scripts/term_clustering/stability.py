# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy", "pandas", "pyarrow", "scikit-learn>=1.4", "umap-learn>=0.5.6"]
# ///
"""One-off: how much does the batch clustering agree with itself?

The incremental spike scores assignment against one full-corpus clustering.
That is only a fair target if the full clustering is stable. Here the same
UMAP + HDBSCAN pipeline runs on the same data with different seeds, and each
pair of runs is scored with the same majority-mapping metric the incremental
spike uses, plus the adjusted Rand index. The result is the ceiling any
incremental method can be expected to reach.

    uv run scripts/term_clustering/stability.py --seeds 42 1 2
"""

from __future__ import annotations

import argparse
from itertools import combinations
from pathlib import Path

import numpy as np
from sklearn.cluster import HDBSCAN
from sklearn.metrics import adjusted_rand_score

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "storage/spikes/term_clustering"


def normalise(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(n == 0, 1, n)


def discover(unit: np.ndarray, mcs: int, seed: int) -> np.ndarray:
    import umap

    reduced = umap.UMAP(n_components=10, n_neighbors=15, min_dist=0.0, metric="cosine", random_state=seed).fit_transform(unit)
    return HDBSCAN(min_cluster_size=mcs, cluster_selection_method="eom").fit(reduced).labels_


def mapped_agreement(a: np.ndarray, b: np.ndarray) -> float:
    """Map every cluster of ``b`` to its majority cluster in ``a``; share of
    ``b``'s clustered points (that ``a`` also clustered) landing on that cluster."""
    both = (a >= 0) & (b >= 0)
    hits = 0
    for label in set(b[both]):
        sel = both & (b == label)
        values, counts = np.unique(a[sel], return_counts=True)
        hits += counts.max()
    return hits / both.sum()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--min-cluster-size", type=int, default=15)
    parser.add_argument("--seeds", nargs="+", type=int, default=[42, 1, 2])
    args = parser.parse_args()

    unit = normalise(np.load(args.dir / "parts.vectors.npy"))
    runs = {}
    for seed in args.seeds:
        labels = discover(unit, args.min_cluster_size, seed)
        runs[seed] = labels
        print(f"seed {seed}: {len(set(labels) - {-1})} clusters, noise {(labels == -1).mean():.0%}")

    print("\n| run A | run B | clustered in both | B->A majority agreement | A->B majority agreement | ARI (clustered in both) |")
    print("|---|---|---|---|---|---|")
    for s1, s2 in combinations(args.seeds, 2):
        a, b = runs[s1], runs[s2]
        both = (a >= 0) & (b >= 0)
        print(
            f"| {s1} | {s2} | {both.mean():.0%} | {mapped_agreement(a, b):.0%} | {mapped_agreement(b, a):.0%} | "
            f"{adjusted_rand_score(a[both], b[both]):.2f} |"
        )


if __name__ == "__main__":
    main()
