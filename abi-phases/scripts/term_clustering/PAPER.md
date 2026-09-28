# From Extracted Claims to a BFO Ontology: Clustering the Semantics of a Research Corpus into Terms, Relations and Axioms

**Status:** working draft, maintained alongside the code in `abi-phases/scripts/term_clustering/`. Every section reports numbers from runs that can be reproduced with the commands in Appendix A. The changelog at the end records what changed and when.

**Corpus for this draft:** 26 papers on solitude and related constructs ingested by the HealthyPhases `phases_v2` pipeline (production snapshot of 24 September 2026), plus a three-paper sample of the same corpus for the frame-based pipeline.

## Abstract

Ontology building is usually top down: an ontologist reads a literature, decides which universals it refers to, and writes classes and axioms. We describe a bottom-up complement. Claims extracted from papers in a fixed logical form ("If X, then Y") are split into their halves, the halves are embedded and clustered, each cluster is proposed as a candidate universal and sorted under Basic Formal Ontology (BFO 2020), and the sentences that joined two halves become relations between clusters, written as BFO dispositions rather than as universal restrictions. On a 26-paper corpus the embedding space is not a continuous fog: 70 to 76% of points fall in clusters whose members read as one idea at every cluster size, and the strongest relations between clusters are findings the field already accepts. Splitting sentences into halves matters: 84 of 195 half-clusters are supported by six or more papers, against 31 of 162 sentence-clusters. A second source, claims already extracted as participant, process, direction and target process, needs no model to axiomatise and supplies the participant classes the first source lacks. A single-file, seven-slot frame pipeline generalises both: one extraction prompt lays each claim out as a relation between two frames, one slot per BFO bucket, and a structured definition (genus, typed differentiae, collective flag) mints the classes a definition refers to, so that "socially withdrawn child" becomes `child and 'bearer of' some 'social withdrawal'` with `child` and `social withdrawal` as classes. Every module produced is consistent under HermiT, passes structural BFO checks and converts without error in ROBOT. We also report what does not work: nearest-centroid assignment of new claims to existing terms is right 85 to 95% of the time when the concept exists but fails on novelty, so daily assignment must be provisional under periodic re-discovery; and an early attempt to carry direction inside disposition subclasses produced contradictory axioms and was replaced by naming the change as the target process.

## 1. Introduction

The HealthyPhases project extracts claims from the solitude literature with a set of prompts and stores them, with their embeddings, in a vector store for semantic search. Search answers "which claims are close to this one". The question addressed here is different: does the whole space of claims have dense regions that could be named, do those regions relate to each other, and can the result be written as an ontology under BFO with axioms that a reasoner can use?

The contribution is a pipeline with five fixed contracts (extract, vectorise, cluster, ontologise, repeat) and the empirical record of applying it. The method is generic: no domain vocabulary appears in code or prompts, and the only domain-facing surface is the extraction prompt. The output imports BFO 2020 core and nothing else. The paper is organised around the questions that were open when the work started and how each was settled.

## 2. Background

**BFO** is a top-level ontology of about three dozen classes and a small set of relations, standardised as ISO/IEC 21838-2. Its central distinction is between continuants (things that persist: independent continuants such as objects and sites, specifically dependent continuants such as qualities and realizables, generically dependent continuants such as information) and occurrents (processes and their boundaries, temporal regions). Its relations include *bearer of*, *inheres in*, *has realization*, *has participant*, *occurs in* and *has member part*. Domain ontologies in the OBO Foundry are built under it. Two BFO constructs do most of the work here: the **disposition**, a realizable entity whose realization is a process of a given type, which is the right way to state a tendency in a logic of universals; and the **process** as the category for changes in degree ("decrease in loneliness"), following the OBO convention rather than treating change as a comparison.

**Density clustering of embeddings** is the standard recipe for finding topics in embedded text: reduce with UMAP, cluster with HDBSCAN, describe with class-based TF-IDF. HDBSCAN is used because it does not force every point into a cluster; its noise label has a meaning here, "no term applies yet". BERTopic packages the same recipe; we did not use it, to keep every step visible and because the relation graph is not part of it.

## 3. Method

### 3.1 Sources of claims

The `phases_v2` pipeline asks eight questions per chunk of text. Two of them produce domain-free, claim-shaped output and are used here.

