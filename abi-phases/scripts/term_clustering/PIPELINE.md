# From text to a BFO ontology: how the pipeline works

This note explains the mechanism behind the term-clustering scripts: how a
sentence becomes nodes and an edge, why a cluster is a candidate universal,
how edges become relations, how both become BFO classes and restrictions, and
what "repeat on new text" means. It ends with the design for the next step,
seven-bucket frames, and why a dictionary is not the way to get there.

The running example is one real sentence from the corpus:

> If adolescents engage in intrinsically motivated solitary activities, then
> they tend to report lower feelings of aloneliness.

## 1. A sentence becomes one edge and two nodes

The extraction prompt forces the "If X, then Y." shape, so the split is
mechanical:

- X = "adolescents engage in intrinsically motivated solitary activities"
- Y = "they tend to report lower feelings of aloneliness"

Each half is embedded on its own (3,072 numbers, `text-embedding-3-large`).
The sentence is kept as the record that these two halves were joined, in this
direction, by this paper.

That is the whole trick: **halves are nodes, sentences are edges.** Before the
split, a sentence embedding was a blend of X and Y. After it, X can sit next
to other phrasings of adolescent solitude and Y next to other phrasings of
loneliness going down, and the link between them is not lost.

The probabilistic-process items are the same idea with more structure. The
extraction already produced a participant, a subject process, a direction and
a target process, so each item is an edge with its direction and its bearer
attached, and no regex is needed.

## 2. A cluster is a candidate universal

In the vector space, halves that mean the same thing land close together
regardless of wording: "adolescents engage in solitary activities",
"adolescents spend time alone", "young people seek solitude". HDBSCAN finds
regions that are dense relative to their surroundings and calls each region a
cluster. Halves in no dense region stay unassigned. We call that noise and
read it as "no term applies yet".

A cluster is therefore a set of paraphrases of one idea, with:

- a centroid (the average vector: where the idea lives);
- members (the paraphrases, each traceable to a paper and a chunk);
- support (distinct papers; cluster size counts paraphrases and is not a
  measure of anything);
- keywords and central examples (handles for a human, not names).

Nothing about the domain is used. The code that found "behavioral inhibition"
also found "tobacco control" for the one smoking paper in the corpus.

Two things density does not give: near-duplicate clusters that should be one
term, and broader terms that group narrower ones. `hierarchy.py` proposes
both from centroid geometry (merges above a similarity threshold, an
average-linkage tree cut at fixed distances). They are proposals; the
reviewer decides.

## 3. Edges between clusters come from the sentences

Every sentence connects the cluster of its X to the cluster of its Y.
Aggregating all sentences by (X-cluster, Y-cluster) gives a weighted, directed
graph over clusters:

```
[adolescent engagement in solitude]  --8 claims, 3 papers-->   [decrease in loneliness]
                                     --12 claims, 3 papers-->  [change in affect]   (contested)
```

The per-sentence votes (`vote_directions.py`) add the last two pieces. Each
sentence is classified on its own: what it says happens to Y as labelled
(more likely, less likely, no effect, or nothing about likelihood), and any
qualifier it states ("intrinsically motivated", "older adults"). An edge is
contested when a minority direction of at least 25% is backed by two or more
papers. The qualifiers are the candidate narrower terms that would resolve
the disagreement: "autonomy in solitude -> change in low-arousal affect"
splits exactly on high versus low autonomy.

## 4. Clusters become classes, edges become restrictions

**Cluster to class.** For each cluster, the BFO sorting questions are asked
over its central members: is it a kind of thing in reality at all (as opposed
to measurement talk or a comparison)? Does it unfold in time (process)? Does
it depend on a bearer (a quality, or a realizable: disposition, role,
function)? Is it information? Otherwise it is an independent continuant. The
answer gives the parent (`rdfs:subClassOf` a BFO category), a label, an
Aristotelian definition and a one-line rationale. All of it is a proposal
with the cluster's evidence attached.

**Edge to restriction.** The shape of the claim picks a pattern. The pattern
that matters most is the tendency:

