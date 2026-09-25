# /// script
# requires-python = ">=3.12"
# dependencies = ["openai>=1.40", "numpy", "pandas", "pyarrow", "scikit-learn>=1.4", "rdflib>=7"]
# ///
"""One-off: propose a BFO 2020 module from clusters and their relations.

Generic by construction: the only inputs are clusters of text fragments with
their members, and edges between clusters with support counts and example
sentences. Nothing about the corpus's subject is in the code or the prompts;
the vocabulary comes from the data. The output imports BFO 2020 core and
nothing else.

Two model calls per proposal:

- per cluster, *categorise*: is this a kind of entity in reality at all, and
  if so which BFO category, with a label, an Aristotelian definition and a
  one-line rationale;
- per edge, *axiomatise*: which pattern the claim shape supports (subclass,
  disposition, quality attribution, participation, occurs-in, or evidence
  only), enforced afterwards against the two categories so the model cannot
  produce a restriction BFO does not allow.

    OPENAI_API_KEY=... uv run scripts/term_clustering/bfo_proposal.py --min-papers-edge 3

Writes into ``<dir>/bfo/``: ``proposal_classes.jsonl``, ``proposal_axioms.jsonl``,
``terms.ttl`` (classes, restrictions, axiom annotations), ``evidence.ttl``
(the sentences behind them) and ``review.md`` for the ontologist.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from rdflib import BNode, Graph, Literal, Namespace, RDF, RDFS, OWL, XSD, URIRef
from rdflib.collection import Collection

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cluster import central_examples, class_tfidf, normalise  # noqa: E402

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "storage/spikes/term_clustering"
OBO = Namespace("http://purl.obolibrary.org/obo/")
BFO_IRI = "http://purl.obolibrary.org/obo/bfo/2020/bfo-core.ttl"
DEFINITION = OBO.IAO_0000115

# BFO 2020 categories a proposal may pick, and the side of the top split each is on.
CATEGORIES = {
    "material entity": ("BFO_0000040", "continuant"),
    "object": ("BFO_0000030", "continuant"),
    "object aggregate": ("BFO_0000027", "continuant"),
    "site": ("BFO_0000029", "continuant"),
    "quality": ("BFO_0000019", "continuant"),
    "disposition": ("BFO_0000016", "continuant"),
    "role": ("BFO_0000023", "continuant"),
    "function": ("BFO_0000034", "continuant"),
    "generically dependent continuant": ("BFO_0000031", "continuant"),
    "process": ("BFO_0000015", "occurrent"),
    "process boundary": ("BFO_0000035", "occurrent"),
}
INDEPENDENT = {"material entity", "object", "object aggregate", "site"}
DEPENDENT = {"quality", "disposition", "role", "function"}
PROCESSES = {"process", "process boundary"}
REL = {
    "bearer of": OBO.BFO_0000196,
    "inheres in": OBO.BFO_0000197,
    "has realization": OBO.BFO_0000054,
    "participates in": OBO.BFO_0000056,
    "has participant": OBO.BFO_0000057,
    "occurs in": OBO.BFO_0000066,
}
PATTERNS = ("subclass", "equivalent", "disposition", "quality_attribution", "participation", "occurs_in", "evidence_only")

CLASS_SYSTEM = """You are an ontologist applying Basic Formal Ontology 2020 (BFO) to a cluster of short text fragments.
Every fragment in the cluster was produced by splitting "If X, then Y." claims extracted from research papers; the cluster groups fragments that say a similar thing. Your job is to decide whether the cluster names a kind of entity in reality, and if so what kind under BFO.

Decide in this order:
1. kind: what the cluster is about.
   - domain_entity: a kind of thing in the world (an organism, a group of people, a bodily or mental process, a quality, a tendency, a role, a place).
   - measurement_or_method: scales, instruments, statistics, study designs, analysis choices.
   - comparative_or_statistical: a comparison or a change in degree ("higher than", "increases") rather than a kind of thing.
   - mixed: the members name more than one kind of thing.
   - other: none of the above.
2. bfo_category, only for domain_entity, using BFO's questions:
   - Does it unfold in time? -> process (or process boundary if instantaneous).
   - Else does it depend on a bearer? A property the bearer always exhibits -> quality. A tendency realized only under conditions -> disposition. A socially assigned status -> role. A designed or evolved purpose -> function.
   - Else is it information -> generically dependent continuant.
   - Else it exists on its own: a single organism or thing -> object; a group -> object aggregate; a bounded space -> site; otherwise -> material entity.
