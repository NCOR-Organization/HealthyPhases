# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy", "pandas", "pyarrow", "scikit-learn>=1.4", "umap-learn>=0.5.6"]
# ///
"""One-off: can new papers be assigned to existing terms without re-clustering?

Simulates daily ingestion with the corpus we already have. The papers are put
in a fixed random order; the first ``--initial-papers`` are clustered once
("discovery") and every cluster becomes a term with a centroid and an
acceptance radius. The remaining papers then arrive one at a time and each new
half is assigned to the nearest term centroid if it falls inside that term's
radius, otherwise it waits in a pool. At the end, discovery runs on the pool
alone to see whether it recovers the concepts the initial papers lacked.

Every decision is scored against the full-corpus clustering from
``cluster.py`` (``assignments_parts_*.parquet``), which stands in for "the
truth we would have had by re-clustering everything".

    uv run scripts/term_clustering/incremental.py --initial-papers 16 \
        --rules p90 max mean2sd fixed:0.20

Radius rules, per term: ``p90`` / ``max`` / ``mean2sd`` are derived from the
term's own members' cosine distance to its centroid; ``fixed:<d>`` is one
global cosine distance. ``--update-centroids`` moves a centroid toward each
half assigned to it (running mean), to see whether drift helps or hurts.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import HDBSCAN

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "storage/spikes/term_clustering"


def normalise(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(n == 0, 1, n)


def discover(unit: np.ndarray, mcs: int, seed: int) -> np.ndarray:
    import umap

    reduced = umap.UMAP(n_components=10, n_neighbors=15, min_dist=0.0, metric="cosine", random_state=seed).fit_transform(unit)
    return HDBSCAN(min_cluster_size=mcs, cluster_selection_method="eom").fit(reduced).labels_


class Terms:
    """Centroids plus per-term radii; the thing a daily job would query."""

    def __init__(self, unit: np.ndarray, labels: np.ndarray, index: np.ndarray):
        self.ids = sorted(set(labels) - {-1})
        self.members = {t: index[labels == t] for t in self.ids}
        self.centroids = normalise(np.vstack([unit[self.members[t]].mean(axis=0) for t in self.ids]))
        self.radii = {"p90": [], "max": [], "mean2sd": []}
        for k, t in enumerate(self.ids):
            d = 1 - unit[self.members[t]] @ self.centroids[k]
            self.radii["p90"].append(float(np.quantile(d, 0.9)))
            self.radii["max"].append(float(d.max()))
            self.radii["mean2sd"].append(float(d.mean() + 2 * d.std()))
        self.radii = {k: np.asarray(v) for k, v in self.radii.items()}
        self.counts = np.asarray([len(self.members[t]) for t in self.ids], dtype=float)

        # Members as a matrix, for the k-nearest-member rules.
        pos = {t: k for k, t in enumerate(self.ids)}
        self.unit = unit
        self.member_idx = index[labels >= 0]
        self.member_term = np.asarray([pos[t] for t in labels[labels >= 0]])

    def assign(self, vectors: np.ndarray, rule: str) -> tuple[np.ndarray, np.ndarray]:
        """Return the term position for each vector, or -1 to pool it.

        Rules: ``p90`` / ``max`` / ``mean2sd`` (per-term radius), ``fixed:<d>``,
        ``margin:<radius rule>:<delta>`` (radius plus a lead over the runner-up),
        ``knn:<k>:<m>[:<dmax>]`` (at least m of the k nearest members agree, and
        the nearest member is within dmax).
        """
        if rule.startswith("knn:"):
            f = rule.split(":")
            k, m = int(f[1]), int(f[2])
            dmax = float(f[3]) if len(f) > 3 else None
            sims = vectors @ self.unit[self.member_idx].T
            top = np.argpartition(-sims, min(k, sims.shape[1] - 1), axis=1)[:, :k]
            out, dist = np.full(len(vectors), -1), np.empty(len(vectors))
            for r in range(len(vectors)):
                terms = self.member_term[top[r]]
                values, counts = np.unique(terms, return_counts=True)
                best = values[counts.argmax()]
                dist[r] = 1 - sims[r, top[r]].max()
                if counts.max() >= m and (dmax is None or dist[r] <= dmax):
                    out[r] = best
            return out, dist
        sims = vectors @ self.centroids.T
        order = np.argsort(-sims, axis=1)
        best, second = order[:, 0], order[:, 1]
        rows = np.arange(len(best))
        dist = 1 - sims[rows, best]
        if rule.startswith("margin:"):
            _, base, delta = rule.split(":")
            ok = (dist <= self.radii[base][best]) & (sims[rows, best] - sims[rows, second] >= float(delta))
        elif rule.startswith("fixed:"):
            ok = dist <= float(rule.split(":")[1])
        else:
            ok = dist <= self.radii[rule][best]
        return np.where(ok, best, -1), dist

    def update(self, k: int, i: int) -> None:
        """Adopt half ``i`` into term ``k``: moves the centroid and adds a member."""
        vector = self.unit[i]
        n = self.counts[k]
        self.centroids[k] = (self.centroids[k] * n + vector) / (n + 1)
        self.centroids[k] /= np.linalg.norm(self.centroids[k])
        self.counts[k] = n + 1
        self.member_idx = np.append(self.member_idx, i)
        self.member_term = np.append(self.member_term, k)


def majority(labels: np.ndarray) -> int:
    labels = labels[labels >= 0]
    if len(labels) == 0:
        return -1
    values, counts = np.unique(labels, return_counts=True)
    return int(values[counts.argmax()])


def run(args: argparse.Namespace) -> None:
    t0 = time.time()
    parts = pd.read_parquet(args.dir / "parts.parquet")
    unit = normalise(np.load(args.dir / "parts.vectors.npy"))
    cond = pd.read_parquet(args.dir / "conditionals.parquet")
    ref_df = pd.read_parquet(args.dir / f"assignments_parts_mcs{args.min_cluster_size}_umap10.parquet")
    key_pos = {k: i for i, k in enumerate(parts["key"])}
    ref = np.full(len(parts), -1)
    ref[[key_pos[k] for k in ref_df["id"]]] = ref_df["cluster"].to_numpy()

    # Arrival order and each half's first paper.
    papers = np.array(sorted(cond["paper_id"].unique()))
    order = np.random.default_rng(args.seed).permutation(len(papers))
    rank = {papers[i]: r for r, i in enumerate(order)}
    first = np.full(len(parts), 10**9)
    for a, c, p in zip(cond["antecedent_key"], cond["consequent_key"], cond["paper_id"]):
        for k in (a, c):
            i = key_pos[k]
            first[i] = min(first[i], rank[p])
    initial = np.flatnonzero(first < args.initial_papers)
    arrivals = [np.flatnonzero(first == r) for r in range(args.initial_papers, len(papers))]

    # Initial discovery.
    labels0 = discover(unit[initial], args.min_cluster_size, args.seed)
    terms = Terms(unit, labels0, initial)
    term_ref = np.asarray([majority(ref[terms.members[t]]) for t in terms.ids])
    covered = set(term_ref[term_ref >= 0].tolist())
    ref_clusters = set(ref[ref >= 0].tolist())
    initial_noise = initial[labels0 == -1]

    lines = [
        "# Incremental assignment spike",
        "",
        f"- papers: {len(papers)}; initial {args.initial_papers}, arriving {len(arrivals)} one at a time (seed {args.seed})",
        f"- halves in initial papers: {len(initial)}; arriving later: {sum(len(a) for a in arrivals)}",
        f"- initial discovery: {len(terms.ids)} terms, {len(initial_noise)} halves unplaced ({len(initial_noise) / len(initial):.0%})",
        f"- reference (full corpus): {len(ref_clusters)} clusters; {len(covered)} of them have a matching initial term ({len(covered) / len(ref_clusters):.0%} coverage)",
        "",
        "## Assignment of arriving halves, by radius rule",
        "",
        "Scored against the full-corpus clustering. *correct*: assigned to the term whose members the reference also groups together. "
        "*wrong term*: reference puts it in a different covered cluster. *absorbed*: reference puts it in a cluster no initial term covers (a new concept swallowed by an old term). "
        "*ref noise*: reference did not cluster it at all. *missed*: pooled although a matching term exists. *pooled new*: pooled, and the reference cluster is one no term covers (discovery's job).",
        "",
        "| rule | centroid update | assigned | correct | wrong term | absorbed | ref noise | pooled | missed | pooled new | pooled noise | precision | recall |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    results = {}
    for rule in args.rules:
        for update in ([False, True] if args.update_centroids else [False]):
            T = Terms(unit, labels0, initial) if update else terms
            tally = dict(assigned=0, correct=0, wrong=0, absorbed=0, refnoise=0, pooled=0, missed=0, poolednew=0, poolednoise=0)
            trajectory, pool = [], []
            for r, idx in enumerate(arrivals):
                if len(idx) == 0:
                    continue
                best, _ = T.assign(unit[idx], rule)
                a = 0
                for i, k in zip(idx, best):
                    if k >= 0:
                        a += 1
                        tally["assigned"] += 1
                        m = term_ref[k]
                        if ref[i] == -1:
                            tally["refnoise"] += 1
                        elif ref[i] == m:
                            tally["correct"] += 1
                        elif ref[i] in covered:
                            tally["wrong"] += 1
                        else:
                            tally["absorbed"] += 1
                        if update:
                            T.update(k, i)
                    else:
                        pool.append(i)
                        tally["pooled"] += 1
                        if ref[i] == -1:
                            tally["poolednoise"] += 1
                        elif ref[i] in covered:
                            tally["missed"] += 1
                        else:
                            tally["poolednew"] += 1
                trajectory.append((r + 1, len(idx), a))
            judged = tally["assigned"] - tally["refnoise"]
            precision = tally["correct"] / judged if judged else 0
            recall = tally["correct"] / (tally["correct"] + tally["missed"]) if tally["correct"] + tally["missed"] else 0
            name = f"{rule}{' +update' if update else ''}"
            results[name] = dict(tally=tally, pool=np.asarray(pool, dtype=int), trajectory=trajectory, precision=precision, recall=recall)
            lines.append(
                f"| {rule} | {'yes' if update else 'no'} | {tally['assigned']} | {tally['correct']} | {tally['wrong']} | {tally['absorbed']} | {tally['refnoise']} | "
                f"{tally['pooled']} | {tally['missed']} | {tally['poolednew']} | {tally['poolednoise']} | {precision:.0%} | {recall:.0%} |"
            )

    # Discovery on the pool, for the rule the report should focus on.
    focus = args.focus if args.focus in results else next(iter(results))
    pool = np.concatenate([initial_noise, results[focus]["pool"]])
    lines += ["", f"## Arrival trajectory ({focus})", "", "| paper | new halves | assigned | pooled |", "|---|---|---|---|"]
    for r, n, a in results[focus]["trajectory"]:
        lines.append(f"| {r} | {n} | {a} | {n - a} |")

    lines += ["", f"## Discovery on the pool ({focus}, context sample {args.pool_context:.0%})", ""]
    if len(pool) >= args.min_cluster_size * 2:
        # Existing members clustered alongside the pool give a fragment of an
        # existing term something to attach to, instead of becoming a duplicate.
        clustered0 = initial[labels0 >= 0]
        rng = np.random.default_rng(args.seed)
        context = rng.choice(clustered0, size=int(len(clustered0) * args.pool_context), replace=False) if args.pool_context > 0 else np.asarray([], dtype=int)
        term_of = dict(zip(clustered0.tolist(), labels0[labels0 >= 0].tolist()))
        both = np.concatenate([pool, context])
        is_context = np.concatenate([np.zeros(len(pool), bool), np.ones(len(context), bool)])
        labels_pool = discover(unit[both], args.min_cluster_size, args.seed)
        new_ids = sorted(set(labels_pool) - {-1})
        recovered, found_noise, merged, rows = set(), 0, 0, []
        for t in new_ids:
            sel = labels_pool == t
            members, ctx = both[sel & ~is_context], both[sel & is_context]
            if len(ctx) and len(ctx) >= 0.3 * sel.sum():
                ctx_terms = np.asarray([term_of[i] for i in ctx])
                values, counts = np.unique(ctx_terms, return_counts=True)
                if counts.max() >= 0.5 * len(ctx):
                    merged += 1
                    rows.append((t, len(members), int(values[counts.argmax()]), counts.max() / len(ctx), "merge into existing term"))
                    continue
            if len(members) == 0:
                continue
            m = majority(ref[members])
            purity = float((ref[members] == m).mean()) if m >= 0 else 0.0
            if m == -1:
                found_noise += 1
            elif m not in covered and purity >= 0.5:
                recovered.add(m)
            rows.append((t, len(members), m, purity, "duplicates a covered term" if m in covered else ("reference noise" if m == -1 else "new term")))
        uncovered = ref_clusters - covered
        unplaced = (labels_pool[~is_context] == -1).sum()
        lines += [
            f"- pool size: {len(pool)} halves ({len(initial_noise)} unplaced at discovery + {len(results[focus]['pool'])} pooled on arrival); context members added: {len(context)}",
            f"- clusters found: {len(new_ids)}; pool halves still unplaced: {unplaced} ({unplaced / len(pool):.0%})",
            f"- clusters that attach to an existing term (merge): {merged}",
            f"- reference clusters with no initial term: {len(uncovered)}; recovered as new terms (majority match, purity >= 50%): {len(recovered)} ({len(recovered) / max(len(uncovered), 1):.0%})",
            f"- new clusters that still duplicate a covered term: {sum(1 for r in rows if r[4] == 'duplicates a covered term')}",
            f"- new clusters the full run saw as noise: {found_noise}",
            "",
            "| cluster | pool halves | reference cluster / term | purity | status |",
            "|---|---|---|---|---|",
        ] + [f"| P{t} | {n} | {'noise' if m == -1 else ('term ' if s.startswith('merge') else 'C') + str(m)} | {p:.0%} | {s} |" for t, n, m, p, s in sorted(rows, key=lambda r: -r[1])[:40]]
    else:
        lines.append(f"- pool too small to cluster ({len(pool)} halves)")

    lines += ["", f"wall time: {time.time() - t0:.0f}s"]
    report = args.dir / f"report_incremental_init{args.initial_papers}_seed{args.seed}.md"
    report.write_text("\n".join(lines))
    print("\n".join(lines))
    print(f"\nfull report: {report}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--initial-papers", type=int, default=16)
    parser.add_argument("--min-cluster-size", type=int, default=15)
    parser.add_argument(
        "--rules", nargs="+",
        default=["p90", "margin:p90:0.02", "margin:p90:0.05", "knn:10:6", "knn:10:8", "knn:10:6:0.30", "knn:15:10", "knn:5:4"],
    )
    parser.add_argument("--focus", default="knn:10:6", help="rule whose pool is clustered and whose trajectory is shown")
    parser.add_argument("--pool-context", type=float, default=0.3, help="share of existing members clustered along with the pool")
    parser.add_argument("--update-centroids", action="store_true", help="also run every rule with the assigned halves adopted as members")
    parser.add_argument("--seed", type=int, default=42)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
