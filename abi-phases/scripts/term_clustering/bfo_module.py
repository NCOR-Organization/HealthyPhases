# /// script
# requires-python = ">=3.12"
# dependencies = ["openai>=1.40", "numpy", "pandas", "pyarrow", "scikit-learn>=1.4", "rdflib>=7"]
# ///
"""One-off: build the BFO 2020 module from every source we have.

Version 2 of ``bfo_proposal.py``. Same patterns, same plain-BFO output, but:

- two sources of terms: the halves of the conditional statements, and the
  subject/target processes plus the participants of the probabilistic-process
  items; classes from the two sources are aligned by centroid similarity so a
  concept both sources found is one class with aliases;
- duplicate clusters merged (``hierarchy.py``) before anything is categorised;
- relations from the process items need no model to axiomatise: participant,
  subject process, direction and target process are already there, so each
  (subject, participant, target) triple with enough papers becomes a
  disposition axiom, and the participant gives the process its
  ``has participant`` restriction;
- relations from the conditionals take their direction and contested flag
  from the per-sentence votes (``vote_directions.py``) when available;
- broader terms from the hierarchy become parent classes when all their
  children share one BFO category.

    OPENAI_API_KEY=... uv run scripts/term_clustering/bfo_module.py --min-papers 2

Categorisations and axiomatisations are cached as JSONL in the output directory,
so a rebuild after a code change costs nothing: a cached proposal is never
recomputed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from rdflib import BNode, Graph, Literal, Namespace, RDF, RDFS, OWL, XSD, URIRef

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bfo_proposal import (  # noqa: E402
    BFO_IRI, CATEGORIES, CLASS_SYSTEM, DEFINITION, OBO, PROCESSES, QUALITY_CHANGE_NOTE, REL,
    axiomatise, build_expression, categorise, enforce, intersection, restriction,
)
from cluster import central_examples, class_tfidf, normalise  # noqa: E402

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "storage/spikes/term_clustering"
SOURCES = {
    # variant, min_cluster_size, class-id prefix
    "parts": ("parts", 15, "C"),
    "process_phrases": ("process_phrases", 10, "P"),
    "participants": ("participants", 8, "A"),
}


class Source:
    """One clustered phrase table with its merges, centroids and summaries."""

    def __init__(self, directory: Path, name: str, variant: str, mcs: int, prefix: str, seed: int):
        self.name, self.prefix = name, prefix
        self.table = pd.read_parquet(directory / f"{variant}.parquet")
        self.unit = normalise(np.load(directory / f"{variant}.vectors.npy"))
        assigned = pd.read_parquet(directory / f"assignments_{variant}_mcs{mcs}_umap10.parquet").set_index("id")
        raw = assigned.loc[self.table["key"], "cluster"].to_numpy()
        merges_path = directory / f"merges_{variant}.parquet"
        group = {}
        if merges_path.exists():
            merges = pd.read_parquet(merges_path)
            group = dict(zip(merges["cluster"].astype(int), merges["group"].astype(int)))
        self.labels = np.asarray([group.get(int(c), int(c)) for c in raw])
        self.merged_from = defaultdict(list)
        for c, g in group.items():
            if c != g:
                self.merged_from[g].append(c)
        self.key_to_cluster = dict(zip(self.table["key"], self.labels.tolist()))
        self.ids = sorted(set(self.labels.tolist()) - {-1})
        self.centroids = {c: normalise(self.unit[self.labels == c].mean(axis=0, keepdims=True))[0] for c in self.ids}
        self.keywords = class_tfidf(self.table["text"].tolist(), self.labels)
        self.rng = np.random.default_rng(seed)
        hierarchy_path = directory / f"hierarchy_{variant}.parquet"
        self.hierarchy = pd.read_parquet(hierarchy_path) if hierarchy_path.exists() else None

    def summary(self, c: int, papers: int) -> dict:
        members = np.flatnonzero(self.labels == c)
        central = central_examples(self.unit, self.labels, c, 8)
        pool = [i for i in members if i not in set(central)]
        others = self.rng.choice(pool, size=min(6, len(pool)), replace=False) if pool else []
        texts = self.table["text"]
        roles = [col for col in self.table.columns if col.startswith("as_")]
        counts = {col: int(self.table[col].to_numpy()[members].sum()) for col in roles}
        return {
            "source": self.name, "cluster": int(c), "size": int(len(members)), "papers": papers,
            "keywords": self.keywords.get(c, []), "central": [texts[i] for i in central], "others": [texts[i] for i in others],
            "as_antecedent": counts.get("as_antecedent", counts.get("as_subject", 0)),
            "as_consequent": counts.get("as_consequent", counts.get("as_target", 0)),
        }


def cached_jsonl(path: Path) -> dict:
    if not path.exists():
        return {}
    rows = [json.loads(line) for line in open(path)]
    return {r["cluster"]: r for r in rows}


def append_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "a") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--out-name", default="bfo_v2")
    parser.add_argument("--base", default="http://purl.example.org/terms/")
    parser.add_argument("--model", default="gpt-4.1")
    parser.add_argument("--min-papers", type=int, default=2, help="papers behind a relation before it becomes an axiom")
    parser.add_argument("--align-threshold", type=float, default=0.90, help="centroid cosine similarity that makes two sources' clusters one term")
    parser.add_argument("--participant-share", type=float, default=0.5, help="share of a process's items naming one participant kind before it is asserted")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    out = args.dir / args.out_name
    out.mkdir(exist_ok=True)

    sources = {name: Source(args.dir, name, *SOURCES[name], args.seed) for name in SOURCES}
    cond = pd.read_parquet(args.dir / "conditionals.parquet")
    items = pd.read_parquet(args.dir / "processes.parquet")

    # papers per cluster, per source
    papers = {name: defaultdict(set) for name in sources}
    P = sources["parts"].key_to_cluster
    for a, c, p in zip(cond["antecedent_key"], cond["consequent_key"], cond["paper_id"]):
        for k in (P[a], P[c]):
            if k >= 0:
                papers["parts"][k].add(p)
    Q, A = sources["process_phrases"].key_to_cluster, sources["participants"].key_to_cluster
    for s, t, a, p in zip(items["subject_key"], items["target_key"], items["participant_key"], items["paper_id"]):
        for k in (Q[s], Q[t]):
            if k >= 0:
                papers["process_phrases"][k].add(p)
        if A[a] >= 0:
            papers["participants"][A[a]].add(p)

    # ---- categorise (cached per source; the parts cache is seeded from bfo_c) ----
    client = None

    def get_client():
        nonlocal client
        if client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                sys.exit("OPENAI_API_KEY is not set and the cache is incomplete")
            from openai import OpenAI

            client = OpenAI()
        return client

    class_system = CLASS_SYSTEM + QUALITY_CHANGE_NOTE
    proposals = {}
    for name, src in sources.items():
        cache_path = out / f"proposal_classes_{name}.jsonl"
        cache = cached_jsonl(cache_path)
        if name == "parts" and not cache and (args.dir / "bfo_c/proposal_classes.jsonl").exists():
            cache = cached_jsonl(args.dir / "bfo_c/proposal_classes.jsonl")
            append_jsonl(cache_path, list(cache.values()))
        missing = [c for c in src.ids if c not in cache]
        if missing:
            print(f"categorising {len(missing)} {name} clusters with {args.model}", file=sys.stderr)
            with ThreadPoolExecutor(args.workers) as pool:
                fresh = list(pool.map(lambda c: categorise(get_client(), args.model, src.summary(c, len(papers[name][c])), class_system), missing))
            append_jsonl(cache_path, fresh)
            cache.update({p["cluster"]: p for p in fresh})
        proposals[name] = {c: cache[c] for c in src.ids if c in cache}

    def is_domain(name, c):
        p = proposals[name].get(c)
        return bool(p) and p["kind"] == "domain_entity" and p["bfo_category"] in CATEGORIES

    # ---- align sources: a term is (source, cluster); aliases point at the canonical one ----
    canonical, aliases = {}, defaultdict(list)
    ranked = [(name, c) for name in ("process_phrases", "participants", "parts") for c in sources[name].ids if is_domain(name, c)]
    for i, (n1, c1) in enumerate(ranked):
        if (n1, c1) in canonical:
            continue
        canonical[(n1, c1)] = (n1, c1)
        v1 = sources[n1].centroids[c1]
        for n2, c2 in ranked[i + 1:]:
            if n2 == n1 or (n2, c2) in canonical:
                continue
            same_category = proposals[n1][c1]["bfo_category"] == proposals[n2][c2]["bfo_category"]
            if same_category and float(v1 @ sources[n2].centroids[c2]) >= args.align_threshold:
                canonical[(n2, c2)] = (n1, c1)
                aliases[(n1, c1)].append((n2, c2))
    terms = sorted(set(canonical.values()))
    print(f"terms: {len(terms)} canonical from {len(canonical)} domain-entity clusters ({len(canonical) - len(terms)} aligned across sources)", file=sys.stderr)

    # ---- the module ----
    T = Namespace(args.base)
    g = Graph()
    g.bind("terms", T); g.bind("obo", OBO); g.bind("owl", OWL)
    onto = URIRef(args.base.rstrip("/#"))
    g.add((onto, RDF.type, OWL.Ontology)); g.add((onto, OWL.imports, URIRef(BFO_IRI)))
    g.add((onto, RDFS.comment, Literal("Generated proposal from clustered claim fragments and process items. Every class and axiom is a proposal until accepted.")))
    for prop, label in (("clusterId", "cluster id (source:cluster)"), ("alias", "alias: another cluster this term absorbed"), ("supportPapers", "support: distinct papers"),
                        ("supportClaims", "support: claims"), ("proposalRationale", "proposal rationale"), ("proposalConfidence", "proposal confidence"),
                        ("evidence", "evidence sentence"), ("claimDirection", "claim direction: what the claims say happens to the target"),
                        ("contested", "contested: the supporting claims disagree"), ("qualifier", "qualifier stated by some supporting claims"),
                        ("proposedParent", "proposed parent: a grouping from the cluster hierarchy, not from the claims"), ("origin", "origin: how the axiom was derived")):
        g.add((T[prop], RDF.type, OWL.AnnotationProperty)); g.add((T[prop], RDFS.label, Literal(label)))

    iri, meta = {}, {}
    for name, c in terms:
        p = proposals[name][c]
        node = T[f"T{sources[name].prefix}{c:05d}"]
        iri[(name, c)] = node
        support = set(papers[name][c])
        for n2, c2 in aliases[(name, c)]:
            support |= papers[n2][c2]
        meta[(name, c)] = {"label": p["label"], "category": p["bfo_category"], "papers": len(support)}
        g.add((node, RDF.type, OWL.Class)); g.add((node, RDFS.subClassOf, OBO[CATEGORIES[p["bfo_category"]][0]]))
        g.add((node, RDFS.label, Literal(p["label"], lang="en"))); g.add((node, DEFINITION, Literal(p["definition"], lang="en")))
        g.add((node, T.clusterId, Literal(f"{name}:{c}"))); g.add((node, T.supportPapers, Literal(len(support))))
        g.add((node, T.proposalRationale, Literal(p["rationale"]))); g.add((node, T.proposalConfidence, Literal(p["confidence"], datatype=XSD.decimal)))
        for n2, c2 in aliases[(name, c)]:
            g.add((node, T.alias, Literal(f"{n2}:{c2} {proposals[n2][c2]['label']}")))
        for c2 in sources[name].merged_from.get(c, []):
            g.add((node, T.alias, Literal(f"{name}:{c2} (merged)")))
    for key, canon in canonical.items():
        iri[key] = iri[canon]

    ev = Graph(); ev.bind("terms", T); ev.bind("obo", OBO)
    ev_onto = URIRef(args.base.rstrip("/#") + "/evidence")
    ev.add((ev_onto, RDF.type, OWL.Ontology)); ev.add((ev_onto, OWL.imports, onto))

    def annotate(source_node, pred, copy, a: dict):
        ann = BNode()
        g.add((ann, RDF.type, OWL.Axiom)); g.add((ann, OWL.annotatedSource, source_node)); g.add((ann, OWL.annotatedProperty, pred)); g.add((ann, OWL.annotatedTarget, copy))
        g.add((ann, T.supportPapers, Literal(a["papers"]))); g.add((ann, T.supportClaims, Literal(a["n"])))
        g.add((ann, T.claimDirection, Literal(a.get("direction", "none")))); g.add((ann, T.origin, Literal(a["origin"])))
        if a.get("rationale"):
            g.add((ann, T.proposalRationale, Literal(a["rationale"])))
        if a.get("contested"):
            g.add((ann, T.contested, Literal(True)))
        for q in a.get("qualifiers", []):
            g.add((ann, T.qualifier, Literal(q)))
        for item_id, text in zip(a.get("item_ids", []), a.get("examples", [])):
            sent = T[f"S{item_id[:16]}"]
            g.add((ann, T.evidence, sent)); ev.add((sent, RDFS.label, Literal(text)))

    # ---- axioms from the process items: no model, the structure is the pattern ----
    votes_path = args.dir / "edge_votes.parquet"
    edge_votes = pd.read_parquet(votes_path).set_index(["src", "dst"]) if votes_path.exists() else None
    items = items.assign(s=items["subject_key"].map(Q), t=items["target_key"].map(Q), a=items["participant_key"].map(A))
    usable = items[(items.s >= 0) & (items.t >= 0)]
    process_axioms, evidence_only = [], []
    for (s, t), grp in usable.groupby(["s", "t"]):
        s, t = int(s), int(t)
        if s == t or not (is_domain("process_phrases", s) and is_domain("process_phrases", t)):
            continue
        n, n_papers = len(grp), grp["paper_id"].nunique()
        if n_papers < args.min_papers:
            continue
        counts = Counter(grp["direction"])
        directional = {k: v for k, v in counts.items() if k in ("increases", "decreases", "no-effect")}
        majority = max(directional, key=directional.get) if directional else "none"
        share = directional[majority] / sum(directional.values()) if directional else 0
        opposing = grp[grp["direction"].isin(set(directional) - {majority})]
        contested = bool(directional) and (1 - share) >= 0.25 and opposing["paper_id"].nunique() >= 2
        participants_ = Counter(int(a) for a in grp["a"] if a >= 0 and is_domain("participants", int(a)))
        part = participants_.most_common(1)[0][0] if participants_ and participants_.most_common(1)[0][1] >= args.participant_share * n else None
        src_meta, dst_meta = meta[canonical[("process_phrases", s)]], meta[canonical[("process_phrases", t)]]
        direction = {"increases": "increases", "decreases": "decreases", "no-effect": "no_effect"}.get(majority, "none")
        a = {"origin": "process items", "src_label": src_meta["label"], "dst_label": dst_meta["label"], "src_category": src_meta["category"],
             "dst_category": dst_meta["category"], "n": int(n), "papers": int(n_papers), "direction": direction, "contested": contested,
             "examples": (grp["participant"] + " | " + grp["subject"] + " -> " + grp["target"] + " (" + grp["direction"] + ")").drop_duplicates().head(8).tolist(),
             "item_ids": grp["item_id"].head(8).tolist(), "pattern": "disposition", "participant": part}
        pattern, note = enforce("disposition", src_meta["category"], dst_meta["category"], True, direction, dst_meta["label"])
        if direction == "no_effect":
            pattern, note = "evidence_only", "null finding: the claims say the target is unaffected"
        a["pattern"], a["enforced"] = pattern, note
        if pattern == "evidence_only":
            evidence_only.append(a)
            continue
        src_node, dst_node = iri[("process_phrases", s)], iri[("process_phrases", t)]
        if src_meta["category"] in PROCESSES and part is not None:
            def expr():
                target = dst_node if dst_meta["category"] in PROCESSES else intersection(g, OBO.BFO_0000015, restriction(g, REL["has participant"], restriction(g, REL["bearer of"], dst_node)))
                realizable = intersection(g, OBO.BFO_0000016, restriction(g, REL["has realization"], target, "only"))
                return restriction(g, REL["has participant"], intersection(g, iri[("participants", part)], restriction(g, REL["bearer of"], realizable)))
            obj, copy = expr(), expr()
            text = (f"'{src_meta['label']}' SubClassOf 'has participant' some ('{meta[canonical[('participants', part)]]['label']}' and 'bearer of' some "
                    f"(disposition and 'has realization' only '{dst_meta['label']}'))")
        else:
            obj, text = build_expression(g, T, a, dst_node, src_meta["category"])
            copy, _ = build_expression(g, T, a, dst_node, src_meta["category"])
            text = f"'{src_meta['label']}' SubClassOf {text}"
        g.add((src_node, RDFS.subClassOf, obj)); annotate(src_node, RDFS.subClassOf, copy, a)
        a["manchester"] = text
        process_axioms.append(a)

    # ---- participant restrictions on process classes ----
    participant_axioms = []
    for s, grp in usable[usable.a >= 0].groupby("s"):
        s = int(s)
        if not is_domain("process_phrases", s) or meta[canonical[("process_phrases", s)]]["category"] not in PROCESSES:
            continue
        counts = Counter(int(a) for a in grp["a"] if is_domain("participants", int(a)))
        if not counts:
            continue
        part, k = counts.most_common(1)[0]
        n_papers = grp[grp.a == part]["paper_id"].nunique()
        if k < args.participant_share * len(grp) or n_papers < args.min_papers:
            continue
        node = iri[("process_phrases", s)]
        obj, copy = restriction(g, REL["has participant"], iri[("participants", part)]), restriction(g, REL["has participant"], iri[("participants", part)])
        g.add((node, RDFS.subClassOf, obj))
        annotate(node, RDFS.subClassOf, copy, {"origin": "process items: participant", "n": int(k), "papers": int(n_papers), "direction": "none"})
        participant_axioms.append(f"'{meta[canonical[('process_phrases', s)]]['label']}' SubClassOf 'has participant' some '{meta[canonical[('participants', part)]]['label']}'  [{k}/{len(grp)} items, {n_papers} papers]")

    # ---- axioms from the conditionals: model-proposed pattern, voted direction ----
    edges = pd.read_parquet(args.dir / "edges_parts_mcs15_umap10.parquet")
    src_c, dst_c = cond["antecedent_key"].map(P), cond["consequent_key"].map(P)
    cache_path = out / "proposal_axioms_parts.jsonl"
    cache = {(r["src"], r["dst"]): r for r in (json.loads(l) for l in open(cache_path))} if cache_path.exists() else {}
    if not cache and (args.dir / "bfo_c/proposal_axioms.jsonl").exists():
        for line in open(args.dir / "bfo_c/proposal_axioms.jsonl"):
            r = json.loads(line)
            cache[(r["src"], r["dst"])] = r
    edges = edges[(edges.src != edges.dst) & (edges.papers >= args.min_papers)]
    edges = edges[[is_domain("parts", int(r.src)) and is_domain("parts", int(r.dst)) for r in edges.itertuples()]]
    todo = [r for r in edges.itertuples() if (int(r.src), int(r.dst)) not in cache]

    def one_edge(row):
        s, d = int(row.src), int(row.dst)
        sm, dm = proposals["parts"][s], proposals["parts"][d]
        sel = cond[(src_c == s) & (dst_c == d)]
        e = {"src": s, "dst": d, "n": int(row.n), "papers": int(row.papers), "src_label": sm["label"], "dst_label": dm["label"],
             "src_category": sm["bfo_category"], "dst_category": dm["bfo_category"], "examples": sel.drop_duplicates("text")["text"].head(8).tolist(),
             "item_ids": sel["item_id"].head(8).tolist()}
        a = axiomatise(get_client(), args.model, e, sm, dm, e["examples"])
        return e | a | {"proposed_pattern": a["pattern"]}

    if todo:
        print(f"axiomatising {len(todo)} conditional relations with {args.model}", file=sys.stderr)
        with ThreadPoolExecutor(args.workers) as pool:
            fresh = list(pool.map(one_edge, todo))
        for r in fresh:
            cache[(r["src"], r["dst"])] = r
    with open(cache_path, "w") as f:
        for r in cache.values():
            f.write(json.dumps({k: v for k, v in r.items() if k != "manchester"}, ensure_ascii=False) + "\n")

    conditional_axioms = []
    for row in edges.itertuples():
        a = dict(cache[(int(row.src), int(row.dst))])
        a["origin"] = "conditionals"
        if edge_votes is not None and (a["src"], a["dst"]) in edge_votes.index:
            v = edge_votes.loc[(a["src"], a["dst"])]
            a["direction"] = str(v["majority"])
            a["contested"] = bool(v["contested"]); a["qualifiers"] = list(v["qualifiers"])
        src_meta, dst_meta = meta[canonical[("parts", a["src"])]], meta[canonical[("parts", a["dst"])]]
        a["src_label"], a["dst_label"], a["src_category"], a["dst_category"] = src_meta["label"], dst_meta["label"], src_meta["category"], dst_meta["category"]
        pattern, note = enforce(a["proposed_pattern"], a["src_category"], a["dst_category"], True, a.get("direction", "none"), a["dst_label"])
        if a.get("direction") == "no_effect":
            pattern, note = "evidence_only", "null finding"
        a["pattern"], a["enforced"] = pattern, note
        if pattern == "evidence_only":
            evidence_only.append(a)
            continue
        src_node, dst_node = iri[("parts", a["src"])], iri[("parts", a["dst"])]
        obj, text = build_expression(g, T, a, dst_node, a["src_category"])
        copy, _ = build_expression(g, T, a, dst_node, a["src_category"])
        pred = OWL.equivalentClass if pattern == "equivalent" else RDFS.subClassOf
        g.add((src_node, pred, obj)); annotate(src_node, pred, copy, a)
        a["manchester"] = f"'{a['src_label']}' {'EquivalentTo' if pattern == 'equivalent' else 'SubClassOf'} {text}"
        conditional_axioms.append(a)

    # ---- hierarchy: level-1 parents whose children share one category ----
    parent_classes = []
    for name, src in sources.items():
        if src.hierarchy is None:
            continue
        for r in src.hierarchy[src.hierarchy.level == 1].itertuples():
            children = [(name, int(c)) for c in r.clusters if is_domain(name, int(c))]
            cats = {meta[canonical[ch]]["category"] for ch in children}
            if len(children) < 2 or len(cats) != 1 or len(children) > 12:
                continue
            cat = cats.pop()
            node = T[f"T{src.prefix}G{int(r.node.split(':')[1]):04d}"]
            label = ", ".join(list(r.keywords)[:2])
            g.add((node, RDF.type, OWL.Class)); g.add((node, RDFS.subClassOf, OBO[CATEGORIES[cat][0]]))
            g.add((node, RDFS.label, Literal(label, lang="en")))
            g.add((node, DEFINITION, Literal(f"A {cat} grouping {', '.join(meta[canonical[ch]]['label'] for ch in children)} (proposed from the cluster hierarchy; to be named and defined).", lang="en")))
            g.add((node, T.proposedParent, Literal(True)))
            for ch in children:
                g.add((iri[ch], RDFS.subClassOf, node))
            parent_classes.append((label, cat, [meta[canonical[ch]]["label"] for ch in children]))

    g.serialize(out / "terms.ttl", format="turtle"); g.serialize(out / "terms.owl", format="xml"); ev.serialize(out / "evidence.ttl", format="turtle")

    # ---- divergence: same source, opposite change targets; effect vs null finding; contested ----
    divergences = []
    all_axioms = process_axioms + conditional_axioms + evidence_only
    by_src = defaultdict(list)
    for a in all_axioms:
        by_src[a["src_label"]].append(a)
    for s, rows in by_src.items():
        for i, a in enumerate(rows):
            for b in rows[i + 1:]:
                la, lb = a["dst_label"].lower(), b["dst_label"].lower()
                qa = la.split(" in ", 1)[1] if la.startswith(("increase in ", "decrease in ")) else None
                qb = lb.split(" in ", 1)[1] if lb.startswith(("increase in ", "decrease in ")) else None
                if qa and qb and qa == qb and la[:3] != lb[:3]:
                    divergences.append(f"- **{s}**: {a['dst_label']} ({a['papers']} papers, {a['origin']}) vs {b['dst_label']} ({b['papers']} papers, {b['origin']})")
                dirs = {a.get("direction"), b.get("direction")}
                if a["dst_label"] == b["dst_label"] and "no_effect" in dirs and dirs != {"no_effect"}:
                    divergences.append(f"- **{s} -> {a['dst_label']}**: effect ({a['origin']}) vs null finding ({b['origin']})")
    for a in all_axioms:
        if a.get("contested"):
            quals = "; ".join(a.get("qualifiers", [])[:3])
            divergences.append(f"- contested: **{a['src_label']} -> {a['dst_label']}** ({a['papers']} papers, {a['origin']}){': ' + quals if quals else ''}")

    lines = [
        "# BFO module v2 review", "",
        f"- sources: parts {len(sources['parts'].ids)} clusters, process phrases {len(sources['process_phrases'].ids)}, participants {len(sources['participants'].ids)} (after merges)",
        f"- domain-entity clusters: {len(canonical)}; canonical terms: {len(terms)}; aligned across sources: {len(canonical) - len(terms)}",
        f"- axioms: {len(process_axioms)} from process items, {len(conditional_axioms)} from conditionals, {len(participant_axioms)} participant restrictions; evidence only: {len(evidence_only)}",
        f"- proposed parent classes from the hierarchy: {len(parent_classes)}",
        f"- divergences: {len(divergences)}", "",
        "## Divergences", "", *(divergences or ["- none"]), "",
        "## Axioms from process items", "", "| papers | claims | direction | contested | axiom |", "|---|---|---|---|---|",
        *(f"| {a['papers']} | {a['n']} | {a['direction']} | {'yes' if a['contested'] else ''} | {a['manchester']} |" for a in sorted(process_axioms, key=lambda a: -a['papers'])),
        "", "## Participant restrictions", "", *(f"- {t}" for t in participant_axioms),
        "", "## Axioms from conditionals", "", "| papers | claims | direction | contested | qualifiers | axiom |", "|---|---|---|---|---|---|",
        *(f"| {a['papers']} | {a['n']} | {a.get('direction', 'none')} | {'yes' if a.get('contested') else ''} | {'; '.join(a.get('qualifiers', [])[:3])} | {a['manchester']} |" for a in sorted(conditional_axioms, key=lambda a: -a['papers'])),
        "", "## Proposed parents", "", *(f"- **{l}** ({c}): {', '.join(ch)}" for l, c, ch in parent_classes),
        "", "## Evidence only", "", "| papers | claims | origin | source | target | reason |", "|---|---|---|---|---|---|",
        *(f"| {a['papers']} | {a['n']} | {a['origin']} | {a['src_label']} | {a['dst_label']} | {a.get('enforced') or a.get('rationale', '')[:120]} |" for a in sorted(evidence_only, key=lambda a: -a['papers'])[:80]),
        "", "## Classes", "", "| term | source | category | label | papers | aliases |", "|---|---|---|---|---|---|",
        *(f"| {str(iri[t]).split('/')[-1]} | {t[0]} | {meta[t]['category']} | {meta[t]['label']} | {meta[t]['papers']} | {'; '.join(proposals[n2][c2]['label'] for n2, c2 in aliases[t])} |" for t in sorted(terms, key=lambda t: -meta[t]['papers'])),
    ]
    (out / "review.md").write_text("\n".join(lines))
    print("\n".join(lines[:8]))
    print(f"\nwrote {out}/terms.ttl, terms.owl, evidence.ttl, review.md")


if __name__ == "__main__":
    main()