3. label: a singular lowercase noun phrase naming the kind, at most six words, no hedges, no pronouns.
4. definition: one sentence of the form "A <genus> that <differentia>." where the genus is the BFO category or a more specific kind the members imply.
5. rationale: one sentence naming the BFO question that decided the category.
6. confidence: 0 to 1.
Be strict. A cluster of comparative statements or of measurement talk is not a domain entity even if it mentions one."""

# Variant: claims about a change in degree are modelled the way OBO ontologies do,
# as a process in which a bearer's quality changes, rather than set aside.
QUALITY_CHANGE_NOTE = """

Exception to the strictness above: a cluster whose members describe a change in the degree of a quality ("increase in X", "higher X", "lower X", "X decreases") IS a domain_entity, of category process: the process in which a bearer's quality X changes. Label it "increase in <quality>", "decrease in <quality>", or "change in <quality>" when the members go both ways, and define it as "A process in which a bearer's <quality> increases/decreases." Keep comparative_or_statistical only for correlations, group comparisons ("compared with younger adults") and statistical statements with no single changing quality."""

EDGE_SYSTEM = """You are an ontologist turning an empirical relation between two BFO classes into an OWL axiom, or refusing to.
The relation comes from "If X, then Y." claims whose X fell in the source class and whose Y fell in the target class. Most such claims are tendencies, not universals: a universally quantified restriction that says every X does Y is false for them. BFO's disposition is the construct for tendencies: bearers of the source have a disposition that is realized in the target process; every bearer has the disposition, not every disposition is realized.

Pick exactly one pattern:
- subclass: the claims say the source is a kind of the target (same BFO category required).
- equivalent: the claims define the source as exactly the target (same category, definitional).
- disposition: the target is a process and the claims say the source tends to lead to it. Direction says what the claims assert about THE TARGET AS LABELLED: "increases" if the target process becomes more likely, "decreases" if less likely, "none" if the claims only say it happens or disagree. Judge it against the target's own label: if the target is "decrease in loneliness" and the claims say loneliness goes down, the direction is "increases", because that decrease becomes more likely.
- quality_attribution: the target is a quality and the claims say the source bears it.
- participation: the target is a process and the claims say the source takes part in it, as a matter of definition rather than tendency.
- occurs_in: the source is a process and the target is a site or material entity it happens in.
- evidence_only: none of the above holds, the claims are comparative or statistical, the claims disagree with each other, or the categories do not fit any pattern.

Also report contested = true if the example sentences disagree about direction or content, and a one-sentence rationale. Never invent a pattern the categories cannot support; prefer evidence_only over a forced axiom."""

CLASS_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "kind": {"type": "string", "enum": ["domain_entity", "measurement_or_method", "comparative_or_statistical", "mixed", "other"]},
        "bfo_category": {"type": "string", "enum": list(CATEGORIES) + ["none"]},
        "label": {"type": "string"},
        "definition": {"type": "string"},
        "rationale": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["kind", "bfo_category", "label", "definition", "rationale", "confidence"],
}
EDGE_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "pattern": {"type": "string", "enum": list(PATTERNS)},
        "direction": {"type": "string", "enum": ["increases", "decreases", "none"]},
        "contested": {"type": "boolean"},
        "rationale": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["pattern", "direction", "contested", "rationale", "confidence"],
}


def ask(client, model: str, system: str, user: str, schema: dict, name: str) -> dict:
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
        temperature=0,
    )
    return json.loads(response.choices[0].message.content)


