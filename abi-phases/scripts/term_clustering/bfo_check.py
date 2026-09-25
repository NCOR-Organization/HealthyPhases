# /// script
# requires-python = ">=3.12"
# dependencies = ["rdflib>=7", "owlready2>=0.46"]
# ///
"""One-off: check a proposed module against BFO 2020, structurally and with a reasoner.

Structural checks (rdflib, no Java needed):
- every class has exactly one label and one definition;
- every class reaches a BFO class through rdfs:subClassOf, and never both a
  continuant and an occurrent;
- every restriction uses an allowed BFO relation, and its subject and filler
  sit on the sides BFO gives that relation (a bearer is an independent
  continuant, what is borne is a specifically dependent continuant, what is
  realized is a process, and so on).

Reasoning (owlready2 + bundled HermiT, needs a Java runtime): the module and
BFO core are merged into one RDF/XML file, the reasoner runs, and the report
lists inconsistency, unsatisfiable classes, and inferred superclasses.

    uv run scripts/term_clustering/bfo_check.py
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from rdflib import Graph, Namespace, RDF, RDFS, OWL, URIRef

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "storage/spikes/term_clustering/bfo"
OBO = Namespace("http://purl.obolibrary.org/obo/")
DEFINITION = OBO.IAO_0000115
CONTINUANT, OCCURRENT = OBO.BFO_0000002, OBO.BFO_0000003
INDEPENDENT, SDC, PROCESS = OBO.BFO_0000004, OBO.BFO_0000020, OBO.BFO_0000015
# relation -> (what the subject must be under, what the filler must be under)
ALLOWED = {
    OBO.BFO_0000196: (INDEPENDENT, SDC, "bearer of"),
    OBO.BFO_0000197: (SDC, INDEPENDENT, "inheres in"),
    OBO.BFO_0000054: (OBO.BFO_0000017, PROCESS, "has realization"),
    OBO.BFO_0000056: (CONTINUANT, PROCESS, "participates in"),
    OBO.BFO_0000057: (PROCESS, CONTINUANT, "has participant"),
    OBO.BFO_0000066: (OCCURRENT, INDEPENDENT, "occurs in"),
}


def ancestors(g: Graph, node, seen=None) -> set:
    """Named superclasses reachable through subClassOf and intersection members."""
    seen = seen if seen is not None else set()
    for parent in g.objects(node, RDFS.subClassOf):
        if isinstance(parent, URIRef):
            if parent not in seen:
                seen.add(parent); ancestors(g, parent, seen)
        else:
            for member in _members(g, parent):
                if isinstance(member, URIRef) and member not in seen:
                    seen.add(member); ancestors(g, member, seen)
    return seen


def _members(g: Graph, node):
    lst = g.value(node, OWL.intersectionOf)
    if lst is None:
        return []
    from rdflib.collection import Collection
    return list(Collection(g, lst))


def category_of(g: Graph, node) -> set:
    """BFO ancestors of a class expression: for a restriction, of its filler's reach through the relation."""
    if isinstance(node, URIRef):
        return ancestors(g, node) | {node}
    if (node, RDF.type, OWL.Restriction) in g:
        prop = g.value(node, OWL.onProperty)
        if prop in ALLOWED:
            return {ALLOWED[prop][0]} | ancestors(g, ALLOWED[prop][0])
        return set()
    out = set()
    for m in _members(g, node):
        out |= category_of(g, m)
    return out