```
'adolescent engagement in solitude' SubClassOf
    'has participant' some ('bearer of' some
        (disposition and 'has realization' only 'decrease in loneliness'))
```

Read: whoever takes part in adolescent solitude bears a disposition that, if
realized, is realized in a decrease of loneliness. Every participant has the
disposition; not every disposition is realized. This is what lets a
statistical tendency live inside a logic that only knows universals, and why
a reasoner cannot derive "every solitary adolescent becomes less lonely" from
it.

The other patterns: definitional claims become plain `SubClassOf` or
`EquivalentTo`; a consistent participant becomes `'has participant' some
<kind>`; a quality becomes `'bearer of' some <quality>`. Comparisons, null
findings and contested claims without a majority stay in the evidence layer
as annotations, never as class axioms.

Every axiom carries its support (papers, claims), its direction, its contested
flag, its qualifiers and the sentences themselves, as OWL axiom annotations.
An ontologist can audit it; a reasoner ignores it. Class expressions contain
only BFO classes, BFO relations and the module's own term classes.

## 5. The generic pipeline as five contracts

The five stages map onto the five goals of the project. What makes the
pipeline generic is that each stage has a fixed contract and nothing
domain-specific lives between them.

| stage | in, out | what it must guarantee |
|---|---|---|
| extract | text, claims in a fixed shape ("If X, then Y" or participant / process / direction / process) | self-contained claims, explicit subjects, provenance (paper, chunk, model, prompt id) |
| vectorise | claim parts, vectors | one embedding model for everything that will ever be compared; parts embedded separately |
| cluster | vectors, clusters plus noise, with support | density-based, noise allowed, distinct papers as support, stable ids |
| ontologise | clusters and edges, BFO classes and restrictions with evidence | only BFO categories and relations in class expressions; tendencies as dispositions; everything else as annotations; reasoner-checked |
| repeat | new claims and existing terms, assignments and an updated registry | provisional assignment, periodic re-discovery, ids never silently change |

The only surface that touches the domain is the extraction prompt. The two
prompts that matter (conditionals and probabilistic processes) are themselves
domain-free. Swap the corpus and the same pipeline produces a different
ontology.

## 6. Repeating on new text, and what "missing" means