def load_clusters(directory: Path, seed: int) -> tuple[pd.DataFrame, list[dict], dict[str, int]]:
    parts = pd.read_parquet(directory / "parts.parquet")
    unit = normalise(np.load(directory / "parts.vectors.npy"))
    assigned = pd.read_parquet(directory / "assignments_parts_mcs15_umap10.parquet")
    labels = assigned.set_index("id").loc[parts["key"], "cluster"].to_numpy()
    cond = pd.read_parquet(directory / "conditionals.parquet")
    key_to_cluster = dict(zip(parts["key"], labels.tolist()))
    papers: dict[int, set] = {}
    for a, c, p in zip(cond["antecedent_key"], cond["consequent_key"], cond["paper_id"]):
        for k in (key_to_cluster[a], key_to_cluster[c]):
            if k >= 0:
                papers.setdefault(k, set()).add(p)
    keywords = class_tfidf(parts["text"].tolist(), labels)
    rng = np.random.default_rng(seed)
    clusters = []
    for label in sorted(set(labels) - {-1}):
        members = np.flatnonzero(labels == label)
        central = central_examples(unit, labels, label, 8)
        others = rng.choice([i for i in members if i not in set(central)], size=min(6, max(0, len(members) - len(central))), replace=False) if len(members) > len(central) else []
        clusters.append({
            "cluster": int(label), "size": int(len(members)), "papers": len(papers.get(label, ())),
            "keywords": keywords.get(label, []),
            "central": [parts["text"][i] for i in central], "others": [parts["text"][i] for i in others],
            "as_antecedent": int(parts["as_antecedent"].to_numpy()[members].sum()),
            "as_consequent": int(parts["as_consequent"].to_numpy()[members].sum()),
        })
    return cond, clusters, key_to_cluster


def categorise(client, model, c: dict, system: str = CLASS_SYSTEM) -> dict:
    user = (
        f"Cluster of {c['size']} fragments from {c['papers']} papers. Members appear {c['as_antecedent']} times as the X of a claim and {c['as_consequent']} times as the Y.\n"
        f"Distinctive words: {', '.join(c['keywords'])}\n\nMost central members:\n" + "\n".join(f"- {t}" for t in c["central"])
        + ("\n\nOther members:\n" + "\n".join(f"- {t}" for t in c["others"]) if c["others"] else "")
    )
    return c | ask(client, model, system, user, CLASS_SCHEMA, "categorisation")


def axiomatise(client, model, edge: dict, src: dict, dst: dict, examples: list[str]) -> dict:
    user = (
        f"Source class: '{src['label']}' ({src['bfo_category']}). Definition: {src['definition']}\n"
        f"Target class: '{dst['label']}' ({dst['bfo_category']}). Definition: {dst['definition']}\n"
        f"Support: {edge['n']} claims from {edge['papers']} distinct papers.\n\nExample claims (X fell in the source, Y in the target):\n"
        + "\n".join(f"- {t}" for t in examples)
    )
    return ask(client, model, EDGE_SYSTEM, user, EDGE_SCHEMA, "axiomatisation")


def enforce(pattern: str, src_cat: str, dst_cat: str, wrap_quality: bool = False,
            direction: str = "none", dst_label: str = "") -> tuple[str, str]:
    """The pattern the categories actually allow, and why it changed if it did.

    With ``wrap_quality`` a disposition may target a quality: the realization is
    then the process in which a participant comes to bear that quality.

    A disposition is realized in its target, so it can only make the target
    more likely. "Decreases" is therefore acceptable only when the target
    class itself is the decrease ("decrease in loneliness"); otherwise the
    claim needs a counterpart process class that nobody proposed, and it stays
    evidence."""
    if pattern in ("subclass", "equivalent") and src_cat != dst_cat:
        return "evidence_only", f"{pattern} needs one category, got {src_cat} and {dst_cat}"
    if pattern == "disposition" and dst_cat not in PROCESSES and not (wrap_quality and dst_cat == "quality"):
        return "evidence_only", f"disposition needs a process target, got {dst_cat}"
    if pattern == "disposition" and direction == "decreases":
        label = dst_label.lower()
        if label.startswith(("decrease in", "reduction in", "reduced ", "loss of")):
            return pattern, ""
        if label.startswith(("increase in", "increased ")):
            return "evidence_only", "claims say the target becomes less likely but the target is an increase; direction conflicts with the target class"
        return "evidence_only", "a disposition cannot make its realization less likely; 'decreases' needs a counterpart process class (e.g. 'decrease in ...')"
    if pattern == "quality_attribution" and (dst_cat != "quality" or src_cat not in INDEPENDENT):
        return "evidence_only", f"quality attribution needs an independent continuant bearing a quality, got {src_cat} -> {dst_cat}"
    if pattern == "participation" and (dst_cat not in PROCESSES or src_cat not in INDEPENDENT):
        return "evidence_only", f"participation needs an independent continuant and a process, got {src_cat} -> {dst_cat}"
    if pattern == "occurs_in" and (src_cat not in PROCESSES or dst_cat not in INDEPENDENT):
        return "evidence_only", f"occurs in needs a process in an independent continuant, got {src_cat} -> {dst_cat}"
    return pattern, ""