def structural(g: Graph, base: str, module: Graph) -> list[str]:
    """``g`` is the module merged with BFO (for ancestry); only the module's own
    classes and restrictions are checked, BFO's are taken as given."""
    problems = []
    classes = [c for c in module.subjects(RDF.type, OWL.Class) if isinstance(c, URIRef) and str(c).startswith(base)]
    for c in classes:
        labels = list(g.objects(c, RDFS.label))
        if len(labels) != 1:
            problems.append(f"{c.n3(g.namespace_manager)}: {len(labels)} labels")
        if g.value(c, DEFINITION) is None:
            problems.append(f"{c.n3(g.namespace_manager)}: no definition")
        anc = ancestors(g, c)
        if CONTINUANT not in anc and OCCURRENT not in anc:
            problems.append(f"{c.n3(g.namespace_manager)}: does not reach a BFO root")
        if CONTINUANT in anc and OCCURRENT in anc:
            problems.append(f"{c.n3(g.namespace_manager)}: both continuant and occurrent")
    for r in module.subjects(RDF.type, OWL.Restriction):
        prop = g.value(r, OWL.onProperty)
        if prop not in ALLOWED:
            problems.append(f"restriction on disallowed relation {prop}")
            continue
        subj_must, fill_must, name = ALLOWED[prop]
        filler = g.value(r, OWL.someValuesFrom) or g.value(r, OWL.allValuesFrom)
        fill_cats = category_of(g, filler) if filler is not None else set()
        if fill_must not in fill_cats and filler not in (None,) and not (isinstance(filler, URIRef) and filler == fill_must):
            problems.append(f"'{name}' filler {filler.n3(g.namespace_manager) if isinstance(filler, URIRef) else '(expression)'} is not under {fill_must.n3(g.namespace_manager)}")
        # The subject is whatever this restriction is a superclass (or intersection member) of.
        for subj in g.subjects(RDFS.subClassOf, r):
            if isinstance(subj, URIRef) and subj_must not in ancestors(g, subj):
                problems.append(f"'{name}' subject {subj.n3(g.namespace_manager)} is not under {subj_must.n3(g.namespace_manager)}")
    return problems


def reason(merged: Graph, base: str) -> list[str]:
    try:
        from owlready2 import get_ontology, sync_reasoner_hermit, default_world
    except ImportError as exc:
        return [f"owlready2 unavailable: {exc}"]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "merged.owl"
        merged.serialize(path, format="xml")
        onto = get_ontology(path.as_uri()).load()
        lines = []
        try:
            with onto:
                sync_reasoner_hermit(infer_property_values=False, debug=0)
        except Exception as exc:  # noqa: BLE001 - the reasoner reports inconsistency by raising
            return [f"reasoner: {exc.__class__.__name__}: {str(exc)[:300]}"]
        unsat = [c for c in default_world.inconsistent_classes()]
        lines.append(f"consistent: yes; unsatisfiable classes: {len(unsat)}")
        for c in unsat[:20]:
            lines.append(f"  unsatisfiable: {c.iri}")
        inferred = 0
        for c in onto.classes():
            if not c.iri.startswith(base):
                continue
            asserted = {str(p.iri) for p in c.is_a if hasattr(p, "iri")}
            for p in c.ancestors():
                if hasattr(p, "iri") and p.iri not in asserted and p is not c and p.iri.startswith(base):
                    inferred += 1
        lines.append(f"inferred module-internal superclass links not asserted: {inferred}")
        return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--base", default="http://purl.example.org/terms/")
    parser.add_argument("--no-reasoner", action="store_true")
    args = parser.parse_args()

    bfo = Graph(); bfo.parse(args.dir / "bfo-core.ttl", format="turtle")
    terms = Graph(); terms.parse(args.dir / "terms.ttl", format="turtle")
    merged = bfo + terms
    for prefix, ns in terms.namespaces():
        merged.bind(prefix, ns)
    n_classes = sum(1 for c in terms.subjects(RDF.type, OWL.Class) if isinstance(c, URIRef) and str(c).startswith(args.base))
    n_restr = sum(1 for _ in terms.subjects(RDF.type, OWL.Restriction))
    print(f"module: {n_classes} classes, {n_restr} restrictions; BFO core: {len(bfo)} triples")

    problems = structural(merged, args.base, terms)
    print(f"\nstructural problems: {len(problems)}")
    for p in problems[:40]:
        print("  -", p)
    if not args.no_reasoner:
        # Drop the import so the reasoner does not try to fetch BFO over the network; it is merged in.
        for onto in list(merged.subjects(RDF.type, OWL.Ontology)):
            merged.remove((onto, OWL.imports, None))
        print("\nreasoner:")
        for line in reason(merged, args.base):
            print("  ", line)
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
