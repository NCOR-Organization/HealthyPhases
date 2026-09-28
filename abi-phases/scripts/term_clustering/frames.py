# /// script
# requires-python = ">=3.12"
# dependencies = ["openai>=1.40", "numpy", "pandas", "pyarrow", "scikit-learn>=1.4", "umap-learn>=0.5.6", "rdflib>=7"]
# ///
"""Text -> frames -> clusters per role -> BFO classes and restrictions, in one file.

The pipeline in one place so it can be read top to bottom and tested on a
few papers before it runs on hundreds. Stages, each cached under
``<dir>/frames/<run>/`` and skipped when its output exists:

1. extract    chunks -> claims. One prompt. A claim is a relation between two
              frames; a frame has one slot per BFO bucket: process, participants,
              qualities (of a participant), realizables (of a participant), when,
              where, information (how we know). The prompt decides roles only,
              never types.
2. flatten    claims -> one row per slot phrase, tagged with its role.
3. embed      distinct (role, phrase) -> vectors.
4. cluster    per role: UMAP + HDBSCAN (guarded for small samples). Identity is
              decided here: phrases that land together are one concept.
5. categorise once per cluster: the BFO questions, with the role as a prior the
              model may override. Types are decided here.
6. module     classes from clusters; restrictions from the frame structure
              (process has participant, participant bears quality, ...); qualified
              frames become defined subclasses; relations between frames become
              disposition axioms with voted direction and a contested flag.
7. review     slot fill rates, clusters per role, classes per bucket, axioms, gaps.

    OPENAI_API_KEY=... uv run scripts/term_clustering/frames.py --papers 3
    uv run scripts/term_clustering/bfo_check.py --dir storage/spikes/term_clustering/frames/p3

Everything the corpus says about direction, support and disagreement is an
annotation; class expressions use only BFO classes and relations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from rdflib import BNode, Graph, Literal, Namespace, RDF, RDFS, OWL, XSD, URIRef
from rdflib.collection import Collection
from sklearn.cluster import HDBSCAN
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, CountVectorizer

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "storage/spikes/term_clustering"
OBO = Namespace("http://purl.obolibrary.org/obo/")
BFO_IRI = "http://purl.obolibrary.org/obo/bfo/2020/bfo-core.ttl"
DEFINITION = OBO.IAO_0000115
EMBED_MODEL, EMBED_DIM = "text-embedding-3-large", 3072

ROLES = ("process", "participant", "quality", "realizable", "when", "where", "information")
# The bucket each role usually lands in. A prior for the categoriser, not a rule.
ROLE_BUCKET = {
    "process": "process", "participant": "material entity", "quality": "quality", "realizable": "disposition",
    "when": "temporal region", "where": "site", "information": "generically dependent continuant",
}
CATEGORIES = {
    "material entity": "BFO_0000040", "object": "BFO_0000030", "object aggregate": "BFO_0000027", "site": "BFO_0000029",
    "quality": "BFO_0000019", "disposition": "BFO_0000016", "role": "BFO_0000023", "function": "BFO_0000034",
    "generically dependent continuant": "BFO_0000031", "process": "BFO_0000015", "process boundary": "BFO_0000035",
    "temporal region": "BFO_0000008", "spatial region": "BFO_0000006",
}
INDEPENDENT = {"material entity", "object", "object aggregate", "site"}
DEPENDENT = {"quality", "disposition", "role", "function"}
PROCESSES = {"process", "process boundary"}
REL = {
    "bearer of": OBO.BFO_0000196, "inheres in": OBO.BFO_0000197, "has realization": OBO.BFO_0000054,
    "participates in": OBO.BFO_0000056, "has participant": OBO.BFO_0000057, "occurs in": OBO.BFO_0000066,
}

# ============================================================== 1. extract

EXTRACT_SYSTEM = """You extract the general claims a research passage supports and lay each one out as a relation between two frames.

A frame describes one process and everything the passage says about it, one slot per kind of thing:
- process: what happens, as a verb phrase or -ing nominal ("spending time alone", "experiencing loneliness"). Required.
- participants: who or what takes part, as noun phrases naming kinds, never pronouns ("adolescents", "older adults living alone", "communication technology"). Repeat the noun phrase rather than writing "they".
- qualities: properties a participant has in this claim, each tied to its participant ({"of": "adolescents", "quality": "high autonomy"}). Only what the passage states.
- realizables: tendencies, roles or functions a participant has in this claim, tied to its participant ({"of": "adolescents", "realizable": "preference for solitude"}).
- when: the time or life stage the claim is restricted to, if stated ("in old age", "during the first week"); else "".
- where: the place or setting, if stated ("at home", "in the classroom"); else "".
- information: how the passage knows this, if stated: the instrument, measure or design ("self-report", "cortisol sampling", "longitudinal cohort"); else "".

A claim relates an antecedent frame to a consequent frame:
- relation.kind: "tends_to" when the antecedent makes the consequent more or less likely (the usual case); "causes" only when the passage asserts causation outright; "is_a" when the antecedent process is a kind of the consequent process; "defines" when the passage defines the antecedent as the consequent; "co_occurs" when they are merely associated with no direction.
- relation.direction: what happens to the consequent process as you named it: "increases" (more likely, more, higher), "decreases" (less likely, less, lower), "no_effect" (the passage says it makes no difference), "none" (nothing about likelihood or degree).
- When a claim says the antecedent lowers or raises something, name the consequent process as the change itself ("decrease in loneliness", "increase in positive affect") and set direction to "increases": the change becomes more likely. Use "decreases" only when the consequent is a process that becomes less likely as such.
- evidence: a short verbatim quote (under 200 characters) from the passage that supports the claim.

Rules: rephrase as general propositions, never copy sentences; no study metadata inside frames except in the information slot; no pronouns anywhere; do not invent what the passage does not say; 0 to 8 claims per passage; an empty list if the passage makes no general claim."""

FRAME_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "process": {"type": "string"},
        "participants": {"type": "array", "items": {"type": "string"}},
        "qualities": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                 "properties": {"of": {"type": "string"}, "quality": {"type": "string"}}, "required": ["of", "quality"]}},
        "realizables": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                   "properties": {"of": {"type": "string"}, "realizable": {"type": "string"}}, "required": ["of", "realizable"]}},
        "when": {"type": "string"}, "where": {"type": "string"}, "information": {"type": "string"},
    },
    "required": ["process", "participants", "qualities", "realizables", "when", "where", "information"],
}
CLAIMS_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"claims": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "antecedent": FRAME_SCHEMA,
            "relation": {"type": "object", "additionalProperties": False,
                         "properties": {"kind": {"type": "string", "enum": ["tends_to", "causes", "is_a", "defines", "co_occurs"]},
                                        "direction": {"type": "string", "enum": ["increases", "decreases", "no_effect", "none"]}},
                         "required": ["kind", "direction"]},
            "consequent": FRAME_SCHEMA,
            "evidence": {"type": "string"},
        },
        "required": ["antecedent", "relation", "consequent", "evidence"],
    }}},
    "required": ["claims"],
}


def ask_json(client, model: str, system: str, user: str, schema: dict, name: str) -> dict:
    response = client.chat.completions.create(
        model=model, temperature=0,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}},
    )
    return json.loads(response.choices[0].message.content)


def extract(client, model: str, chunks: pd.DataFrame, workers: int) -> list[dict]:
    def one(row):
        out = ask_json(client, model, EXTRACT_SYSTEM, f"Passage:\n{row.text}", CLAIMS_SCHEMA, "claims")
        claims = []
        for i, c in enumerate(out["claims"]):
            claim_id = hashlib.sha256(f"{row.chunk_id}|{i}|{c['antecedent']['process']}|{c['consequent']['process']}".encode()).hexdigest()[:16]
            claims.append({"claim_id": claim_id, "paper_id": row.paper_id, "chunk_id": row.chunk_id, **c})
        return claims

    with ThreadPoolExecutor(workers) as pool:
        return [c for claims in pool.map(one, list(chunks.itertuples())) for c in claims]


CHANGE_PREFIXES = ("decrease in", "reduction in", "reduced", "loss of", "lower", "decline in", "fewer")


def normalise_direction(claim: dict) -> dict:
    """A tendency can only make its realization more likely, so "X decreases Y"
    is written as "X makes 'decrease in Y' more likely". The prompt asks for
    this; when the model keeps "decreases" on a plain target, do it here."""
    rel, cons = claim["relation"], claim["consequent"]
    if rel["direction"] == "decreases" and not cons["process"].lower().startswith(CHANGE_PREFIXES):
        cons["process"] = f"decrease in {cons['process']}"
        rel["direction"] = "increases"
    return claim


# ============================================================== 2. flatten

IRREGULAR_PLURALS ={"children": "child", "people": "person", "men": "man", "women": "woman", "adolescents": "adolescent"}


def singular(word: str) -> str:
    """Light English number folding for the last word of a phrase; deliberately conservative."""
    if word in IRREGULAR_PLURALS:
        return IRREGULAR_PLURALS[word]
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is", "as", "os", "ness")):
        return word[:-1]
    return word


def normalize_key(text: str) -> str:
    """Identity key for a phrase: case, spacing and trailing period folded, and the
    head noun's number folded so "parents" and "parent" share one vector."""
    words = re.sub(r"\s+", " ", text).strip().rstrip(".").casefold().split(" ")
    if words:
        words[-1] = singular(words[-1])
    return " ".join(words)