def restriction(g: Graph, prop: URIRef, filler, kind: str = "some") -> BNode:
    node = BNode()
    g.add((node, RDF.type, OWL.Restriction))
    g.add((node, OWL.onProperty, prop))
    g.add((node, OWL.someValuesFrom if kind == "some" else OWL.allValuesFrom, filler))
    return node


def intersection(g: Graph, *members) -> BNode:
    node, lst = BNode(), BNode()
    g.add((node, RDF.type, OWL.Class))
    Collection(g, lst, list(members))
    g.add((node, OWL.intersectionOf, lst))
    return node


def build_axiom(g: Graph, T: Namespace, ax: dict, src: URIRef, dst: URIRef, src_cat: str) -> tuple[URIRef, URIRef, object, str]:
    """Add the axiom to ``g``; return (subject, predicate, object, manchester rendering)."""
    p = ax["pattern"]
    if p == "subclass":
        g.add((src, RDFS.subClassOf, dst)); return src, RDFS.subClassOf, dst, f"{ax['src_label']} SubClassOf {ax['dst_label']}"
    if p == "equivalent":
        g.add((src, OWL.equivalentClass, dst)); return src, OWL.equivalentClass, dst, f"{ax['src_label']} EquivalentTo {ax['dst_label']}"
    if p == "disposition":
        # Plain BFO: a disposition realized only in the target process. The
        # empirical direction is an annotation on the axiom, never a class.
        disp, disp_label = OBO.BFO_0000016, "disposition"
        if ax["dst_category"] == "quality":
            # A quality is not a realization; the process in which a participant comes to bear it is.
            target = intersection(g, OBO.BFO_0000015, restriction(g, REL["has participant"], restriction(g, REL["bearer of"], dst)))
            target_text = f"(process and 'has participant' some ('bearer of' some '{ax['dst_label']}'))"
        else:
            target, target_text = dst, f"'{ax['dst_label']}'"
        realizable = intersection(g, disp, restriction(g, REL["has realization"], target, "only"))
        inner = f"({disp_label} and 'has realization' only {target_text})"
        if src_cat in INDEPENDENT:
            filler, text = restriction(g, REL["bearer of"], realizable), f"'bearer of' some {inner}"
        elif src_cat in PROCESSES:
            filler, text = restriction(g, REL["has participant"], restriction(g, REL["bearer of"], realizable)), f"'has participant' some ('bearer of' some {inner})"
        else:
            filler, text = restriction(g, REL["inheres in"], restriction(g, REL["bearer of"], realizable)), f"'inheres in' some ('bearer of' some {inner})"
        g.add((src, RDFS.subClassOf, filler)); return src, RDFS.subClassOf, filler, f"'{ax['src_label']}' SubClassOf {text}"
    if p == "quality_attribution":
        filler = restriction(g, REL["bearer of"], dst); g.add((src, RDFS.subClassOf, filler))
        return src, RDFS.subClassOf, filler, f"'{ax['src_label']}' SubClassOf 'bearer of' some '{ax['dst_label']}'"
    if p == "participation":
        filler = restriction(g, REL["participates in"], dst); g.add((src, RDFS.subClassOf, filler))
        return src, RDFS.subClassOf, filler, f"'{ax['src_label']}' SubClassOf 'participates in' some '{ax['dst_label']}'"
    if p == "occurs_in":
        filler = restriction(g, REL["occurs in"], dst); g.add((src, RDFS.subClassOf, filler))
        return src, RDFS.subClassOf, filler, f"'{ax['src_label']}' SubClassOf 'occurs in' some '{ax['dst_label']}'"
    raise ValueError(p)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--base", default="http://purl.example.org/terms/", help="IRI base of the generated module")
    parser.add_argument("--model", default="gpt-4.1")
    parser.add_argument("--min-papers-edge", type=int, default=3)
    parser.add_argument("--max-clusters", type=int, default=0, help="0 = all")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out-name", default="bfo", help="output directory name under --dir")
    parser.add_argument("--quality-change-as-process", action="store_true",
                        help="model 'increase in X' clusters as processes and let dispositions target qualities")
    args = parser.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set")
    from openai import OpenAI

    client = OpenAI()
    out = args.dir / args.out_name
    out.mkdir(exist_ok=True)
    class_system = CLASS_SYSTEM + (QUALITY_CHANGE_NOTE if args.quality_change_as_process else "")

    cond, clusters, key_to_cluster = load_clusters(args.dir, args.seed)
    if args.max_clusters:
        clusters = clusters[: args.max_clusters]
    print(f"categorising {len(clusters)} clusters with {args.model}", file=sys.stderr)
    with ThreadPoolExecutor(args.workers) as pool:
        proposals = list(pool.map(lambda c: categorise(client, args.model, c, class_system), clusters))
    by_id = {p["cluster"]: p for p in proposals}
    with open(out / "proposal_classes.jsonl", "w") as f:
        for p in proposals:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    edges = pd.read_parquet(args.dir / "edges_parts_mcs15_umap10.parquet")
    edges = edges[(edges.src != edges.dst) & (edges.papers >= args.min_papers_edge) & edges.src.isin(by_id) & edges.dst.isin(by_id)]
    edges = edges.sort_values(["papers", "n"], ascending=False)
    src_c = cond["antecedent_key"].map(key_to_cluster)
    dst_c = cond["consequent_key"].map(key_to_cluster)

    def one_edge(row):
        src, dst = by_id[int(row.src)], by_id[int(row.dst)]
        e = {"src": int(row.src), "dst": int(row.dst), "n": int(row.n), "papers": int(row.papers)}
        sel = cond[(src_c == row.src) & (dst_c == row.dst)]
        examples = sel.drop_duplicates("text")["text"].head(8).tolist()
        e |= {"src_label": src["label"], "dst_label": dst["label"], "src_category": src["bfo_category"], "dst_category": dst["bfo_category"],
              "examples": examples, "item_ids": sel["item_id"].head(8).tolist()}
        if src["kind"] != "domain_entity" or dst["kind"] != "domain_entity":
            return e | {"pattern": "evidence_only", "direction": "none", "contested": False, "confidence": 1.0,
                        "rationale": "one end is not a domain entity", "enforced": "", "proposed_pattern": "evidence_only"}
        a = axiomatise(client, args.model, e, src, dst, examples)
        pattern, note = enforce(a["pattern"], src["bfo_category"], dst["bfo_category"], args.quality_change_as_process,
                                a["direction"], dst["label"])
        return e | a | {"proposed_pattern": a["pattern"], "pattern": pattern, "enforced": note}

    print(f"axiomatising {len(edges)} edges with >= {args.min_papers_edge} papers", file=sys.stderr)
    with ThreadPoolExecutor(args.workers) as pool:
        axioms = list(pool.map(one_edge, list(edges.itertuples())))

    # ---- the module ----
    T = Namespace(args.base)
    g = Graph()
    g.bind("terms", T); g.bind("obo", OBO); g.bind("owl", OWL)
    onto = URIRef(args.base.rstrip("/#"))
    g.add((onto, RDF.type, OWL.Ontology)); g.add((onto, OWL.imports, URIRef(BFO_IRI)))
    g.add((onto, RDFS.comment, Literal("Generated proposal: classes from clusters of claim fragments, restrictions from relations between clusters. Every class and axiom is a proposal until accepted.")))
    # Only BFO classes and relations appear in class expressions; everything the
    # corpus says about strength, direction or disagreement is an annotation.
    for prop, label in (("clusterId", "cluster id"), ("supportPapers", "support: distinct papers"), ("supportClaims", "support: claims"),
                        ("proposalRationale", "proposal rationale"), ("proposalConfidence", "proposal confidence"), ("evidence", "evidence sentence"),
                        ("claimDirection", "claim direction: what the claims say happens to the target (increases, decreases, none)"),
                        ("contested", "contested: the supporting claims disagree")):
        g.add((T[prop], RDF.type, OWL.AnnotationProperty)); g.add((T[prop], RDFS.label, Literal(label)))

    iri = {}
    for p in proposals:
        if p["kind"] != "domain_entity" or p["bfo_category"] not in CATEGORIES:
            continue
        c = T[f"T{p['cluster']:05d}"]
        iri[p["cluster"]] = c
        g.add((c, RDF.type, OWL.Class)); g.add((c, RDFS.subClassOf, OBO[CATEGORIES[p["bfo_category"]][0]]))
        g.add((c, RDFS.label, Literal(p["label"], lang="en"))); g.add((c, DEFINITION, Literal(p["definition"], lang="en")))
        g.add((c, T.clusterId, Literal(p["cluster"]))); g.add((c, T.supportPapers, Literal(p["papers"])))
        g.add((c, T.proposalRationale, Literal(p["rationale"]))); g.add((c, T.proposalConfidence, Literal(p["confidence"], datatype=XSD.decimal)))

    ev = Graph(); ev.bind("terms", T); ev.bind("obo", OBO)
    ev.add((URIRef(args.base.rstrip("/#") + "/evidence"), RDF.type, OWL.Ontology)); ev.add((URIRef(args.base.rstrip("/#") + "/evidence"), OWL.imports, onto))
    built = 0
    for a in axioms:
        if a["pattern"] == "evidence_only":
            continue
        s, pred, o, text = build_axiom(g, T, a, iri[a["src"]], iri[a["dst"]], a["src_category"])
        a["manchester"] = text
        ann = BNode()
        g.add((ann, RDF.type, OWL.Axiom)); g.add((ann, OWL.annotatedSource, s)); g.add((ann, OWL.annotatedProperty, pred)); g.add((ann, OWL.annotatedTarget, o))
        g.add((ann, T.supportPapers, Literal(a["papers"]))); g.add((ann, T.supportClaims, Literal(a["n"])))
        g.add((ann, T.proposalRationale, Literal(a["rationale"]))); g.add((ann, T.proposalConfidence, Literal(a["confidence"], datatype=XSD.decimal)))
        g.add((ann, T.claimDirection, Literal(a.get("direction", "none"))))
        if a.get("contested"):
            g.add((ann, T.contested, Literal(True)))
        for item_id, text_ in zip(a["item_ids"], a["examples"]):
            sent = T[f"S{item_id[:16]}"]
            g.add((ann, T.evidence, sent))
            ev.add((sent, RDFS.label, Literal(text_)))
        built += 1
    g.serialize(out / "terms.ttl", format="turtle")
    ev.serialize(out / "evidence.ttl", format="turtle")
    # Written after the module so each row carries the axiom as rendered.
    with open(out / "proposal_axioms.jsonl", "w") as f:
        for a in axioms:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")

    # ---- review sheet ----
    kinds = pd.Series([p["kind"] for p in proposals]).value_counts().to_dict()
    cats = pd.Series([p["bfo_category"] for p in proposals if p["kind"] == "domain_entity"]).value_counts().to_dict()
    pats = pd.Series([a["pattern"] for a in axioms]).value_counts().to_dict()
    proposed = pd.Series([a["proposed_pattern"] for a in axioms]).value_counts().to_dict()
    lines = [
        "# BFO proposal review", "",
        f"- clusters categorised: {len(proposals)}; kinds: {kinds}",
        f"- BFO categories among domain entities: {cats}",
        f"- classes written: {len(iri)}; edges considered (>= {args.min_papers_edge} papers): {len(axioms)}; axioms written: {built}",
        f"- patterns as proposed by the model: {proposed}", f"- patterns after category enforcement: {pats}",
        f"- enforcement changed {sum(1 for a in axioms if a['enforced'])} proposals", "",
        "## Classes (largest first; accept / reject / fix)", "",
        "| cluster | kind | BFO category | label | definition | rationale | conf | halves | papers | decision |", "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for p in sorted(proposals, key=lambda p: -p["size"]):
        lines.append(f"| C{p['cluster']} | {p['kind']} | {p['bfo_category']} | {p['label']} | {p['definition']} | {p['rationale']} | {p['confidence']:.2f} | {p['size']} | {p['papers']} | |")
    lines += ["", "## Axioms (strongest support first; accept / reject / fix)", "", "| papers | claims | pattern | axiom | rationale | contested | enforcement note | example | decision |", "|---|---|---|---|---|---|---|---|---|"]
    for a in axioms:
        ax_text = a.get("manchester") or f"evidence only ('{a['src_label']}' -> '{a['dst_label']}')"
        lines.append(f"| {a['papers']} | {a['n']} | {a['pattern']} | {ax_text} | {a['rationale']} | {'yes' if a.get('contested') else ''} | {a['enforced']} | {a['examples'][0] if a['examples'] else ''} | |")
    (out / "review.md").write_text("\n".join(lines))
    print("\n".join(lines[:8]))
    print(f"\nwrote {out / 'terms.ttl'}, {out / 'evidence.ttl'}, {out / 'review.md'}")


if __name__ == "__main__":
    main()