*Conditional statements.* Every item has the form "If X, then Y." with no pronouns referring outside the sentence. 9,414 of 9,417 items parse with a regular expression that splits at the last ", then". X and Y are the halves.

*Probabilistic processes.* Every item is a structured object: a participant, the subject process it takes part in, a direction (increases, decreases, no effect) and a target process. 3,624 items, all parseable. This is already the shape of a BFO disposition claim.

Both sources were extracted by two models (Claude Sonnet 4.6 via OpenRouter, GPT-4.1 mini); 142 of 1,129 chunk-and-prompt pairs were extracted by both, so about 4% of claims are exact duplicates. Support is therefore always counted in distinct papers, never in claims.

### 3.2 Halves are nodes, sentences are edges

Embedding a whole "If X, then Y." gives a blend of X and Y; two claims that share X but conclude differently land between their parts, and clusters blur. The halves are embedded separately (`text-embedding-3-large`, 3,072 dimensions, the corpus's own model), deduplicated on a normalised key, and the sentence is kept as the record that these two halves were joined in this direction by this paper. The corpus becomes a graph: halves are nodes, sentences are edges. The probabilistic-process items give the same graph with the participant attached to the edge.

### 3.3 Clustering

Vectors are scaled to unit length, reduced to 10 dimensions with UMAP (15 neighbours, `min_dist` 0, cosine metric) and clustered with HDBSCAN (minimum cluster size 15, excess-of-mass selection). A separate two-dimensional UMAP is used only to draw a map. Each cluster is described by class-based TF-IDF keywords (one document per cluster, common words and the prompt's hedges removed), its members nearest the centroid in the original space, its size, and the number of distinct papers behind it. Duplicate clusters are merged when their centroids exceed 0.90 cosine similarity, and an average-linkage tree over centroids proposes broader groupings.

### 3.4 Relations and direction

Sentences aggregated by (X-cluster, Y-cluster) give weighted, directed edges with claim and paper counts. Each supporting sentence is then classified on its own for what it says happens to Y as labelled (more likely, less likely, no effect, or nothing about likelihood) and for any qualifier it states. Direction is the majority; an edge is *contested* when a minority direction of at least 25% is backed by two or more papers. Qualifiers ("intrinsically motivated", "older adults") are recorded as candidate narrower terms. For the process items the direction is stated per claim and only needs counting.

### 3.5 From clusters to classes

For each cluster, a language model is asked the BFO sorting questions over the cluster's central members: is it a kind of thing in reality at all (as opposed to measurement talk or a comparison)? Does it unfold in time? Does it depend on a bearer, and if so is it a property always exhibited (quality) or a tendency (disposition), a status (role), a purpose (function)? Is it information? The answer gives the BFO parent, a label, an Aristotelian definition and a one-line rationale, all kept as annotations. A change in degree ("increase in X") is categorised as a process. Clusters judged to be measurement or method talk are set aside from the domain hierarchy.

### 3.6 From edges to restrictions

The shape of the claim picks a pattern:

| claim shape | axiom |
|---|---|
| tendency: X tends to lead to Y (a process) | `X SubClassOf 'has participant' some ('bearer of' some (disposition and 'has realization' only Y))`, with the chain starting at *bearer of* when X is an independent continuant and at *inheres in* when X is a quality |
| tendency whose target is a quality | the realization is the process in which a participant comes to bear the quality |
| X is a kind of Y, or X is defined as Y (same category) | `SubClassOf` or `EquivalentTo` |
| comparison, correlation, null finding, disagreement without a majority | evidence only, never a class axiom |

"X decreases Y" is written as "X makes *decrease in Y* more likely": the change is named as the target process and the direction annotation says "increases". A disposition cannot make its realization less likely, and an earlier design that carried direction in disposition subclasses ("probability decreasing disposition") produced contradictions whenever the target was itself a decrease (Section 5.4). Every axiom carries its support, direction, contested flag, qualifiers and the sentences as OWL axiom annotations; class expressions contain only BFO classes, BFO relations and the module's own terms.

### 3.7 Seven-slot frames

The frame pipeline (`frames.py`) generalises both sources into one extraction prompt. A claim is a relation between two frames; a frame has one slot per BFO bucket: the process (how it happens), participants (what and who), qualities of a participant (how they are), realizables of a participant (why they can), when, where, and information (how we know). The prompt decides roles only, never types. Every slot phrase is embedded and clustered within its role (paraphrase merge by average-linkage agglomeration at 0.20 cosine distance below 300 phrases, density clustering above; phrases with opposite degree words never share a cluster; the head noun's number is folded into the key). Each cluster is categorised once with its role as a prior the model may override. Restrictions then come from the frame structure without a model: `has participant` when a majority of a process's frames name the same participant kind, `occurs in` for places; qualified frames become defined subclasses (`process and 'has participant' some (participant and 'bearer of' some quality)`); relations between frames become dispositions as in 3.6.

### 3.8 Structured definitions

The categoriser returns, besides the definition sentence, a genus, typed differentiae (quality, realizable, life stage, location, member kind) and a collective flag. Each component is resolved to an existing class of its role by centroid similarity (0.80) or minted once, deduplicated by paraphrase, and becomes an axiom: `subClassOf` the genus; `'bearer of' some` for qualities and realizables of independent continuants; `'has member part' some` for collectives. Plural participants of a process are read as individuals; an aggregate is written only when the phrases name a group as such. The minted components form the corpus's own dictionary, typed by bucket, and are the natural input to grounding against reference ontologies.

### 3.9 Identities and decisions

Review work is only worth doing if it attaches to something that survives the next run. Cluster numbers do not: HDBSCAN reassigns them, and a new paper changes the partition. Each cluster therefore carries a term id reconciled against a registry of the previous run's terms: a cluster keeps the id of the registered term whose members overlap it most (Jaccard, or containment of the old term so that a term which grew still matches) when the overlap reaches 0.5, and gets a new content-derived id otherwise. The reconciliation report says what changed: matched, new, split (two clusters claim one old term; the better overlap keeps the id and the other is reported), merged (two old terms map to one cluster; the second is marked merged into the first), vanished (an old term matched by no cluster, kept in the registry with that status). Class IRIs are the term ids, so a class keeps its IRI across runs. Axioms get an id from their origin and their two ends. Classes minted from definitions and defined classes are derived from term ids, so they are stable when their components are.

A decisions file holds the outcome of review as rows of (target id, action, value): accept, reject, rename, recategorise, merge into another term; the last decision on a target wins. It is applied on every rebuild: a rejected term produces no class and no axiom; a renamed term keeps its old label as an alias; a recategorised term changes its BFO parent and therefore which patterns apply to it; a merged term redirects everything that referred to it to its target; a rejected axiom is not written; accepted items carry a status annotation. The registry and the decisions file together are the term registry that the operating model in Section 5.6 requires, in their simplest form.

### 3.10 Checks

Every module is checked structurally (every class reaches a BFO root and never both a continuant and an occurrent; every restriction uses an allowed relation with subject and filler on the sides BFO gives it), reasoned over with HermiT (consistency, unsatisfiable classes, inferred hierarchy) and converted with ROBOT, which also exercises OWLAPI's parser.

## 4. Experiments

### 4.1 Do the halves form clusters?

| variant | points | clusters | clustered | noise |
|---|---|---|---|---|
| whole sentences | 9,414 | 162 | 76% | 24% |
| halves | 15,597 | 195 | 70% | 30% |
| process phrases (subject and target) | 3,739 | 108 | 81% | 19% |
| participants | 1,047 | 41 | 85% | 15% |

Clusters read as one idea at every size, including the minimum size of 15 (one such cluster is the definitional term "solitude can be experienced in the presence of others"). Noise is one-off claims with no sibling in the corpus. A paper on smoking networks in the corpus formed its own clusters ("tobacco control", "smoking cessation") without disturbing the rest, which is the behaviour a multi-topic corpus needs.

Paper spread of clusters (one paper, two, three to five, six or more): sentences 39 / 43 / 49 / 31; halves 22 / 27 / 62 / 84. A whole sentence carries one paper's pairing of cause and effect; a half carries a concept many papers share.

Stability: three full runs with different seeds agree on 90 to 98% of the points they both cluster (adjusted Rand index 0.84 to 0.91). Each run leaves 30 to 34% as noise and only about 60% of points are clustered in every run: cluster cores are stable, cluster edges are soft.

### 4.2 Relations

Among the halves, 4,952 of 9,414 conditionals have both ends in a cluster, giving 1,145 distinct edges, 108 of them self-loops (definitional or measurement statements). Of the 1,037 cross-cluster edges, 211 are supported by two or more papers and 50 by three or more. The strongest are known findings: momentary solitude and low-arousal affect (7 papers, 66 claims); time alone and self-reflection or creativity (6); lack of social contacts and loneliness (4); shy or reticent children and peer rejection (4). Per-sentence voting over the 1,348 sentences behind the 211 edges found 12 contested edges and qualifiers on 162; "autonomy in solitude -> change in low-arousal affect" splits exactly on high versus low autonomy. Among the process items, 74% have both ends in a cluster, giving 756 edges, 166 with two or more papers; directions are stated in the items (2,441 increases, 970 decreases, 212 no effect).

A structural query over the edge graph finds divergences without a model: the same source with supported edges to opposite changes of one quality. On 26 papers there is one, and it is the field's central argument: spending time alone leads to a decrease in loneliness (2 papers, 6 claims) and to an increase in loneliness (2 papers, 4 claims).

### 4.3 Incremental assignment

Can papers ingested daily be attached to existing terms without re-clustering? The 26 papers were put in a fixed random order; the first 16 were clustered once into 162 terms (a centroid, a radius from the members' spread, a member list), covering 65% of the concepts the full corpus ends up with; the remaining 10 papers arrived one at a time and each new half was assigned to a term or pooled. Decisions were scored against the full 26-paper clustering.

| rule | assigned | precision | recall |
|---|---|---|---|
| centroid, 90th-percentile radius | 3,057 | 56% | 64% |
| centroid, maximum radius | 4,799 | 47% | 87% |
| centroid, radius plus 0.05 margin over the runner-up | 1,585 | 72% | 42% |
| 8 of 10 nearest members agree | 1,690 | 65% | 42% |
| fixed cosine distance 0.15 | 184 | 86% | 7% |

Every rule sits on one curve; the member vote does not beat the centroid and moving centroids changes nothing. The dominant error is *absorbed*: a half whose concept has no term yet is assigned to the nearest existing term. Among halves whose concept has a term, assignment is right 85 to 95% of the time. Novelty detection is the failure mode, and novelty is a function of coverage. Discovery on the pool alone recovers a third of the missing concepts and re-creates fragments of existing terms; clustering the pool with a 30% sample of existing members lets 30 fragments attach, recovery stays at a third.

### 4.4 Ontology proposals from the halves

Three runs on 195 clusters and the 50 relations with three or more papers (GPT-4.1):

| | strict (A) | change as process (B) | plain BFO (C) |
|---|---|---|---|
| domain entities | 98 | 142 | 142 |
| set aside (comparative / measurement / other) | 65 / 28 / 4 | 24 / 27 / 2 | 23 / 28 / 2 |
| axioms | 2 | 24 | 24 |
| structural problems / consistent / ROBOT | 0 / yes / 0 | 0 / yes / 0 | 0 / yes / 0 |

The difference between A and B is one modelling decision. In this corpus the consequent of a claim is very often a change in degree; A treats those clusters as comparisons and sets them aside, so 40 of the 50 relations have no class at one end and 6 more target a quality; B models "increase in X" as a process. C is B with the disposition subclasses removed (Section 5.4); its 24 axioms are all dispositions, three of them flagged contested where the sentences disagree.

### 4.5 Two sources combined

Merging clusters, aligning the halves and the process phrases by centroid similarity (16 concepts found by both, e.g. "spending time in solitude" and "spending time alone"), voted directions for the conditionals and structure-derived axioms for the process items give a module of 263 canonical terms, 293 classes including 30 proposed parents from the hierarchy, 206 axioms (112 from process items, 73 from conditionals at two or more papers, 21 participant restrictions such as "aging has participant some older adult", 72 of 83 items, 9 papers), 99 evidence-only relations and 34 divergences. Consistent, structurally clean, ROBOT-clean.

### 4.6 Frames on a three-paper sample

Three mid-sized papers (55 chunks) yielded 355 claims (6.5 per chunk, GPT-4.1, about 1.50 USD including categorisation).

| role | filled | distinct phrases | classes |
|---|---|---|---|
| process | 100% | 453 | 28 |
| participant | 100% | 56 | 11 |
| information | 43% | 85 | 7 |
| when | 27% | 56 | 9 |
| quality | 11% | 50 | 2 |
| where | 5% | 14 | 0 |
| realizable | 2% | 23 | 1 |

Module: 85 classes (58 from clusters, 5 defined from qualified frames, 22 minted from definitions), 8 participant restrictions, 22 definitional axioms, 73 relation axioms, 13 refused for stated reasons (null findings, mere co-occurrence, a role as realization target); 0 structural problems, consistent, ROBOT-clean. The minted classes are `human`, `child`, `adult human`, `toddler or baby`, `solitude experience`, `experimental method`, and the qualities the participants bear (`social withdrawal`, `shyness`, `behavioral inhibition`, `autonomy`, life stages); the axioms include `'older adult' SubClassOf 'human'` and `'bearer of' some 'older adulthood'`, `'socially withdrawn child' SubClassOf 'child'` and `'bearer of' some 'social withdrawal'`.

### 4.7 Frames on ten papers

Ten mid-sized papers spread across the corpus (183 chunks) yielded 1,096 claims (6.0 per chunk, about 6 USD). The fill profile is the same as on three papers: process and participant 100%, information 40%, when 24%, quality 13%, where 4%, realizable 2%. Relation kinds: 993 tendencies, 30 is-a, 24 definitions, 48 co-occurrences, 1 causal; directions after the decrease rewrite: 911 increases, 113 none, 71 no effect.

Module: 242 classes (195 from clusters, 15 defined from qualified frames, 32 minted from definitions), 60 definitional axioms, 24 participant and place restrictions, 230 relation axioms at one paper of support, 64 refused with reasons; 0 structural problems, consistent, no unsatisfiable class, ROBOT-clean. HermiT infers 69 module-internal superclass links that were not asserted, which is the definitions doing their work: the genus chains (`human`, `child`, `person`, `human adult`, `human child`) and the `bearer of` differentiae let the reasoner place qualified participants under their kinds.

Three defects appeared only at this scale and were fixed before the numbers above. A state extracted into the process slot ("having high shyness", "being socially anxious") is typed by the categoriser as a quality or a disposition; treating it as a process with participants made 23 defined classes unsatisfiable, so such classes now carry tendencies only through their bearer and get no defined subclass. Minted components lacked the polarity guard the clusters have, so "high aloneliness" and "low aloneliness" had merged into one quality. And a genus was minted in the slot's bucket rather than the class's category, producing "autonomy" both as a process and as a quality.

### 4.8 Frames on the whole local corpus

All 26 papers (499 chunks after the length filter) yielded 3,092 claims (6.2 per chunk, about 25 USD). The fill profile held for the third time: process and participant 100%, information 40%, when 21%, quality 13%, where 4%, realizable 2%. Relation kinds: 2,846 tendencies, 67 is-a, 59 definitions, 112 co-occurrences, 8 causal; directions 2,599 increases, 264 none, 221 no effect.

Module: 770 classes (549 from clusters, 126 defined from qualified frames, 95 minted from definitions), 214 definitional axioms, 74 participant and place restrictions, 777 relation axioms at one paper of support, of which 17 have three or more papers and 74 have two, 148 refused with reasons; 0 structural problems, consistent, no unsatisfiable class, ROBOT-clean.

A first build of this module wrote every `is_a` and `defines` claim as a `SubClassOf` or `EquivalentTo` axiom at one paper of support, and HermiT then inferred 553 module-internal superclass links. Reading one class showed why: "social withdrawal" had become equivalent to its own qualified subclass and a subclass of "overcontrolling parenting", each on the strength of one claim. A tendency at one paper is harmless as a disposition; a hierarchy or an equivalence at one paper is not. Both patterns now require two papers and are never written toward a process's own qualified subclass; 29 claims were held back as evidence and the inferred links fell to 32. The number of inferences a reasoner draws is not a quality measure on its own; where they come from is. Participants give 107 classes under a minted genus set (`human`, `child`, `adolescent`, `adult human`, `human child`, `human male`, `human female`, `person`); the time slot gives 67 temporal-region classes ("older age", "early adolescence", "later life", "solitude period"); the information slot gives 68 (self-report, experience sampling, correlation analysis, named scales). The strongest relations are the field's known results: solitude leads to a decrease in high-arousal and in positive affect (four and five papers), to relaxation and calm (three), to low-arousal negative affect (three); social withdrawal leads to negative self-perception of social competence, peer exclusion and victimization, and psychological maladjustment (three each); a limited future time perspective leads to prioritising emotionally meaningful social partners (three).

Two scale defects appeared and were fixed. Qualifiers repeated inside a defined class when several spans of one frame fell in the same quality cluster; they are now a set. And density clustering over-merged roles with a few hundred phrases (526 participant phrases became 42 clusters, 311 time phrases became 8), so paraphrase agglomeration now stays in charge up to 2,000 phrases per role and density is used only for the process role (3,550 phrases, 240 clusters).

At this scale the support distribution is the practical finding: 91 relation axioms have two or more papers behind them, which is the size of a reviewable core, while 715 single-paper relations are evidence to keep and to revisit as papers accumulate.

### 4.9 Do identities survive a rebuild?

The 26-paper module was built twice from the same cached extraction and embeddings, with the registry created by the first pass. The first pass minted 1,956 term ids (one per cluster in every role, including clusters too small to become classes: 240 process, 408 participant, 384 quality, 147 realizable, 203 when, 86 where, 488 information). The second pass kept 1,956 of 1,956 ids, with 0 new, 0 split, 0 merged and 0 vanished, and produced an identical module: 770 classes, 550 of them cluster classes carrying a term id, 948 axioms carrying an axiom id, 0 structural problems, consistent.

A decisions file with five rows (accept a term, rename one, recategorise "participant" from material entity to role, reject the term "researcher", reject one relation axiom) was then applied on a third rebuild. The five intended effects appeared: a status annotation on the accepted term, the old label kept as an alias on the renamed one, the recategorised term under BFO role, the rejected term and the rejected axiom absent. The demo also surfaced two defects that only a decision could reveal. The recategorisation made one class unsatisfiable: "participant in positive group" had `SubClassOf 'participant'` from its definition's genus and was itself a material entity, and once "participant" became a role the class was both an independent and a specifically dependent continuant, which BFO makes disjoint. The genus check had compared only continuant against occurrent; it now requires the same BFO family (independent, dependent, information, process, region), which also removed three cross-family genus links the earlier module carried. And the rejected axiom left its class expression behind as an orphaned intersection that OWLAPI could not parse; expressions are now removed when the axiom they were built for is refused. After both fixes the module with decisions is consistent, structurally clean and ROBOT-clean. Identical rebuilds are the easy case; the informative case, a rebuild after new papers arrive, is what the next corpus run will measure through the reconciliation report.

## 5. Discussion

### 5.1 The space has islands, and the split is what makes them terms

The first question, whether the embedding space would be a continuous fog, was answered on the first afternoon: it is not, and the fixed claim form is the reason. Phrasing is a constant within a prompt, so only meaning can separate points. The second finding is that splitting a sentence is not a detail. Halves cluster almost as well as sentences and generalise across papers far better, and the sentence becomes an edge. The same move, one level down, is what the frames do to a half: a participant and a process embed as a blend until they are separated.

### 5.2 Tendencies belong to dispositions

Most extracted claims are statistical tendencies. An OWL restriction is universal: `X SubClassOf r some Y` says every X, and a reasoner would draw false conclusions from it. The disposition pattern states that bearers of X bear a disposition realized only in Y; every bearer has it, not every disposition is realized. This is reasoner-safe and it is exactly what the probabilistic-process prompt had been asking for since it was written.

### 5.3 Change in degree decides the tendency layer

A third of the half-clusters and 40 of the 50 strongest relations involve a change in degree. Modelling "increase in X" as a process, as OBO ontologies do, is what turns two axioms into twenty-four. The decision is an ontological one and is recorded as such; the strict run remains available as the baseline that shows what the corpus supports without it.

### 5.4 A mistake worth recording

The first module carried direction inside two invented disposition subclasses, "probability increasing" and "probability decreasing". "Increasing" is what any disposition already does, so the subclass added a label and no meaning; "decreasing" is incoherent as a disposition realized in its target and, when the target was itself a "decrease in X" process, produced axioms that said the opposite of the claim. Direction now lives in the target process class and in an annotation; a "decreases" claim without such a target stays evidence.

### 5.5 Disagreement is an output

The contested flag, the qualifier votes and the opposite-target query make divergence a first-class product. Its head on 26 papers is the field's central argument with the papers counted on each side. Most flagged disagreements are not contradictions but moderation: the qualifiers say which condition separates the two directions, and those conditions are the narrower classes the ontology is missing. At the scale of hundreds of papers, the divergence map is likely the most useful output for researchers.

### 5.6 What repeating on new text means

Assignment of new halves to known terms is reliable; recognising that a half belongs to no known term is not. This settles the operating model: daily assignment is provisional, periodic re-discovery with identifier reconciliation is the authority, and human decisions attach to term identifiers that survive re-clustering. Reading a new document against the axioms of the terms it lands in is what turns the ontology into a checklist: a process expects participants and a time, a quality a bearer, a disposition a realization; an empty slot is a gap and an opposite direction is a divergence.

### 5.7 Why not a dictionary

A compound term such as "older adult human population" must decompose for the hierarchy to appear, and it was tempting to embed a dictionary to obtain the components. Clustering dictionary entries yields lexical neighbourhoods with no evidence behind them, and single words embed on a different footing from claim fragments. The structured definition does the decomposition with types: it knows which word is the genus, which is a value the bearer has, which is a collective marker. The minted components are the corpus's dictionary, and reference ontologies already under BFO are where they should be grounded.

## 6. Limitations

- Corpus size. Twenty-six papers is a small sample; cluster size reflects how much one group wrote, and "seven papers" is still a small number. The 30% noise is partly corpus size and will shrink.
- Models in the loop. Categorisation and pattern choice are model proposals with rationales, not decisions. Every proposal is traceable to sentences and papers so that review is cheap; it does not disappear.
- Clusters are density, not genus. The hierarchy, the merges and the cross-source alignments are proposals; a few alignments are near rather than identical.
- Frames fill unevenly. Papers state who takes part and, less often, how they know and when; qualities, realizables and places are rarely explicit. Those buckets stay thin until the corpus is large or grounding supplies them.
- Locations are noted, not axiomatised: BFO core relates a continuant to a site only through its history, and the extracted phrases are too coarse for regions.
- Human review. The reviewed core grows as fast as ontologists review it; acceptance rate per run is the metric that has not yet been measured.

## 7. Future work

1. Run the frame pipeline on ten papers, then on the 200-plus paper corpus after the extraction prompt fix (explicit subjects in consequents, PR #85) is deployed; replay the incremental test at that scale.
2. Ground minted components against reference ontologies under BFO (taxa for organisms, PATO for qualities, OBO process ontologies, IAO for information) by embedding their labels and definitions and matching with category agreement.
3. The term registry: stable identifiers, provisional daily assignment, periodic re-discovery with reconciliation by member overlap, named terms flagged on split or merge.
4. The review application: name a cluster as a term, build its definition iteratively from members, accept or reject the category and the axioms, see the divergence map.
5. Gap detection for new documents against the axioms of the terms they land in.
6. Measure review acceptance per run.

## Appendix A. Reproducibility

Scripts live in `abi-phases/scripts/term_clustering/` on branch `feat/phases-v2-term-clustering`. Each carries its own dependencies and runs with `uv run`; data lands in the gitignored `storage/spikes/term_clustering/`. The README records every run's numbers; `PIPELINE.md` explains the mechanism.

| step | script |
|---|---|
| copy the vector store | `dump_vectors.py --host <qdrant>` |
| conditionals into halves | `split_conditionals.py` |
| process items into phrases | `split_processes.py` |
| embed a phrase table | `embed_parts.py --input <table>` |
| cluster, describe, term graph | `cluster.py --variant <table>` |
| merges and hierarchy | `hierarchy.py --variant <table>` |
| per-sentence direction votes | `vote_directions.py --min-papers 2` |
| incremental replay | `incremental.py --initial-papers 16` |
| seed stability | `stability.py --seeds 42 1 2` |
| module from halves | `bfo_proposal.py --quality-change-as-process` |
| module from both sources | `bfo_module.py --min-papers 2` |
| frames, end to end | `frames.py --papers 3 --run s3` |
| structural checks and HermiT | `bfo_check.py --dir <output>` |
| unit tests (40) | `pytest scripts/term_clustering/tests -q` with the dependencies listed in the README |

Parameters: `text-embedding-3-large` at 3,072 dimensions; UMAP 10 dimensions, 15 neighbours, `min_dist` 0, cosine, seed 42; HDBSCAN minimum cluster size 15 (10 for process phrases, 8 for participants, 5 in the frame pipeline with agglomeration at 0.20 below 300 phrases); merge threshold 0.90; alignment threshold 0.90; component resolution 0.80; categorisation and axiomatisation with GPT-4.1 at temperature 0 and strict JSON schemas; direction votes with GPT-4.1 mini. BFO 2020 core from its PURL; ROBOT for conversion; HermiT via Owlready2.

## References

- Arp, R., Smith, B., Spear, A. D. *Building Ontologies with Basic Formal Ontology.* MIT Press, 2015.
- ISO/IEC 21838-2:2021. Information technology, Top-level ontologies, Part 2: Basic Formal Ontology (BFO).
- Smith, B. et al. The OBO Foundry: coordinated evolution of ontologies to support biomedical data integration. *Nature Biotechnology* 25, 1251–1255 (2007).
- McInnes, L., Healy, J., Melville, J. UMAP: Uniform Manifold Approximation and Projection for Dimension Reduction. arXiv:1802.03426 (2018).
- Campello, R. J. G. B., Moulavi, D., Sander, J. Density-Based Clustering Based on Hierarchical Density Estimates. *PAKDD* 2013.
- McInnes, L., Healy, J., Astels, S. hdbscan: Hierarchical density based clustering. *Journal of Open Source Software* 2(11), 205 (2017).
- Grootendorst, M. BERTopic: Neural topic modeling with a class-based TF-IDF procedure. arXiv:2203.05794 (2022).
- Jackson, R. C. et al. ROBOT: A tool for automating ontology workflows. *BMC Bioinformatics* 20, 407 (2019).
- Glimm, B., Horrocks, I., Motik, B., Stoilos, G., Wang, Z. HermiT: An OWL 2 Reasoner. *Journal of Automated Reasoning* 53, 245–269 (2014).
- Lamy, J.-B. Owlready: Ontology-oriented programming in Python with automatic classification and high level constructs for biomedical ontologies. *Artificial Intelligence in Medicine* 80, 11–28 (2017).
- Priem, J., Piwowar, H., Orr, R. OpenAlex: A fully-open index of scholarly works, authors, venues, institutions, and concepts. arXiv:2205.01833 (2022).

## Changelog

- 2026-09-24. Conditionals split into halves, embedded, clustered; term graph; results page. Finding: islands, not fog; halves beat sentences.
- 2026-09-25. Prompt fix for explicit subjects (PR #85). Incremental replay and seed stability: assignment reliable for known concepts, novelty is the failure mode. BFO proposals A, B, C; disposition subclasses introduced and then removed; plain-BFO module; OWLAPI-clean serialisation; ROBOT and Protégé audit.
- 2026-09-28. Process items as a second source; merges and hierarchy; per-sentence direction votes; two-source module v2 (263 terms, 206 axioms, 34 divergences). Frames pipeline in one file, sample-tested on three papers; sampler, paraphrase merge, plural folding, decrease rewriting, polarity guard, content-keyed cache; structured definitions mint referenced classes. First draft of this paper.
- 2026-09-28, later. Frames on ten papers (Section 4.7): 242 classes, 230 relation axioms, clean. Fixes: states in the process slot get no defined subclass; polarity guard on minted components; genus minted in the class's category.
- 2026-09-28, evening. Frames on all 26 local papers (Section 4.8): 770 classes, 777 relation axioms (91 with two or more papers), clean. Fixes: qualifiers deduplicated in defined classes; agglomeration up to 2,000 phrases per role; hierarchy and equivalence axioms gated at two papers (29 held back; inferred links from 553 to 32).
- 2026-09-28, night. Identities and decisions (Sections 3.9 and 4.9): term ids reconciled by member overlap, class IRIs are term ids, axiom ids, a decisions file applied on rebuild. Identical rebuilds keep 1,956 of 1,956 ids; a five-row decisions file has exactly its five effects. The categoriser's confidence is annotated as `modelSelfConfidence`.