def flatten(claims: list[dict]) -> pd.DataFrame:
    """One row per slot phrase: which claim, which side, which role, tied to which participant."""
    rows = []
    for c in claims:
        for side in ("antecedent", "consequent"):
            f = c[side]

            def add(role, text, of=""):
                if text and text.strip():
                    rows.append({"claim_id": c["claim_id"], "paper_id": c["paper_id"], "chunk_id": c["chunk_id"], "side": side,
                                 "role": role, "text": text.strip(), "key": normalize_key(text), "of": normalize_key(of) if of else ""})

            add("process", f["process"])
            for p in f["participants"]:
                add("participant", p)
            for q in f["qualities"]:
                add("quality", q["quality"], q["of"])
            for r in f["realizables"]:
                add("realizable", r["realizable"], r["of"])
            add("when", f["when"]); add("where", f["where"]); add("information", f["information"])
    return pd.DataFrame(rows)


# ============================================================== 3. embed

def embed(client, phrases: list[str]) -> np.ndarray:
    out = np.empty((len(phrases), EMBED_DIM), dtype=np.float32)
    for start in range(0, len(phrases), 256):
        batch = phrases[start:start + 256]
        response = client.embeddings.create(model=EMBED_MODEL, input=batch, dimensions=EMBED_DIM)
        for i, item in enumerate(response.data):
            out[start + i] = item.embedding
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.where(norms == 0, 1, norms)


# ============================================================== 4. cluster

def cluster_role(unit: np.ndarray, mcs: int, seed: int, merge_distance: float = 0.15, density_from: int = 300) -> np.ndarray:
    """Labels per phrase, -1 for noise.

    Density (UMAP + HDBSCAN) needs a few hundred points to mean anything; below
    that it either finds nothing or folds everything together. Small roles are
    therefore merged by paraphrase instead: average-linkage agglomeration with a
    cosine-distance cut, which keeps distinct concepts apart and never invents
    density. Tiny roles keep every distinct phrase on its own."""
    n = len(unit)
    if n == 0:
        return np.asarray([], dtype=int)
    if n < 8:
        return np.arange(n)
    if n < density_from:
        from sklearn.cluster import AgglomerativeClustering

        model = AgglomerativeClustering(n_clusters=None, distance_threshold=merge_distance, metric="cosine", linkage="average")
        return model.fit(unit).labels_
    import umap

    reduced = umap.UMAP(n_components=min(10, n - 2), n_neighbors=min(15, n - 1), min_dist=0.0, metric="cosine", random_state=seed).fit_transform(unit)
    return HDBSCAN(min_cluster_size=mcs, min_samples=min(mcs, 5), cluster_selection_method="eom").fit(reduced).labels_


POLARITY = {
    "+": ("high", "higher", "increase", "increased", "increasing", "more", "greater", "positive", "strong", "stronger", "elevated", "gain"),
    "-": ("low", "lower", "decrease", "decreased", "decreasing", "less", "fewer", "negative", "weak", "weaker", "reduced", "reduction", "loss", "decline"),
}


def polarity(text: str) -> str:
    """'+', '-' or '' from the degree words in a phrase; '' when mixed or absent."""
    words = set(re.findall(r"[a-z]+", text.lower()))
    plus, minus = bool(words & set(POLARITY["+"])), bool(words & set(POLARITY["-"]))
    return "+" if plus and not minus else "-" if minus and not plus else ""


def split_by_polarity(labels: np.ndarray, texts: list[str]) -> np.ndarray:
    """Embeddings put "high autonomy" next to "low autonomy"; a quality's value and a
    change's direction are what a qualifier carries, so a cluster is split by polarity.
    Phrases with no degree word stay with the cluster's unmarked part."""
    out = labels.copy()
    next_label = int(labels.max()) + 1 if len(labels) else 0
    for c in sorted(set(labels) - {-1}):
        members = np.flatnonzero(labels == c)
        pols = {i: polarity(texts[i]) for i in members}
        signs = {p for p in pols.values() if p}
        if len(signs) < 2:
            continue
        # keep '' and the majority sign together, move the minority sign out
        counts = Counter(p for p in pols.values() if p)
        minority = min(counts, key=counts.get)
        for i in members:
            if pols[i] == minority:
                out[i] = next_label
        next_label += 1
    return out


def keywords_for(texts: list[str], labels: np.ndarray, top: int = 6) -> dict[int, list[str]]:
    clusters = sorted(set(labels) - {-1})
    if not clusters or len(clusters) < 2:
        return {c: [] for c in clusters}
    docs = [" ".join(t for t, l in zip(texts, labels) if l == c) for c in clusters]
    counts = CountVectorizer(stop_words=list(ENGLISH_STOP_WORDS), ngram_range=(1, 2)).fit(docs)
    matrix = counts.transform(docs).toarray().astype(float)
    tf = matrix / np.maximum(matrix.sum(axis=1, keepdims=True), 1)
    idf = np.log1p(matrix.sum() / len(clusters) / np.maximum(matrix.sum(axis=0), 1))
    scores, vocab = tf * idf, counts.get_feature_names_out()
    return {c: [vocab[i] for i in np.argsort(-scores[k])[:top] if scores[k, i] > 0] for k, c in enumerate(clusters)}


# ============================================================== 5. categorise

CATEGORISE_SYSTEM = """You are an ontologist applying Basic Formal Ontology 2020 to a cluster of short phrases. All phrases were extracted from research claims in the same role, and phrases in a cluster were judged to mean the same thing. Decide what kind of entity the cluster names.

Decide in this order:
1. kind: domain_entity (a kind of thing in the world), measurement_or_method (instruments, statistics, study designs; these are information, not domain entities, unless the role is 'information'), comparative_or_statistical (a comparison between groups or a correlation, not a kind of thing), mixed (several kinds), other.
   A quality or realizable qualified by a degree ("high autonomy", "low resting vagal tone", "strong preference for solitude") IS a domain entity: it is the quality at that value, which a participant can bear. Only comparisons between groups ("higher than younger adults") and statistics are comparative.
2. bfo_category, for domain entities and for information: the role the phrases were extracted in suggests a bucket; keep it unless the phrases clearly say otherwise (a 'participant' that names a status like "study participant" is a role; a 'participant' that names a device is an object; a 'quality' that is really a tendency is a disposition). Categories: material entity, object, object aggregate, site, quality, disposition, role, function, generically dependent continuant, process, process boundary, temporal region, spatial region. A change in degree ("increase in X") is a process.
3. label: singular lowercase noun phrase, at most six words, no hedges.
4. definition: "A <genus> that <differentia>." with the genus the BFO category or a more specific kind the phrases imply.
5. genus: the parent kind as a short phrase ("human", "child", "experience", "social interaction"), or "" when the BFO category itself is the parent. Prefer the most specific kind the phrases share.
6. differentiae: what distinguishes this kind from its genus, as typed items. kind is one of: quality (a property the bearer has: "social withdrawal", "shyness"), realizable (a tendency, role or function: "behavioral inhibition"), life_stage (an age or developmental stage: "older adulthood", "preschool age"), location (where it is), member_kind (for a group: the kind of its members), other. phrase is a short noun phrase. Give one item per distinct component; leave the list empty when the phrases name a bare kind.
7. collective: true only when the phrases name a group as such (a family, a peer group, a dyad, a cohort, a population studied as a whole). Plural participants of a process ("older adults", "children") are individuals of that kind: collective = false and category object or material entity, never object aggregate.
8. rationale: one sentence naming the BFO question that decided it.
9. confidence: 0 to 1."""

