# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy", "pandas", "pyarrow", "scipy", "scikit-learn>=1.4"]
# ///
"""One-off: merge duplicate clusters and build a broader/narrower tree over them.

HDBSCAN finds density, not genus. Two things a term hierarchy needs are missing
from its output: near-identical clusters that should be one term ("decrease in
high-arousal affect" twice), and the broader terms that group narrower ones.
Both come from the geometry of cluster centroids:

- merges: centroid pairs above ``--merge-threshold`` cosine similarity,
  closed under transitivity, become one term;
- tree: average-linkage agglomeration over the merged centroids, cut at
  ``--levels`` cosine distances, gives parent nodes with two or more children.

    uv run scripts/term_clustering/hierarchy.py --variant parts

Writes ``merges_<variant>.parquet``, ``hierarchy_<variant>.parquet`` and a
report; nothing is renamed, the module builder decides what to do with them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cluster import class_tfidf, normalise  # noqa: E402

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "storage/spikes/term_clustering"


def load(directory: Path, variant: str, mcs: int) -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    table = pd.read_parquet(directory / f"{variant}.parquet")
    unit = normalise(np.load(directory / f"{variant}.vectors.npy"))
    assigned = pd.read_parquet(directory / f"assignments_{variant}_mcs{mcs}_umap10.parquet").set_index("id")
    labels = assigned.loc[table["key"], "cluster"].to_numpy()
    return table, unit, labels


def centroids(unit: np.ndarray, labels: np.ndarray) -> tuple[list[int], np.ndarray]:
    ids = sorted(set(labels) - {-1})
    return ids, normalise(np.vstack([unit[labels == c].mean(axis=0) for c in ids]))


def merge_groups(ids: list[int], C: np.ndarray, threshold: float) -> dict[int, int]:
    """Cluster id -> group representative (smallest id), closed under transitivity."""
    parent = {c: c for c in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    sims = C @ C.T
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            if sims[i, j] >= threshold:
                a, b = find(ids[i]), find(ids[j])
                if a != b:
                    parent[max(a, b)] = min(a, b)
    return {c: find(c) for c in ids}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--variant", default="parts")
    parser.add_argument("--min-cluster-size", type=int, default=15)
    parser.add_argument("--merge-threshold", type=float, default=0.90, help="cosine similarity between centroids")
    parser.add_argument("--levels", nargs="+", type=float, default=[0.25, 0.40], help="cosine distances at which to cut the tree")
    args = parser.parse_args()

    table, unit, labels = load(args.dir, args.variant, args.min_cluster_size)
    texts = table["text"].tolist()
    ids, C = centroids(unit, labels)
    keywords = class_tfidf(texts, labels)
    label_of = lambda c: (keywords.get(c, [""])[:1] or [""])[0]  # noqa: E731

    # ---- merges ----
    group = merge_groups(ids, C, args.merge_threshold)
    groups = {}
    for c, g in group.items():
        groups.setdefault(g, []).append(c)
    merged = {g: members for g, members in groups.items() if len(members) > 1}
    merged_labels = labels.copy()
    for g, members in merged.items():
        for c in members:
            merged_labels[labels == c] = g
    pd.DataFrame([{"cluster": c, "group": g} for c, g in group.items()]).to_parquet(args.dir / f"merges_{args.variant}.parquet", index=False)

    # ---- tree over merged centroids ----
    gids, G = centroids(unit, merged_labels)
    Z = linkage(pdist(G, metric="cosine"), method="average") if len(gids) > 1 else None
    rows = [{"node": f"L0:{g}", "level": 0, "parent": None, "clusters": [g], "size": int((merged_labels == g).sum())} for g in gids]
    node_of_cluster = {g: f"L0:{g}" for g in gids}
    level_keywords = {0: {f"L0:{g}": class_tfidf(texts, merged_labels).get(g, []) for g in gids}}
    for level, cut in enumerate(args.levels, start=1):
        if Z is None:
            break
        assignment = fcluster(Z, t=cut, criterion="distance")
        parents = {}
        for g, a in zip(gids, assignment):
            parents.setdefault(int(a), []).append(g)
        node_labels = merged_labels.copy()
        for a, members in parents.items():
            for g in members:
                node_labels[merged_labels == g] = a
        kw = class_tfidf(texts, node_labels)
        level_keywords[level] = {}
        for a, members in parents.items():
            if len(members) < 2:
                continue  # a singleton parent adds no information
            node = f"L{level}:{a}"
            level_keywords[level][node] = kw.get(a, [])
            rows.append({"node": node, "level": level, "parent": None, "clusters": members, "size": int(node_labels[node_labels == a].size)})
            for g in members:
                # attach the child's current top node to this parent
                child = node_of_cluster[g]
                for r in rows:
                    if r["node"] == child and r["parent"] is None and r["level"] < level:
                        r["parent"] = node
                node_of_cluster[g] = node
    hierarchy = pd.DataFrame(rows)
    hierarchy["keywords"] = hierarchy["node"].map(lambda n: level_keywords.get(int(n[1]), {}).get(n, []))
    hierarchy.to_parquet(args.dir / f"hierarchy_{args.variant}.parquet", index=False)

    # ---- report ----
    lines = [
        f"# Hierarchy and merges — {args.variant}", "",
        f"- clusters: {len(ids)}; merge threshold {args.merge_threshold}: {len(merged)} groups absorbing {sum(len(m) - 1 for m in merged.values())} clusters -> {len(gids)} terms",
        f"- tree cuts at cosine distance {args.levels}: " + ", ".join(f"level {l}: {sum(1 for r in rows if r['level'] == l)} parents" for l in range(1, len(args.levels) + 1)),
        "", "## Merges", "",
    ]
    for g, members in sorted(merged.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"- **{label_of(g)}** <- " + "; ".join(f"C{c} ({', '.join(keywords.get(c, [])[:3])})" for c in members))
    lines += ["", "## Level 1 parents (children listed by first keyword)", ""]
    for r in sorted((r for r in rows if r["level"] == 1), key=lambda r: -r["size"])[:60]:
        lines.append(f"- **{', '.join(level_keywords[1][r['node']][:3])}** ({r['size']} halves): " + " · ".join(label_of(c) for c in r["clusters"]))
    if len(args.levels) > 1:
        lines += ["", "## Level 2 parents", ""]
        for r in sorted((r for r in rows if r["level"] == 2), key=lambda r: -r["size"])[:30]:
            lines.append(f"- **{', '.join(level_keywords[2][r['node']][:3])}** ({r['size']} halves, {len(r['clusters'])} terms)")
    report = args.dir / f"report_hierarchy_{args.variant}.md"
    report.write_text("\n".join(lines))
    print("\n".join(lines[:4]))
    print(f"\nfull report: {report}")


if __name__ == "__main__":
    main()