When a new paper arrives, its claims are extracted and split as before, and
each half is placed against the existing terms (nearest centroid within the
term's radius, or a vote among nearest members). Three things can happen to a
half, and each is information:

1. **It lands in a term.** The paper is now evidence for that term and for
   the edges its sentences form. Support counts update; a contested edge may
   settle, or a settled one become contested.
2. **It lands nowhere.** It waits in the pool. Periodic re-discovery either
   finds it siblings (a new term) or leaves it as noise.
3. **It lands in a term whose axioms it does not satisfy.** This is where the
   ontology pays for itself. If the new text says "engagement in solitude
   reduced depressive symptoms" and the term `engagement in solitude`
   carries `'has participant' some 'adolescent'`, the pipeline can ask
   whether the new text names a participant at all, and of what kind. No
   participant is a gap to fill. "Older adults" is either a new sibling term
   or a reason to generalise the parent. If the term's disposition is
   realized in `decrease in loneliness` and the new text claims an increase,
   that is a divergence, and the qualifiers show whether a condition
   explains it.

Each BFO category brings its own expectations: a process expects
participants and a time; a quality expects a bearer; a disposition expects a
realization; a role expects a context; information expects what it is about.
Sorting a new term into its bucket is what tells you which of those the text
must supply and which it has not.

So the ontology does two jobs: it is the map of what the corpus knows, and
its axioms are the checklist a new document is read against.

The incremental replay (`incremental.py`) measured the assignment half of
this: 85 to 95% right when the concept already has a term, with novelty as
the failure mode. That is why daily assignment is provisional and periodic
re-discovery with id reconciliation is the authority.

## 7. Limits

- The pipeline proposes; the reviewed core grows as fast as ontologists
  review it. Everything is traceable so that review is cheap.
- Clusters are density, not genus. The hierarchy and the merges are
  proposals.
- Tendencies are only as good as the direction votes. Where the corpus
  disagrees, the ontology records the disagreement rather than resolving it.
- Coverage is the corpus's coverage. A new field arrives as a wave of "lands
  nowhere" until re-discovery runs.
- Gap detection (6.3) is designed, not built. It needs the term registry and
  the assignment step, both specified in the README.

## 8. Next: seven-bucket frames, not a dictionary

The goal is a complete BFO description of each process: what and who are the
materials, how they are is their qualities, why they can do something is
their realizables, how it happens is the process, when and where are time and
space, and how we know is the information. Today the module has the process
and often the participant, rarely the rest. Two ways to fill the gap were
considered.

**Embedding the English dictionary does not help.** Clustering dictionary
entries produces lexical neighbourhoods (synonyms and near-synonyms), not
universals in a domain: "adolescent" would cluster with "teenager" and
"youth", which is a thesaurus entry, not a class with evidence behind it. A
dictionary has no support, no papers, no claims, and single words embed on a
different footing from claim fragments, so mixing the two spaces would
degrade the clusters we have. Ontologies are built from the universals a
domain's claims refer to, not from the words a language has.

**Frames at extraction time do help.** The reason `adolescent engagement in
solitude` has no `adolescent` participant is that the conditional extraction
keeps the participant inside X. The probabilistic-process prompt already
pulls the participant out, and that is exactly why the v2 module has
`'aging' SubClassOf 'has participant' some 'older adult'`. Generalise that:
ask the extractor for a frame per claim with one slot per bucket.

| bucket | slot | BFO target | relation to the process |
|---|---|---|---|
| what and who | participants | material entity (organism, group, artefact) | `has participant` |
| how they are | qualities of the participants | quality | `bearer of` (on the participant) |
| why they can | realizables | disposition, role, function | `bearer of`, `has realization` |
| how it happens | the process itself | process | the frame's subject |
| when | temporal context | temporal region | `occupies temporal region` |
| where | site or location | site, spatial region | `occurs in` |
| how we know | the source and the measure | information content entity | `is about` |

Each slot phrase is embedded and clustered within its bucket, so "adolescent"
becomes a material-entity term with the papers that mention it, "high
autonomy" a quality term, "preference for solitude" a disposition term, and
the frame's slots become the restrictions on the process class. An empty slot
is then a concrete statement of what the corpus does not say about that
process, which is the gap report in section 6 made routine.

**Reference ontologies are the right place for the dictionary idea.** Once
slot terms exist, they should be grounded against vocabularies that are
already under BFO: taxon and anatomy for organisms, PATO for qualities, the
OBO process ontologies where they apply, IAO for information. Embedding
those terms' labels and definitions and matching clusters to them by
similarity plus category agreement reuses IRIs that come with agreed
definitions. That is the productive version of "embed all the terms": embed
the terms of ontologies that already sort things into the seven buckets, not
the words of a language. A lexical resource such as WordNet can still supply
synonyms as alternative labels, and nothing more.

Concretely: one new extraction prompt (the frame), the same embed, cluster
and categorise steps per bucket, restrictions generated from slots instead of
guessed from definitions, and a grounding step against reference ontologies.
None of it changes the contracts in section 5. `frames.py` is that pipeline
in one file; its README section records the first sample.

**Structured definitions are where the decomposition happens.** A compound
term such as "older adult human population" is a genus plus components:
genus *human*, a life-stage differentia *older adulthood*, and, only when the
claims are about the group as such, a collective marker with a member kind.
The categoriser now returns those components typed, and each one is resolved
to an existing class of its role or minted once, so `human` becomes one class
that every participant definition points at, and the axioms follow:

```
'older adult'              SubClassOf 'human', 'bearer of' some 'older adulthood'
'socially withdrawn child' SubClassOf 'child', 'bearer of' some 'social withdrawal'
'older adult population'   SubClassOf 'object aggregate', 'has member part' some 'older adult'
```

That set of minted components is the corpus's own dictionary, built with
evidence and typed by bucket. It is what a dictionary of English cannot give
(which of the four words is the genus, which the value, which the collective
marker) and it is what the grounding step maps to reference ontologies.
Plural participants of a process are read as individuals; an aggregate is
written only when the phrases name a group.