CATEGORY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "kind": {"type": "string", "enum": ["domain_entity", "measurement_or_method", "comparative_or_statistical", "mixed", "other"]},
        "bfo_category": {"type": "string", "enum": list(CATEGORIES) + ["none"]},
        "label": {"type": "string"}, "definition": {"type": "string"},
        "genus": {"type": "string"},
        "differentiae": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                    "properties": {"kind": {"type": "string", "enum": ["quality", "realizable", "life_stage", "location", "member_kind", "other"]},
                                                                   "phrase": {"type": "string"}},
                                                    "required": ["kind", "phrase"]}},
        "collective": {"type": "boolean"},
        "rationale": {"type": "string"}, "confidence": {"type": "number"},
    },
    "required": ["kind", "bfo_category", "label", "definition", "genus", "differentiae", "collective", "rationale", "confidence"],
}

# Where a definition's components live, and the BFO category a minted one gets.
GENUS_TARGET = {"participant": "object", "process": "process", "quality": "quality", "realizable": "disposition",
                "when": "temporal region", "where": "site", "information": "generically dependent continuant"}
DIFFERENTIA_TARGET = {"quality": ("quality", "quality"), "life_stage": ("quality", "quality"), "realizable": ("realizable", "disposition"),
                      "location": ("where", "site"), "member_kind": ("participant", "object")}
TOP = {**{c: "continuant" for c in INDEPENDENT | DEPENDENT | {"generically dependent continuant", "spatial region"}},
       **{c: "occurrent" for c in PROCESSES | {"temporal region"}}}
# A genus must sit in the same BFO family as the class: an independent continuant cannot be a
# kind of role, a process cannot be a kind of quality. Families are pairwise disjoint in BFO.
FAMILY = {**{c: "independent" for c in INDEPENDENT}, **{c: "dependent" for c in DEPENDENT},
          "generically dependent continuant": "information", **{c: "process" for c in PROCESSES},
          "temporal region": "temporal region", "spatial region": "spatial region"}


def categorise(client, model: str, role: str, phrases: list[str], keywords: list[str], papers: int) -> dict:
    user = (f"Role the phrases were extracted in: {role} (usual bucket: {ROLE_BUCKET[role]}).\nPapers: {papers}.\n"
            f"Distinctive words: {', '.join(keywords) or '(none)'}\n\nPhrases, most central first:\n" + "\n".join(f"- {p}" for p in phrases[:14]))
    return ask_json(client, model, CATEGORISE_SYSTEM, user, CATEGORY_SCHEMA, "categorisation")


# ============================================================== 6. module helpers

def restriction(g: Graph, prop: URIRef, filler, kind: str = "some") -> BNode:
    node = BNode()
    g.add((node, RDF.type, OWL.Restriction)); g.add((node, OWL.onProperty, prop))
    g.add((node, OWL.someValuesFrom if kind == "some" else OWL.allValuesFrom, filler))
    return node


def intersection(g: Graph, *members) -> BNode:
    node, lst = BNode(), BNode()
    g.add((node, RDF.type, OWL.Class)); Collection(g, lst, list(members)); g.add((node, OWL.intersectionOf, lst))
    return node


def summarise_direction(directions: list[str], papers: list[str], minority: float = 0.25) -> tuple[str, bool]:
    """Majority direction among claims that say something about likelihood, and whether a
    minority of at least ``minority`` backed by two papers contests it."""
    votes = [(d, p) for d, p in zip(directions, papers) if d in ("increases", "decreases", "no_effect")]
    if not votes:
        return "none", False
    counts = Counter(d for d, _ in votes)
    majority = max(counts, key=counts.get)
    share = counts[majority] / len(votes)
    opposing_papers = {p for d, p in votes if d != majority}
    return majority, (1 - share) >= minority and len(opposing_papers) >= 2


def allowed_disposition(src_cat: str, dst_cat: str, direction: str, dst_label: str) -> str:
    """Why a tendency cannot be written, or '' when it can."""
    if dst_cat not in PROCESSES and dst_cat != "quality":
        return f"realization must be a process or a quality to come to bear, got {dst_cat}"
    if direction == "decreases" and not dst_label.lower().startswith(("decrease in", "reduction in", "loss of", "lower")):
        return "a disposition cannot make its realization less likely; 'decreases' needs the change named as the target"
    if direction == "no_effect":
        return "null finding: the claims say the target is unaffected"
    return ""


# ============================================================== identities and decisions

def stable_id(prefix: str, *parts: str) -> str:
    """A short identifier derived from content, so the same thing gets the same id on every run."""
    return prefix + hashlib.sha256("|".join(parts).encode()).hexdigest()[:10]


def reconcile(registry: dict, role: str, clusters: dict[int, list[str]], threshold: float = 0.5, run: str = "") -> tuple[dict[int, str], dict]:
    """Give each cluster a term id that survives re-runs.

    A cluster keeps the id of the registered term whose members overlap it most
    (Jaccard, or containment of the old term so a term that grew still matches)
    when the overlap reaches ``threshold``; otherwise it gets a new id. The
    report says what changed: matched, new, split (two clusters claim one old
    term; the better overlap keeps the id), merged (two old terms map to one
    cluster; the other is marked merged), vanished (an old term matched by no
    cluster)."""
    old = {tid: set(t["members"]) for tid, t in registry.items() if t["role"] == role and t.get("status") != "merged"}
    scores = {}
    for c, members in clusters.items():
        m = set(members)
        for tid, om in old.items():
            inter = len(m & om)
            if inter:
                scores[(c, tid)] = max(inter / len(m | om), inter / len(om))
    assignment, used = {}, {}
    for (c, tid), s in sorted(scores.items(), key=lambda kv: -kv[1]):
        if s < threshold or c in assignment or tid in used:
            continue
        assignment[c] = tid
        used[tid] = c
    report = {"matched": len(assignment), "new": 0, "split": [], "merged": [], "vanished": []}
    for (c, tid), s in scores.items():
        if s >= threshold and c not in assignment and tid in used:
            report["split"].append((tid, c))
    for c in clusters:
        if c not in assignment:
            assignment[c] = stable_id("T", role, run, *sorted(clusters[c]))
            report["new"] += 1
    for tid in old:
        if tid in used:
            continue
        best = max(((c, s) for (c, t), s in scores.items() if t == tid), key=lambda x: x[1], default=None)
        if best and best[1] >= threshold:
            report["merged"].append((tid, assignment[best[0]]))
        else:
            report["vanished"].append(tid)
    return assignment, report


def apply_decisions(decisions: list[dict]) -> dict:
    """Index a decisions file by target.

    Rows are ``{"target": <term or axiom id>, "action": ..., "value": ...}`` with
    actions accept, reject, rename (value: label), recategorise (value: BFO
    category), merge (value: target term id). The last decision on a target wins."""
    out = {"reject": set(), "accept": set(), "rename": {}, "recategorise": {}, "merge": {}}
    for d in decisions:
        target, action, value = d.get("target"), d.get("action"), d.get("value")
        if not target or action not in ("accept", "reject", "rename", "recategorise", "merge"):
            continue
        for key in ("reject", "accept"):
            out[key].discard(target)
        for key in ("rename", "recategorise", "merge"):
            out[key].pop(target, None)
        if action in ("accept", "reject"):
            out[action].add(target)
        elif action == "recategorise" and value in CATEGORIES:
            out[action][target] = value
        elif action in ("rename", "merge") and value:
            out[action][target] = value
    return out


def plan_components(classes: dict, is_class) -> list[tuple]:
    """Which definition components to resolve: (owner key, kind, target role, minted category, phrase).

    A genus that is just a BFO category name adds nothing; a member kind only
    makes sense for a collective."""
    bare = {normalize_key(c) for c in CATEGORIES} | {"entity", "thing", "kind"}
    degree_only = set(POLARITY["+"]) | set(POLARITY["-"]) | {"degree", "level", "amount", "extent", "very"}
    wanted = []
    for k, p in classes.items():
        if not is_class(*k):
            continue
        role, category, own = k[0], p.get("bfo_category"), normalize_key(p.get("label") or "")
        genus = (p.get("genus") or "").strip()
        if genus and normalize_key(genus) not in bare and normalize_key(genus) != own:
            # The genus follows the class's category, not the slot it came from: a state in the
            # process slot typed as a quality has a quality for a genus.
            target_role = next((r for r, cat in GENUS_TARGET.items() if cat == category), None)
            if category in DEPENDENT:
                target_role, minted_category = ("quality", "quality") if category == "quality" else ("realizable", category)
            elif target_role is not None:
                minted_category = category
            else:
                target_role, minted_category = role, GENUS_TARGET[role]
            wanted.append((k, "genus", target_role, minted_category, genus))
        for d in p.get("differentiae", []):
            phrase = (d.get("phrase") or "").strip()
            kind = d.get("kind")
            if not phrase or kind not in DIFFERENTIA_TARGET or normalize_key(phrase) == own:
                continue
            if kind == "location":
                continue  # no axiom can use it (BFO core has no located-in for this pattern); reported as a note instead
            if set(re.findall(r"[a-z]+", phrase.lower())) <= degree_only:
                continue  # "high degree" is not a quality, it is the value of one
            # Only a bearer can have a quality or a realizable; a process's differentiae are its
            # participants and parts, which the frames already supply.
            if kind in ("quality", "life_stage", "realizable") and category not in INDEPENDENT:
                continue
            if kind == "member_kind" and not (p.get("collective") and category == "object aggregate"):
                continue
            target_role, minted_category = DIFFERENTIA_TARGET[kind]
            wanted.append((k, kind, target_role, minted_category, phrase))
    return wanted


def resolve_components(wanted: list[tuple], vectors: np.ndarray, centroids: dict, threshold: float) -> tuple[dict, dict]:
    """Match each component to an existing class of its target role by centroid
    similarity; what does not match is grouped for minting, one class per paraphrase group.

    ``centroids`` maps a role to (list of class keys, unit matrix). Returns
    (matched: component -> class key, to_mint: role -> list of (component, vector))."""
    matched, to_mint = {}, defaultdict(list)
    for w, v in zip(wanted, vectors):
        role = w[2]
        if role in centroids:
            keys, M = centroids[role]
            sims = M @ v
            j = int(np.argmax(sims))
            if sims[j] >= threshold:
                matched[w] = keys[j]
                continue
        to_mint[role].append((w, v))
    return matched, to_mint


# ============================================================== main

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--papers", type=int, default=3, help="how many papers to sample (first N sorted ids)")
    parser.add_argument("--paper-ids", nargs="*", default=None, help="explicit paper ids instead of a sample")
    parser.add_argument("--max-chunks", type=int, default=0, help="cap on chunks (0 = all chunks of the sampled papers)")
    parser.add_argument("--run", default=None, help="run name under <dir>/frames/ (default p<papers>)")
    parser.add_argument("--model", default="gpt-4.1")
    parser.add_argument("--min-cluster-size", type=int, default=5, help="HDBSCAN minimum, used once a role has --density-from phrases")
    parser.add_argument("--merge-distance", type=float, default=0.20, help="cosine distance under which small-role phrases are one concept")
    parser.add_argument("--density-from", type=int, default=2000,
                        help="phrases per role from which UMAP + HDBSCAN is used; below it, paraphrase agglomeration (a few hundred phrases over-merge under density)")
    parser.add_argument("--min-members", type=int, default=2, help="phrases a cluster needs before it becomes a class")
    parser.add_argument("--resolve-threshold", type=float, default=0.80, help="cosine similarity for a definition component to reuse an existing class")
    parser.add_argument("--registry", type=Path, default=None, help="term registry (JSONL) that gives clusters ids surviving re-runs; default <dir>/frames/registry.jsonl")
    parser.add_argument("--decisions", type=Path, default=None, help="review decisions (JSONL) applied on rebuild; default <dir>/frames/decisions.jsonl")
    parser.add_argument("--reconcile-threshold", type=float, default=0.5, help="member overlap for a cluster to keep a registered term's id")
    parser.add_argument("--min-papers", type=int, default=1, help="papers behind a restriction or relation before it is written")
    parser.add_argument("--base", default="http://purl.example.org/terms/")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    run = args.dir / "frames" / (args.run or f"p{args.papers}")
    run.mkdir(parents=True, exist_ok=True)
    client = None

    def get_client():
        nonlocal client
        if client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                sys.exit("OPENAI_API_KEY is not set and a cached stage is missing")
            from openai import OpenAI
            client = OpenAI()
        return client

    # ---- 1. extract ----
    claims_path = run / "claims.jsonl"
    if claims_path.exists():
        claims = [json.loads(line) for line in open(claims_path)]
        print(f"[extract] reusing {len(claims)} claims", file=sys.stderr)
    else:
        chunks = pd.read_parquet(args.dir / "phases_v2_chunks.meta.parquet")
        chunks = chunks[chunks["text"].fillna("").str.len() > 200]
        if args.paper_ids:
            paper_ids = args.paper_ids
        else:
            # Mid-sized papers, spread across the sorted ids, so a sample of N really is N papers.
            sizes = chunks.groupby("paper_id").size()
            if args.papers >= len(sizes):
                paper_ids = sorted(sizes.index)  # the whole local corpus
            else:
                candidates = sorted(sizes[(sizes >= 10) & (sizes <= 40)].index) or sorted(sizes.index)
                step = max(1, len(candidates) // args.papers)
                paper_ids = candidates[::step][: args.papers]
        chunks = chunks[chunks["paper_id"].isin(paper_ids)].sort_values(["paper_id", "seq"])
        if args.max_chunks:
            chunks = chunks.head(args.max_chunks)
        print(f"[extract] {len(chunks)} chunks from {len(paper_ids)} papers with {args.model}", file=sys.stderr)
        claims = extract(get_client(), args.model, chunks, args.workers)
        with open(claims_path, "w") as f:
            for c in claims:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
    claims = [normalise_direction(c) for c in claims]
    n_chunks = len({c["chunk_id"] for c in claims})
    sample_papers = len({c["paper_id"] for c in claims})

    # ---- 2. flatten ----
    spans = flatten(claims)
    spans.to_parquet(run / "spans.parquet", index=False)

    # ---- 3. embed ----
    phrases = spans.drop_duplicates(["role", "key"])[["role", "key", "text"]].reset_index(drop=True)
    vec_path = run / "vectors.npy"
    if vec_path.exists() and (run / "phrases.parquet").exists() and len(pd.read_parquet(run / "phrases.parquet")) == len(phrases):
        unit = np.load(vec_path)
        print(f"[embed] reusing {len(phrases)} vectors", file=sys.stderr)
    else:
        print(f"[embed] {len(phrases)} distinct (role, phrase)", file=sys.stderr)
        unit = embed(get_client(), phrases["text"].tolist())
        np.save(vec_path, unit)
    phrases.to_parquet(run / "phrases.parquet", index=False)

    # ---- 4. cluster per role ----
    phrases["cluster"] = -1
    cluster_info = {}
    for role in ROLES:
        idx = np.flatnonzero(phrases["role"] == role)
        if len(idx) == 0:
            continue
        texts = phrases.loc[idx, "text"].tolist()
        labels = split_by_polarity(cluster_role(unit[idx], args.min_cluster_size, args.seed, args.merge_distance, args.density_from), texts)
        phrases.loc[idx, "cluster"] = labels
        kw = keywords_for(texts, labels)
        for c in sorted(set(labels) - {-1}):
            members = idx[labels == c]
            centroid = unit[members].mean(axis=0); centroid /= np.linalg.norm(centroid)
            order = members[np.argsort(-(unit[members] @ centroid))]
            cluster_info[(role, int(c))] = {"members": members.tolist(), "central": phrases.loc[order[:14], "text"].tolist(), "keywords": kw.get(c, [])}
    phrases.to_parquet(run / "phrases.parquet", index=False)
    key_to_cluster = {(r, k): int(c) for r, k, c in zip(phrases["role"], phrases["key"], phrases["cluster"])}
    spans["cluster"] = [key_to_cluster[(r, k)] for r, k in zip(spans["role"], spans["key"])]
    papers_of = spans[spans.cluster >= 0].groupby(["role", "cluster"])["paper_id"].nunique().to_dict()

    # ---- identities: a cluster keeps its term id across runs; decisions attach to that id ----
    registry_path = args.registry or (args.dir / "frames" / "registry.jsonl")
    registry = {r["term_id"]: r for r in (json.loads(l) for l in open(registry_path))} if registry_path.exists() else {}
    term_id, reconciliation = {}, {}
    for role in ROLES:
        members_of = {c: phrases.loc[info["members"], "key"].tolist() for (r, c), info in cluster_info.items() if r == role}
        if members_of:
            assignment, report = reconcile(registry, role, members_of, args.reconcile_threshold, run.name)
            term_id.update({(role, c): tid for c, tid in assignment.items()})
            reconciliation[role] = report
    decisions_path = args.decisions or (args.dir / "frames" / "decisions.jsonl")
    decided = apply_decisions([json.loads(l) for l in open(decisions_path)] if decisions_path.exists() else [])
    print(f"[identities] {sum(r['matched'] for r in reconciliation.values())} clusters kept a registered id, "
          f"{sum(r['new'] for r in reconciliation.values())} new; decisions: {sum(len(v) for v in decided.values())}", file=sys.stderr)

    # ---- 5. categorise per cluster ----
    # The cache is keyed by the cluster's content, not its id: a re-clustering
    # that yields the same set of phrases reuses the categorisation, anything
    # else is categorised afresh.
    prompt_hash = hashlib.sha256(CATEGORISE_SYSTEM.encode()).hexdigest()[:8]
    for k, info in cluster_info.items():
        content = "|".join(sorted(phrases.loc[info["members"], "key"]))
        info["signature"] = hashlib.sha256(f"{prompt_hash}|{k[0]}|{content}".encode()).hexdigest()[:16]
    cat_path = run / "classes.jsonl"
    cache = {r["signature"]: r for r in (json.loads(l) for l in open(cat_path)) if "signature" in r} if cat_path.exists() else {}
    # Only clusters with enough members (or seen in two papers) are worth a class.
    eligible = {k for k, info in cluster_info.items() if len(info["members"]) >= args.min_members or papers_of.get(k, 0) >= 2}
    missing = [k for k in eligible if cluster_info[k]["signature"] not in cache]
    if missing:
        print(f"[categorise] {len(missing)} clusters with {args.model}", file=sys.stderr)

        def one(k):
            role, c = k
            info = cluster_info[k]
            out = categorise(get_client(), args.model, role, info["central"], info["keywords"], papers_of.get((role, c), 0))
            return {"signature": info["signature"], "role": role, "cluster": c, "size": len(info["members"]), "papers": papers_of.get((role, c), 0),
                    "keywords": info["keywords"], "central": info["central"][:6], **out}

        with ThreadPoolExecutor(args.workers) as pool:
            for r in pool.map(one, missing):
                cache[r["signature"]] = r
        with open(cat_path, "w") as f:
            for r in cache.values():
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    classes = {k: dict(cache[cluster_info[k]["signature"]]) | {"cluster": k[1], "papers": papers_of.get(k, 0)} for k in eligible if cluster_info[k]["signature"] in cache}
    # Participants are individuals unless the phrases name a collective; the
    # aggregate and its member kind are two classes joined by 'has member part'.
    for (role, c), p in classes.items():
        if role == "participant" and p.get("bfo_category") == "object aggregate" and not p.get("collective"):
            p["bfo_category"] = "object"
        elif role == "participant" and p.get("collective") and p.get("bfo_category") in INDEPENDENT:
            p["bfo_category"] = "object aggregate"

    # ---- decisions from review: rename, recategorise, reject; merges are applied when classes are created ----
    for k, p in classes.items():
        tid = term_id[k]
        if tid in decided["rename"]:
            p["alias"] = p.get("label"); p["label"] = decided["rename"][tid]
        if tid in decided["recategorise"]:
            p["bfo_category"] = decided["recategorise"][tid]; p["kind"] = "domain_entity"
    rejected = {k for k in classes if term_id[k] in decided["reject"]}

    def is_class(role, c):
        p = classes.get((role, c))
        if not p or (role, c) in rejected:
            return False
        return p["bfo_category"] in CATEGORIES and (p["kind"] == "domain_entity" or (role == "information" and p["kind"] in ("domain_entity", "measurement_or_method")))

    # ---- 6. module ----
    T = Namespace(args.base)
    g = Graph(); g.bind("terms", T); g.bind("obo", OBO); g.bind("owl", OWL)
    onto = URIRef(args.base.rstrip("/#"))
    g.add((onto, RDF.type, OWL.Ontology)); g.add((onto, OWL.imports, URIRef(BFO_IRI)))
    for prop, label in (("clusterId", "cluster id (role:cluster)"), ("termId", "term id: stable across runs, the target of review decisions"),
                        ("supportPapers", "support: distinct papers"), ("supportClaims", "support: claims"),
                        ("proposalRationale", "proposal rationale"), ("modelSelfConfidence", "the categoriser's own confidence (self-reported, uncalibrated)"),
                        ("evidence", "evidence quote"), ("claimDirection", "claim direction"), ("contested", "contested"), ("origin", "origin of the axiom"),
                        ("axiomId", "axiom id: stable across runs, the target of review decisions"), ("status", "review status"), ("alias", "another label this class absorbed"),
                        ("when", "temporal context stated by the claims"), ("howWeKnow", "instrument or design stated by the claims"), ("definedFrom", "defined class built from a qualified frame")):
        g.add((T[prop], RDF.type, OWL.AnnotationProperty)); g.add((T[prop], RDFS.label, Literal(label)))
    # Class IRIs are the term ids, so a class keeps its IRI across runs and decisions keep pointing at it.
    by_tid = {tid: k for k, tid in term_id.items()}
    merged_into = {k: by_tid.get(decided["merge"][term_id[k]]) for k in classes if term_id[k] in decided["merge"]}
    iri, label_of, cat_of = {}, {}, {}
    for (role, c), p in classes.items():
        if not is_class(role, c) or (role, c) in merged_into:
            continue
        tid = term_id[(role, c)]
        node = T[tid]
        iri[(role, c)], label_of[(role, c)], cat_of[(role, c)] = node, p["label"], p["bfo_category"]
        g.add((node, RDF.type, OWL.Class)); g.add((node, RDFS.subClassOf, OBO[CATEGORIES[p["bfo_category"]]]))
        g.add((node, RDFS.label, Literal(p["label"], lang="en"))); g.add((node, DEFINITION, Literal(p["definition"], lang="en")))
        g.add((node, T.clusterId, Literal(f"{role}:{c}"))); g.add((node, T.termId, Literal(tid))); g.add((node, T.supportPapers, Literal(p["papers"])))
        g.add((node, T.proposalRationale, Literal(p["rationale"]))); g.add((node, T.modelSelfConfidence, Literal(p["confidence"], datatype=XSD.decimal)))
        if tid in decided["accept"]:
            g.add((node, T.status, Literal("accepted")))
        if p.get("alias"):
            g.add((node, T.alias, Literal(p["alias"])))
    for k, target in merged_into.items():
        if target is not None and target in iri:
            iri[k], label_of[k], cat_of[k] = iri[target], label_of[target], cat_of[target]
            g.add((iri[target], T.alias, Literal(f"{classes[k]['label']} (merged by decision)")))

    ev = Graph(); ev.bind("terms", T)
    ev.add((URIRef(args.base.rstrip("/#") + "/evidence"), RDF.type, OWL.Ontology))

    def annotate(subject, pred, copy, a: dict):
        ann = BNode()
        g.add((ann, RDF.type, OWL.Axiom)); g.add((ann, OWL.annotatedSource, subject)); g.add((ann, OWL.annotatedProperty, pred)); g.add((ann, OWL.annotatedTarget, copy))
        g.add((ann, T.supportPapers, Literal(a["papers"]))); g.add((ann, T.supportClaims, Literal(a["n"]))); g.add((ann, T.origin, Literal(a["origin"])))
        if "direction" in a:
            g.add((ann, T.claimDirection, Literal(a["direction"])))
        if a.get("contested"):
            g.add((ann, T.contested, Literal(True)))
        for cid, quote in a.get("evidence", []):
            sent = T[f"E{cid}"]
            g.add((ann, T.evidence, sent)); ev.add((sent, RDFS.label, Literal(quote)))
        if a.get("axiom_id"):
            g.add((ann, T.axiomId, Literal(a["axiom_id"])))
            if a["axiom_id"] in decided["accept"]:
                g.add((ann, T.status, Literal("accepted")))

    def remove_expression(node):
        """Drop an anonymous class expression (restrictions, intersections, their lists)
        that no axiom refers to; OWLAPI cannot parse an orphaned intersection."""
        if not isinstance(node, BNode):
            return
        for _, _, o in list(g.triples((node, None, None))):
            remove_expression(o)
        g.remove((node, None, None))

    def assert_axiom(subject, pred, obj, copy, a: dict) -> bool:
        """Write an axiom unless a review decision rejected it. The axiom id is
        derived from its origin and its two ends, so it is the same on every run."""
        aid = stable_id("A", a["origin"], str(subject), str(a.get("dst", "")))
        a["axiom_id"] = aid
        if aid in decided["reject"]:
            remove_expression(obj); remove_expression(copy)
            return False
        g.add((subject, pred, obj)); annotate(subject, pred, copy, a)
        return True

    # ---- 6a. definitions: genus, differentiae and members become classes and axioms ----
    # A definition names things ("a human child exhibiting social withdrawal").
    # Each component is resolved to an existing class of its role or minted once,
    # so the hierarchy the definitions know becomes axioms the reasoner sees.
    centroids = {}
    for role in ROLES:
        keys = [k for k in iri if k[0] == role]
        if keys:
            M = np.vstack([unit[cluster_info[k]["members"]].mean(axis=0) for k in keys])
            centroids[role] = (keys, M / np.linalg.norm(M, axis=1, keepdims=True))
    wanted = plan_components(classes, is_class)
    component_node, minted, definitional = {}, {}, []
    if wanted:
        vectors = embed(get_client(), [w[4] for w in wanted])
        matched, to_mint = resolve_components(wanted, vectors, centroids, args.resolve_threshold)
        for w, key in matched.items():
            component_node[w] = iri[key]
        for role, items in to_mint.items():
            V = np.vstack([v for _, v in items])
            # same guard as the clusters: "high aloneliness" and "low aloneliness" are two classes
            groups = split_by_polarity(cluster_role(V, args.min_cluster_size, args.seed, args.merge_distance, args.density_from), [w[4] for w, _ in items])
            for gid in sorted(set(groups)):
                members = [w for (w, _), l in zip(items, groups) if l == gid]
                phrase = min((w[4] for w in members), key=len)
                category = members[0][3]
                node = T[f"TX{len(minted):04d}"]
                minted[node] = {"label": phrase, "category": category, "role": role, "from": [label_of[w[0]] for w in members]}
                g.add((node, RDF.type, OWL.Class)); g.add((node, RDFS.subClassOf, OBO[CATEGORIES[category]]))
                g.add((node, RDFS.label, Literal(phrase, lang="en")))
                g.add((node, DEFINITION, Literal(f"A {category} named in the definitions of {len(members)} class(es); to be defined.", lang="en")))
                g.add((node, T.origin, Literal("minted from definitions: " + "; ".join(sorted({label_of[w[0]] for w in members})[:6]))))
                for w in members:
                    component_node[w] = node

    def node_label(node):
        return minted[node]["label"] if node in minted else str(g.value(node, RDFS.label))

    def node_category(node):
        return minted[node]["category"] if node in minted else next((c for k, c in cat_of.items() if iri[k] == node), None)

    for w, node in component_node.items():
        owner, kind, _, _, phrase = w
        subj, owner_cat, owner_label = iri[owner], cat_of[owner], label_of[owner]
        target_cat = node_category(node)
        if node == subj or target_cat is None:
            continue
        a = {"origin": f"definition: {kind}", "n": 1, "papers": classes[owner]["papers"], "dst": node_label(node)}
        if kind == "genus":
            aid = stable_id("A", a["origin"], str(subj), a["dst"])
            if FAMILY.get(owner_cat) == FAMILY.get(target_cat) and aid not in decided["reject"]:
                g.add((subj, RDFS.subClassOf, node))
                definitional.append(f"'{owner_label}' SubClassOf '{node_label(node)}'  [{aid}]")
        elif kind in ("quality", "life_stage", "realizable"):
            if owner_cat in INDEPENDENT and target_cat in DEPENDENT:
                obj, copy = restriction(g, REL["bearer of"], node), restriction(g, REL["bearer of"], node)
                if assert_axiom(subj, RDFS.subClassOf, obj, copy, a):
                    definitional.append(f"'{owner_label}' SubClassOf 'bearer of' some '{node_label(node)}'  [{a['axiom_id']}]")
        elif kind == "member_kind":
            if owner_cat == "object aggregate" and target_cat in INDEPENDENT:
                obj, copy = restriction(g, OBO.BFO_0000115, node), restriction(g, OBO.BFO_0000115, node)  # has member part
                if assert_axiom(subj, RDFS.subClassOf, obj, copy, a):
                    definitional.append(f"'{owner_label}' SubClassOf 'has member part' some '{node_label(node)}'  [{a['axiom_id']}]")

    # Participant expression: an independent continuant directly; a role or quality via its bearer.
    def participant_expr(pc: int):
        node, cat = iri[("participant", pc)], cat_of[("participant", pc)]
        return node if cat in INDEPENDENT else restriction(g, REL["bearer of"], node) if cat in DEPENDENT else None

    # Frame-level structure per claim side: process cluster, participant clusters, quality/realizable clusters tied to them.
    by_claim_side = defaultdict(lambda: {"process": None, "participants": [], "qualities": defaultdict(list), "realizables": defaultdict(list), "when": None, "where": None, "information": None})
    span_key = {(r.claim_id, r.side, r.role, r.key): r.cluster for r in spans.itertuples()}
    for r in spans.itertuples():
        f = by_claim_side[(r.claim_id, r.side)]
        if r.role == "process":
            f["process"] = r.cluster
        elif r.role == "participant":
            f["participants"].append(r.cluster)
        elif r.role in ("quality", "realizable"):
            pc = span_key.get((r.claim_id, r.side, "participant", r.of), -1)
            f["qualities" if r.role == "quality" else "realizables"][pc].append(r.cluster)
        else:
            f[r.role] = r.cluster
    claim_of = {c["claim_id"]: c for c in claims}

    # 6a. restrictions from frame structure, aggregated per process class
    structural = []
    per_process = defaultdict(lambda: defaultdict(list))  # (process cluster) -> relation key -> [(paper, claim)]
    for (cid, side), f in by_claim_side.items():
        pc = f["process"]
        # A process-role cluster the categoriser typed otherwise (a disposition, a role) is
        # not a process and cannot have participants; its frames are kept as evidence only.
        if pc is None or pc < 0 or not is_class("process", pc) or cat_of[("process", pc)] not in PROCESSES:
            continue
        paper = claim_of[cid]["paper_id"]
        per_process[pc]["frames"].append((paper, cid))
        for a in f["participants"]:
            if a >= 0 and is_class("participant", a):
                per_process[pc][("participant", a)].append((paper, cid))
        if f["where"] is not None and f["where"] >= 0 and is_class("where", f["where"]):
            per_process[pc][("where", f["where"])].append((paper, cid))
        if f["when"] is not None and f["when"] >= 0 and is_class("when", f["when"]):
            per_process[pc][("when", f["when"])].append((paper, cid))
        if f["information"] is not None and f["information"] >= 0 and is_class("information", f["information"]):
            per_process[pc][("information", f["information"])].append((paper, cid))
    for pc, rels in per_process.items():
        total = len(rels["frames"])
        for key, hits in rels.items():
            if key == "frames":
                continue
            role, c = key
            n_papers = len({p for p, _ in hits})
            if n_papers < args.min_papers or len(hits) < 0.5 * total:
                continue
            node = iri[("process", pc)]
            a = {"origin": f"frame structure: {role}", "n": len(hits), "papers": n_papers, "dst": label_of[(role, c)],
                 "evidence": [(cid, claim_of[cid]["evidence"]) for _, cid in hits[:4]]}
            if role == "participant":
                exprs = [participant_expr(c), participant_expr(c)]
                if exprs[0] is None:
                    continue
                obj, copy = (restriction(g, REL["has participant"], e) for e in exprs)
                text = f"'{label_of[('process', pc)]}' SubClassOf 'has participant' some '{label_of[('participant', c)]}'"
            elif role == "where" and cat_of[("where", c)] in INDEPENDENT:
                obj, copy = restriction(g, REL["occurs in"], iri[("where", c)]), restriction(g, REL["occurs in"], iri[("where", c)])
                text = f"'{label_of[('process', pc)]}' SubClassOf 'occurs in' some '{label_of[('where', c)]}'"
            else:
                # time and information are recorded as annotations: BFO core has no 'is about', and the temporal phrases are too coarse for regions.
                g.add((node, T.when if role == "when" else T.howWeKnow, Literal(f"{label_of[(role, c)]} ({n_papers} papers)")))
                structural.append(f"'{label_of[('process', pc)]}' {role}: '{label_of[(role, c)]}'  [{len(hits)}/{total} frames, {n_papers} papers]  (annotation)")
                continue
            if assert_axiom(node, RDFS.subClassOf, obj, copy, a):
                structural.append(f"{text}  [{len(hits)}/{total} frames, {n_papers} papers] [{a['axiom_id']}]")

    # 6b. qualified frames become defined subclasses: process and has participant some (participant and bearer of some quality)
    defined = {}

    def effective_class(cid: str, side: str):
        f = by_claim_side[(cid, side)]
        pc = f["process"]
        if pc is None or pc < 0 or not is_class("process", pc):
            return None
        if cat_of[("process", pc)] not in PROCESSES:
            # A state in the process slot ("having high shyness") is typed as a quality or a
            # disposition. It can carry a tendency through its bearer, but it has no
            # participants, so it gets no defined subclass.
            return iri[("process", pc)], label_of[("process", pc)], cat_of[("process", pc)], pc
        qualifiers = []
        for a in f["participants"]:
            if a < 0 or not is_class("participant", a):
                continue
            # Only what BFO lets a participant bear: a quality, or a realizable (disposition, role, function).
            qs = tuple(sorted({q for q in f["qualities"].get(a, []) if q >= 0 and is_class("quality", q) and cat_of[("quality", q)] == "quality"}))
            rs = tuple(sorted({r for r in f["realizables"].get(a, []) if r >= 0 and is_class("realizable", r) and cat_of[("realizable", r)] in ("disposition", "role", "function")}))
            if qs or rs:
                qualifiers.append((a, qs, rs))
        if not qualifiers:
            return iri[("process", pc)], label_of[("process", pc)], cat_of[("process", pc)], pc
        key = (pc, tuple(qualifiers))
        if key not in defined:
            node = T[f"TD{len(defined):04d}"]
            parts, texts = [], []
            for a, qs, rs in qualifiers:
                pe = participant_expr(a)
                if pe is None:
                    continue
                bearer = intersection(g, pe, *[restriction(g, REL["bearer of"], iri[("quality", q)]) for q in qs], *[restriction(g, REL["bearer of"], iri[("realizable", r)]) for r in rs])
                parts.append(restriction(g, REL["has participant"], bearer))
                texts.append(f"{label_of[('participant', a)]} bearing {', '.join(label_of[('quality', q)] for q in qs) or ''}{' ' if qs and rs else ''}{', '.join(label_of[('realizable', r)] for r in rs)}")
            label = f"{label_of[('process', pc)]} ({'; '.join(texts)})"
            g.add((node, RDF.type, OWL.Class)); g.add((node, RDFS.label, Literal(label, lang="en")))
            g.add((node, RDFS.subClassOf, iri[("process", pc)]))  # implied by the equivalence; stated so the hierarchy is explicit
            g.add((node, OWL.equivalentClass, intersection(g, iri[("process", pc)], *parts)))
            g.add((node, T.definedFrom, Literal(f"process:{pc}")))
            g.add((node, DEFINITION, Literal(f"A {label_of[('process', pc)]} whose participants are as qualified in the claims that mention it.", lang="en")))
            defined[key] = (node, label, cat_of[("process", pc)], pc)
        return defined[key]

    # 6c. relations between frames
    relations = defaultdict(list)
    for c in claims:
        src, dst = effective_class(c["claim_id"], "antecedent"), effective_class(c["claim_id"], "consequent")
        if src is None or dst is None or src[0] == dst[0]:
            continue
        relations[(src, dst)].append(c)
    relation_axioms, evidence_only = [], []
    for (src, dst), cs in relations.items():
        n_papers = len({c["paper_id"] for c in cs})
        if n_papers < args.min_papers:
            continue
        kinds = Counter(c["relation"]["kind"] for c in cs)
        kind = max(kinds, key=kinds.get)
        direction, contested = summarise_direction([c["relation"]["direction"] for c in cs], [c["paper_id"] for c in cs])
        src_node, src_label, src_cat, src_pc = src
        dst_node, dst_label, dst_cat, dst_pc = dst
        a = {"origin": f"relation: {kind}", "n": len(cs), "papers": n_papers, "direction": direction, "contested": contested,
             "evidence": [(c["claim_id"], c["evidence"]) for c in cs[:4]], "src": src_label, "dst": dst_label}
        if kind in ("tends_to", "causes"):
            why = allowed_disposition(src_cat, dst_cat, direction, dst_label)
            if why:
                evidence_only.append(a | {"why": why}); continue

            def expr():
                target = dst_node if dst_cat in PROCESSES else intersection(g, OBO.BFO_0000015, restriction(g, REL["has participant"], restriction(g, REL["bearer of"], dst_node)))
                realizable = intersection(g, OBO.BFO_0000016, restriction(g, REL["has realization"], target, "only"))
                bearer = restriction(g, REL["bearer of"], realizable)
                return restriction(g, REL["has participant"], bearer) if src_cat in PROCESSES else bearer if src_cat in INDEPENDENT else restriction(g, REL["inheres in"], bearer)
            obj, copy = expr(), expr()
            if not assert_axiom(src_node, RDFS.subClassOf, obj, copy, a):
                evidence_only.append(a | {"why": "rejected by review decision"}); continue
            head = "'has participant' some ('bearer of' some" if src_cat in PROCESSES else "'bearer of' some (" if src_cat in INDEPENDENT else "'inheres in' some ('bearer of' some"
            a["manchester"] = f"'{src_label}' SubClassOf {head} (disposition and 'has realization' only '{dst_label}'))"
            relation_axioms.append(a)
        elif kind in ("is_a", "defines") and src_cat == dst_cat:
            # A hierarchy or an equivalence is a stronger claim than a tendency: it needs two
            # papers, and a process is never equivalent to its own qualified subclass.
            if n_papers < 2:
                evidence_only.append(a | {"why": f"{kind} needs two papers to become a class axiom"}); continue
            if src_pc == dst_pc:
                evidence_only.append(a | {"why": f"{kind} between a process and its own qualified subclass"}); continue
            pred = RDFS.subClassOf if kind == "is_a" else OWL.equivalentClass
            if not assert_axiom(src_node, pred, dst_node, dst_node, a):
                evidence_only.append(a | {"why": "rejected by review decision"}); continue
            a["manchester"] = f"'{src_label}' {'SubClassOf' if kind == 'is_a' else 'EquivalentTo'} '{dst_label}'"
            relation_axioms.append(a)
        else:
            evidence_only.append(a | {"why": f"{kind} between {src_cat} and {dst_cat} is evidence, not an axiom"})

    g.serialize(run / "terms.ttl", format="turtle"); g.serialize(run / "terms.owl", format="xml"); ev.serialize(run / "evidence.ttl", format="turtle")
    core = args.dir / "bfo/bfo-core.ttl"
    if core.exists():
        (run / "bfo-core.ttl").write_bytes(core.read_bytes())

    # ---- registry: every cluster's id, members and status, so the next run can reconcile against it ----
    for k, info in cluster_info.items():
        tid = term_id[k]
        row = registry.get(tid, {"term_id": tid, "role": k[0], "created": run.name})
        row.update({"members": phrases.loc[info["members"], "key"].tolist(), "last_run": run.name,
                    "status": "rejected" if k in rejected else "merged" if k in merged_into else "active",
                    "label": classes.get(k, {}).get("label"), "category": classes.get(k, {}).get("bfo_category")})
        registry[tid] = row
    for rep in reconciliation.values():
        for tid, into in rep["merged"]:
            registry[tid]["status"], registry[tid]["merged_into"] = "merged", into
        for tid in rep["vanished"]:
            registry[tid]["status"] = "vanished"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    with open(registry_path, "w") as f:
        for r in registry.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ---- 7. review ----
    sides = 2 * len(claims)
    fill = {role: int((spans.role == role).groupby(spans.loc[spans.role == role, ["claim_id", "side"]].apply(tuple, axis=1)).any().sum()) if (spans.role == role).any() else 0 for role in ROLES}
    per_role = spans.groupby("role").agg(spans=("key", "size"), distinct=("key", "nunique")).to_dict("index")
    clusters_per_role = Counter(role for role, _ in cluster_info)
    classes_per_role = Counter(role for (role, c) in classes if is_class(role, c))
    noise = {role: int(((phrases.role == role) & (phrases.cluster < 0)).sum()) for role in ROLES}
    gaps = []
    for pc, rels in per_process.items():
        total = len(rels["frames"])
        missing_roles = [role for role in ("participant", "where", "when", "information") if not any(k[0] == role for k in rels if k != "frames")]
        if total >= 2 and missing_roles:
            gaps.append(f"- '{label_of[('process', pc)]}' ({total} frames): no consistent {', '.join(missing_roles)}")
    lines = [
        "# Frames pipeline review", "",
        f"- sample: {sample_papers} papers, {n_chunks} chunks, {len(claims)} claims ({len(claims) / max(n_chunks, 1):.1f} per chunk), model {args.model}",
        "", "## Slot fill rates (share of frame sides with the slot filled)", "",
        "| role | filled | share | spans | distinct phrases | clusters | noise phrases | classes |", "|---|---|---|---|---|---|---|---|",
        *(f"| {role} | {fill[role]} | {fill[role] / max(sides, 1):.0%} | {per_role.get(role, {}).get('spans', 0)} | {per_role.get(role, {}).get('distinct', 0)} | {clusters_per_role.get(role, 0)} | {noise[role]} | {classes_per_role.get(role, 0)} |" for role in ROLES),
        "", f"- relation kinds: {dict(Counter(c['relation']['kind'] for c in claims))}",
        f"- directions: {dict(Counter(c['relation']['direction'] for c in claims))}",
        f"- classes: {len(iri)} from clusters + {len(defined)} defined (qualified frames) + {len(minted)} minted from definitions",
        f"- definitional axioms (genus, differentiae, members): {len([d for d in definitional if '(noted' not in d])}",
        f"- restrictions from frame structure: {len([s for s in structural if '(annotation)' not in s])} (+ {len([s for s in structural if '(annotation)' in s])} annotations)",
        f"- relation axioms: {len(relation_axioms)}; evidence only: {len(evidence_only)}",
        "", "## Identities and decisions", "",
        f"- registry: {registry_path} ({len(registry)} terms after this run)",
        *(f"- {role}: {rep['matched']} clusters kept their term id, {rep['new']} new, {len(rep['split'])} split, {len(rep['merged'])} merged, {len(rep['vanished'])} vanished"
          for role, rep in reconciliation.items()),
        f"- decisions applied from {decisions_path}: {len(decided['accept'])} accepted, {len(decided['reject'])} rejected, {len(decided['rename'])} renamed, "
        f"{len(decided['recategorise'])} recategorised, {len(decided['merge'])} merged",
        "", "## Classes minted from definitions", "",
        "| category | label | referenced by |", "|---|---|---|",
        *(f"| {m['category']} | {m['label']} | {'; '.join(sorted(set(m['from']))[:6])} |" for m in sorted(minted.values(), key=lambda m: (m['category'], m['label']))),
        "", "## Definitional axioms", "", *(f"- {d}" for d in definitional),
        "", "## Locations stated in definitions (noted, no axiom)", "",
        *(f"- '{p['label']}': {d['phrase']}" for (role, c), p in classes.items() if is_class(role, c) for d in p.get("differentiae", []) if d.get("kind") == "location" and d.get("phrase")),
        "", "## Classes by bucket", "",
        "| term id | role | category | label | definition | papers | central phrases |", "|---|---|---|---|---|---|---|",
        *(f"| {term_id[(role, c)]} | {role} | {p['bfo_category']} | {p['label']} | {p['definition'][:100]} | {p['papers']} | {'; '.join(p['central'][:3])} |" for (role, c), p in sorted(classes.items(), key=lambda kv: (kv[0][0], -kv[1]['papers'], -kv[1]['size'])) if is_class(role, c)),
        "", "## Set aside (not domain entities)", "",
        *(f"- {role}:{c} {p['kind']}: {'; '.join(p['central'][:3])}" for (role, c), p in classes.items() if not is_class(role, c)),
        "", "## Restrictions from frame structure", "", *(f"- {s}" for s in structural),
        "", "## Defined classes from qualified frames", "", *(f"- {lbl}" for _, lbl, _, _ in defined.values()),
        "", "## Relation axioms", "", "| axiom id | papers | claims | direction | contested | axiom |", "|---|---|---|---|---|---|",
        *(f"| {a.get('axiom_id', '')} | {a['papers']} | {a['n']} | {a['direction']} | {'yes' if a['contested'] else ''} | {a['manchester']} |" for a in sorted(relation_axioms, key=lambda a: (-a['papers'], -a['n']))),
        "", "## Evidence only", "", *(f"- {a['src']} -> {a['dst']} ({a['papers']} papers, {a['direction']}): {a['why']}" for a in evidence_only),
        "", "## Gaps: processes with no consistent slot", "", *(gaps or ["- none"]),
    ]
    (run / "review.md").write_text("\n".join(lines))
    print("\n".join(lines[:16]))
    print(f"\nwrote {run}/terms.ttl, terms.owl, evidence.ttl, review.md")


if __name__ == "__main__":
    main()
