# Term clustering spike

Question: do the embedded extractions form clusters dense enough to be named as
terms, and do those clusters relate to each other in a way an ontology could
use? This directory is the throwaway experiment that answers it before any
domain code is written. Nothing here is imported by the application.

The corpus is the `phases_v2_extracted_items` collection, restricted to the
conditional statements (`conditional_statement` and its earlier name
`logical_sentences`): every item has the form "If X, then Y.", so phrasing is
constant and only meaning can separate the points.

## Run

All scripts carry their own dependencies (PEP 723), so `uv run` needs no
project sync. Data lands in `storage/spikes/term_clustering/`, which is
gitignored.

```sh
# 1. Copy the vectors and payloads out of the production Qdrant (once).
uv run scripts/term_clustering/dump_vectors.py --host <qdrant host>

# 2. Select the "If X, then Y." items and split them.
uv run scripts/term_clustering/split_conditionals.py

# 3. Embed the distinct antecedents and consequents (same model as the corpus).
#    uv's --env-file cannot parse this repo's .env, so pass the key directly.
OPENAI_API_KEY=$(grep -E '^OPENAI_API_KEY=' .env | tail -1 | cut -d= -f2-) \
  uv run scripts/term_clustering/embed_parts.py

# 4. Cluster. `sentences` reuses the corpus vectors; `parts` uses step 3.
uv run scripts/term_clustering/cluster.py --variant sentences parts --min-cluster-size 15
```

Step 4 writes `report_<variant>_mcs<k>_umap<d>.md` (stats, term graph, one
section per cluster with keywords and the most central members) and an
`assignments_*.parquet` with a cluster label, membership probability and 2-D
map coordinates per point.

## Method

L2-normalise, UMAP to 10 dimensions (cosine), HDBSCAN. HDBSCAN is used on
purpose: it does not force every point into a cluster, so "no term applies"
shows up as noise instead of being hidden in a bad cluster. Keywords are
class-based TF-IDF (one document per cluster). Representative members are the
ones nearest the cluster centroid in the original embedding space.

In the `parts` variant each cluster is a candidate term and each conditional is
an edge from its antecedent's cluster to its consequent's cluster; the report
lists the most frequent edges with the number of distinct papers behind them.

## Results (2026-09-24, production corpus)

Corpus: 33,333 items from 26 papers; 9,414 conditionals parsed ("If X, then
Y."), 7,121 distinct antecedents and 8,478 distinct consequents. Two models
extracted the corpus (`claude-sonnet-4.6`, `gpt-4.1-mini`); 142 of 1,129
chunk/prompt pairs were extracted by both, so about 4% of sentences are exact
duplicates. Defaults: UMAP 10-d, HDBSCAN `min_cluster_size=15`.

| variant | points | clusters | clustered | noise |
|---|---|---|---|---|
| sentences | 9,414 | 162 | 76% | 24% |
| parts | 15,597 | 195 | 70% | 30% |

The space is not a continuous fog: three quarters of the points sit in
clusters whose members read as one idea, and this holds for the smallest
clusters (n=15) as well as the largest. Examples of part clusters: "autonomy
in solitude", "behavioral inhibition in toddlers", "increasing social
withdrawal trajectory", "low-arousal positive affect", "6-item loneliness
scale", "solitude can be experienced in the presence of others". Some
clusters are methodological ("model fit indices", "multilevel models with
covariates", "correlation strength"); they are coherent but are terms of a
different kind and would need their own flag.

Paper spread of sentence clusters: 39 from a single paper, 43 from two, 49
from three to five, 31 from six or more. A paper about smoking networks in
the corpus formed its own clusters ("tobacco control", "smoking cessation"),
which is what a multi-topic corpus should do.

Term graph (parts variant): 4,952 of 9,414 conditionals have both ends in a
cluster. 108 edges are self-loops (both parts in the same cluster; mostly
definitional or measurement statements). 1,037 edges cross clusters; 211 of
them are supported by two or more papers and 50 by three or more. The
strongest are known findings, which is the sanity check we wanted:

| papers | n | antecedent cluster | consequent cluster |
|---|---|---|---|
| 7 | 66 | momentary solitude | low-arousal affect |
| 6 | 14 | spending time alone | self-reflection, creativity, rejuvenation |
| 5 | 12 | 15 minutes of solitude | low-arousal positive affect increases |
| 4 | 27 | lack of social contacts | loneliness |
| 4 | 14 | shy / reticent child | peer rejection |
| 4 | 17 | older age | solitude experienced less negatively than younger adults |

Noise is what it should be: one-off claims with no sibling in the corpus
("older women are primary caregivers in old age", "the findings are robust to
missing-data assumptions"), i.e. "no term applies yet", not garbage.

Known limitations of this spike:

- Consequents often keep a pronoun subject ("they tend to reap greater
  affective benefits than younger adults"), so consequent clusters group by
  predicate and the subject lives in the antecedent. Resolving the pronoun
  from the antecedent before embedding would sharpen the consequent terms.
- Cluster sizes count paraphrases, including double extractions; distinct
  papers and distinct chunks are the honest support counts.
- One parameter setting and one seed. `min_cluster_size` trades cluster count
  against noise; both reports are cheap to regenerate for other values.
- OpenAlex topics are not joined yet; the join is
  `phases_v2.papers.storage_key -> pubmed.artifacts.storage_key -> pmid ->
  openalex.paper_enrichments`.

## Frames: the generic pipeline in one file (2026-09-28)

`frames.py` is the end-to-end version of the method, written as a single
script so it can be reviewed top to bottom and tested on a few papers before
it runs on hundreds. See `PIPELINE.md` for the reasoning. Stages, each cached
under `storage/spikes/term_clustering/frames/<run>/`:

1. extract: one prompt lays each claim out as a relation between two
   seven-slot frames (process, participants, qualities of a participant,
   realizables of a participant, when, where, information). Roles only, no
   types.
2. flatten: one row per slot phrase, with the head noun's number folded into
   the key and "X decreases Y" rewritten as "X makes 'decrease in Y' more
   likely".
3. embed: every distinct (role, phrase).
4. cluster per role: agglomerative paraphrase merge (0.20 cosine) below 300
   phrases, UMAP + HDBSCAN above; phrases with opposite degree words never
   share a cluster.
5. categorise once per cluster, the role as a prior the model may override;
   cached by cluster content and prompt.
6. module: classes under BFO categories; `has participant` and `occurs in`
   from the frame structure when a majority of a process's frames agree;
   qualified frames become defined subclasses (`process and has participant
   some (participant and bearer of some quality)`); tendencies become
   dispositions with voted direction; null findings, co-occurrence and
   cross-category is-a stay as evidence.
7. review: slot fill rates, classes by bucket, restrictions, defined classes,
   relation axioms, what was refused and why, and processes with no
   consistent when/where/participant.

```sh
OPENAI_API_KEY=... uv run scripts/term_clustering/frames.py --papers 3 --run s3
uv run scripts/term_clustering/bfo_check.py --dir storage/spikes/term_clustering/frames/s3
uv run --no-project --with pytest --with pandas --with pyarrow --with rdflib --with scikit-learn \
    --with scipy --with numpy --with openai --with umap-learn pytest scripts/term_clustering/tests -q
```

Sample of three mid-sized papers (55 chunks, 355 claims, about $1.50):

| role | filled | distinct phrases | classes |
|---|---|---|---|
| process | 100% | 453 | 28 |
| participant | 100% | 56 | 11 |
| quality | 11% | 50 | 2 |
| realizable | 2% | 23 | 1 |
| when | 27% | 56 | 9 |
| where | 5% | 14 | 0 |
| information | 43% | 85 | 7 |

Module: 85 classes (58 from clusters, 5 defined from qualified frames, 22
minted from definitions), 8 participant restrictions ("aging process has
participant some older adult", 43 of 73 frames, 2 papers), 22 definitional
axioms, 73 relation axioms, 13 refused for stated reasons; 0 structural
problems, consistent, ROBOT-clean. The fill rates are the finding: papers
state participants and, less often, time and instrument; qualities,
realizables and places are rarely explicit, so those buckets will stay thin
until the corpus is large or a grounding step supplies them.

**Ten papers** (run `frames/s10`, 183 chunks, 1,096 claims, about 6 USD):
fill rates process and participant 100%, information 40%, when 24%,
quality 13%, where 4%, realizable 2%, the same profile as three papers.
Module: 242 classes (195 from clusters, 15 defined, 32 minted), 60
definitional axioms, 24 participant and place restrictions, 230 relation
axioms at one paper of support, 64 refused with reasons; 0 structural
problems, consistent, ROBOT-clean, and HermiT infers 69 module-internal
superclass links from the definitions. Three defects surfaced at this scale
and were fixed: a state extracted into the process slot ("having high
shyness") is typed as a quality and must not get a defined subclass with
participants (23 unsatisfiable classes before the fix); minted components
need the same polarity guard as clusters ("high aloneliness" and "low
aloneliness" had merged); a genus is minted in the class's own category, not
the slot's bucket ("autonomy" had been minted both as a process and as a
quality).

**All 26 local papers** (run `frames/s26`, 499 chunks, 3,092 claims, about
25 USD): fill rates unchanged (participants and processes 100%, information
40%, when 21%, quality 13%, where 4%, realizable 2%). Module: 770 classes
(549 from clusters, 126 defined, 95 minted), 214 definitional axioms, 74
participant and place restrictions, 806 relation axioms of which 17 have
three or more papers and 74 have two, 119 refused with reasons; 0
structural problems, consistent, ROBOT-clean; HermiT infers 553
module-internal superclass links. Two scale defects fixed on the way:
qualifiers repeated inside defined classes when several spans fell in one
cluster (now a set), and the density path over-merged roles with a few
hundred phrases (526 participant phrases became 42 clusters, 311 time
phrases became 8), so agglomeration is now used up to 2,000 phrases per
role; participants then give 107 classes, time phrases 67 ("older age",
"early adolescence", "later life", "solitude period"). The reviewed core
at two or more papers is 91 relation axioms; the rest is single-paper
evidence for the review sheet.

**Structured definitions.** The categoriser returns a genus, typed
differentiae (quality, realizable, life stage, location, member kind) and a
collective flag, not only a sentence. Each component is resolved to an
existing class of its role by centroid similarity (0.80) or minted once,
deduplicated by paraphrase, and becomes an axiom: `subClassOf` the genus,
`'bearer of' some` for qualities and realizables of independent continuants,
`'has member part' some` for collectives. Plural participants are individuals
unless the phrases name a group. This is what turns "A human child exhibiting
social withdrawal" into `'socially withdrawn child' SubClassOf 'child' and
'bearer of' some 'social withdrawal'`, with `child` and `social withdrawal`
as classes, and it is the corpus-derived dictionary that a grounding step
maps to reference ontologies (`human` to a taxon, the qualities to PATO).

Question: can papers ingested daily be attached to existing terms without
re-clustering everything? `incremental.py` simulates it: the 26 papers are put
in a fixed random order, the first 16 are clustered once and every cluster
becomes a term (centroid, per-term radius, member list), then the remaining 10
papers arrive one at a time and each new half is either assigned to a term or
left in a pool. Decisions are scored against the full 26-paper clustering.
`stability.py` measures how far that target can be trusted.

```sh
uv run scripts/term_clustering/incremental.py --initial-papers 16 --update-centroids
uv run scripts/term_clustering/stability.py --seeds 42 1 2
```

Calibration first. Three full runs with different seeds agree on 90-98% of the
points they both cluster (ARI 0.84-0.91), so the reference is stable at the
cluster level. Each run leaves 30-34% as noise, and only about 60% of points
are clustered in every run: membership at cluster edges is soft, and any
incremental design has to treat it as provisional.

Assignment results, 16 initial papers (162 terms, covering 65% of the
concepts the full corpus ends up with), 5,735 arriving halves:

| rule | assigned | precision | recall | wrong term | absorbed |
|---|---|---|---|---|---|
| centroid, p90 radius | 3,057 | 56% | 64% | 222 | 782 |
| centroid, max radius | 4,799 | 47% | 87% | 404 | 1,419 |
| centroid, p90 + 0.05 margin over runner-up | 1,585 | 72% | 42% | 49 | 314 |
| 8 of 10 nearest members agree | 1,690 | 65% | 42% | 62 | 431 |
| fixed cosine distance 0.15 | 184 | 86% | 7% | 19 | 5 |

Every rule sits on the same trade-off curve; the k-nearest-member vote does
not beat the centroid, and moving centroids with each assignment changes
nothing. The dominant error is *absorbed*: a half whose concept has no term
yet is assigned to the nearest existing term. Among halves whose concept does
have a term, assignment is right 85-95% of the time (p90: 1,301 correct vs
222 wrong; with margin: 933 vs 49). The problem is novelty detection, not
assignment, and novelty is a function of corpus coverage: at 16 papers, 35%
of concepts were still unknown.

Discovery on the pool alone recovered a third of the missing concepts and
re-created 40-46 fragments of terms that already existed. Clustering the pool
together with a 30% sample of existing members lets 30 of those fragments
attach to their term, but the recovery rate stays at a third.

What this means for the design:

- Daily assignment is provisional and should use a conservative rule (margin
  or member vote): it is right about 95% of the time when it fires, and what
  it leaves in the pool is not lost.
- The authoritative structure comes from periodic re-discovery (weekly, or
  after every N papers) over the pool, the recent assignments and a sample of
  existing members, with **id reconciliation** by member overlap: existing
  terms keep their ids, new clusters get new ids, and a named term that splits
  or merges is flagged for review rather than changed. While a full re-cluster
  takes minutes (it does up to a few thousand papers), the periodic job can
  simply be a full run followed by reconciliation.
- Human decisions (a name, a definition, an accept/reject) attach to the term
  id and survive re-clustering; membership refreshes underneath them and the
  app shows edge members as such.
- Coverage grows with the corpus, so the share of provisional assignments that
  later move should fall; the 200+ paper rerun is the first real measurement.

## BFO proposal (2026-09-25)

Question: can the clusters and their relations be turned into a BFO 2020
module with real axioms, generically (nothing corpus-specific in code or
prompts) and importing only `bfo-core`? `bfo_proposal.py` categorises every
cluster under BFO (kind, category, label, Aristotelian definition, rationale)
and turns each strong relation into an OWL restriction through a small pattern
library, with the pattern enforced against the two categories afterwards.
`bfo_check.py` runs the structural checks and HermiT.

```sh
OPENAI_API_KEY=... uv run scripts/term_clustering/bfo_proposal.py --min-papers-edge 3
OPENAI_API_KEY=... uv run scripts/term_clustering/bfo_proposal.py --min-papers-edge 3 \
    --quality-change-as-process --out-name bfo_b
uv run scripts/term_clustering/bfo_check.py --dir storage/spikes/term_clustering/bfo
```

Tendencies are the central problem: "If X, then Y tends to happen" is not a
universal, so `X SubClassOf r some Y` would be false. The module uses BFO's
disposition instead: bearers of X bear a disposition realized only in Y. Every
bearer has the disposition, not every disposition is realized. Class
expressions contain only BFO classes and BFO relations plus the module's own
term classes; what the corpus says about direction, strength and disagreement
is carried by annotations on the axiom (`claimDirection`, `supportPapers`,
`supportClaims`, `contested`, `evidence`), never by a class.

An earlier version defined two disposition subclasses, "probability
increasing" and "probability decreasing", to carry direction inside the
expression. That was wrong twice over: "increasing" is what any disposition
already does, and a disposition realized in Y cannot make Y less likely, so
"decreasing" produced contradictions whenever the target was itself a
"decrease in X" process. Direction now lives in the target process class
("decrease in loneliness") and a "decreases" claim whose target is not such a
class stays evidence.

Three runs on 195 clusters and the 50 relations with 3+ papers (`gpt-4.1`):

| | strict (A) | change as process (B, superseded) | plain BFO (C) |
|---|---|---|---|
| domain entities | 98 | 142 | 142 |
| set aside: comparative / measurement / mixed / other | 65 / 28 / 3 / 1 | 24 / 27 / 1 / 1 | 23 / 28 / 2 / 0 |
| categories | 35 quality, 31 process, 16 disposition, 10 object aggregate, 3 role, 2 GDC, 1 function | 82 process, 37 quality, 11 disposition, 6 object aggregate, 3 role, 2 GDC, 1 function | 77 process, 41 quality, 12 disposition, 5 object aggregate, 4 role, 3 GDC |
| axioms from 50 relations | 2 | 24 | 24 (all dispositions) |
| structural problems / consistent | 0 / yes | 0 / yes | 0 / yes |

Run C is the reference for the conditional-only module. Its output directory
is `bfo_c/`.

## Pipeline v2: both sources, votes, hierarchy (2026-09-28)

Five additions, each its own script, all covered by `tests/test_pure.py`
(17 tests; run with `uv run --no-project --with pytest --with pandas
--with pyarrow --with rdflib --with scikit-learn --with scipy --with numpy
--with openai pytest scripts/term_clustering/tests -q`).

```sh
uv run scripts/term_clustering/split_processes.py                       # probabilistic-process items -> phrase tables
OPENAI_API_KEY=... uv run scripts/term_clustering/embed_parts.py --input process_phrases
OPENAI_API_KEY=... uv run scripts/term_clustering/embed_parts.py --input participants
uv run scripts/term_clustering/cluster.py --variant process_phrases --min-cluster-size 10
uv run scripts/term_clustering/cluster.py --variant participants --min-cluster-size 8
uv run scripts/term_clustering/hierarchy.py --variant parts --min-cluster-size 15   # and process_phrases 10, participants 8
OPENAI_API_KEY=... uv run scripts/term_clustering/vote_directions.py --min-papers 2
OPENAI_API_KEY=... uv run scripts/term_clustering/bfo_module.py --min-papers 2
uv run scripts/term_clustering/bfo_check.py --dir storage/spikes/term_clustering/bfo_v2
```

**Probabilistic-process items as a second source.** The 3,624 items already
carry participant, subject process, direction and target process. Their
phrases cluster better than the halves (108 process clusters at 81% clustered,
41 participant clusters at 85%), 74% of items have both ends in a cluster,
and 166 of the 756 relations have two or more papers. Because the structure
is the disposition pattern, each (subject, participant, target) relation
becomes an axiom with no model call, and the participant gives the process
its `has participant` restriction ("aging has participant some older adult",
72 of 83 items, 9 papers). The participants are the bearer classes the
conditional-only module lacked.

**Merges and hierarchy** (`hierarchy.py`). Centroid pairs above 0.90 cosine
similarity fold into one term (4 clusters absorbed among the halves, 3 among
the processes); an average-linkage tree cut at cosine distance 0.25 gives
level-1 parents, which become proposed parent classes only when all their
children share one BFO category and there are at most twelve of them. The
labels of those parents are keyword pairs and their definitions are
placeholders; they exist to be named or rejected.

**Per-sentence direction votes** (`vote_directions.py`). Each of the 1,348
sentences behind the 211 conditional relations with two or more papers is
classified on its own (direction against the target as labelled, qualifier if
any). Contested is then a minority of at least 25% backed by two or more
papers: 12 relations. 162 relations carry at least one qualifier, and the
qualifiers often resolve the disagreement ("autonomy in solitude -> change in
low-arousal affect" splits exactly on *high* versus *low* autonomy).

**Two-source module** (`bfo_module.py`, output `bfo_v2/`):

| | conditional-only (C) | v2 |
|---|---|---|
| canonical terms | 142 | 263 (16 concepts found by both sources, aligned by centroid similarity ≥ 0.90 within one category) |
| classes | 142 | 293, including 30 proposed parents |
| axioms | 24 | 206: 112 from process items, 73 from conditionals (2+ papers, voted direction), 21 participant restrictions |
| evidence only | 26 | 99 |
| divergences reported | 3 contested | 34 (contested both ways, opposite change targets, effect versus null finding) |
| structural problems / HermiT / ROBOT | 0 / consistent / 0 errors | 0 / consistent / 0 errors |

The divergence list is now a first-class output. Its head is the central
argument of the field, with the papers counted on each side: "spending time
in solitude -> experience of loneliness" (10 papers, contested), "-> experience
of well-being" (8, contested), "-> onset of depressive symptoms" (5, contested).

Known weak points, for the review sheet (`bfo_v2/review.md`):

- alignment across sources is by similarity, so a few pairs are near rather
  than identical ("solitude episode" with "increase in solitude episode
  duration"); the alias annotation keeps both cluster ids for review;
- proposed parents are groupings, not terms, until someone names them;
- "spending time in solitude", "solitude experience" and "solitude
  engagement" are three process terms that a reviewer may collapse; the
  merge threshold was kept strict on purpose;
- relations with a single paper are not in the module at all.

The difference is one modelling decision. In this corpus the consequent of a
claim is very often a change in degree ("higher positive affect", "decrease in
loneliness"). Run A treats those clusters as comparative statements and sets
them aside, so 40 of the 50 relations have no class at one end and 6 more
target a quality, which cannot realize a disposition. Run B models "increase
in X" as a process in which a bearer's quality X changes (the OBO convention,
BFO-conformant), and lets a disposition targeting a quality be realized in the
process of coming to bear it. The strict run is the baseline that shows what
the corpus supports without that concession; the ontologist decides.

What run C writes reads like the findings: participants in spending time
alone bear a disposition realized only in self-reflection and creativity
(6 papers, direction "increases"); bearers of scarcity of social
relationships, in experience of loneliness (4); bearers of social withdrawal,
in peer rejection and victimization (4); participants in adolescent
engagement in solitude, in decrease in loneliness (3). Relations whose
sentences disagree are written with direction "none" and flagged contested
(3 of 24); 2 were refused by enforcement and the rest by the model as
comparative, correlational or inconsistent.

For review (the sheet is `review.md` in each output directory):

- category calls to argue with: "mutual friendship" and "social relations" as
  object aggregates, an attachment style as a role rather than a disposition;
- duplicate concepts across categories ("solitude" as a quality and
  "experience of solitude" as a process, joined by a trivial axiom) and among
  change processes ("decrease in high-arousal affect" twice): the merge and
  hierarchy steps of the term registry are where these belong;
- "age" as the bearer of dispositions ("age inheres in some bearer of a
  disposition realized in increase in time spent alone") is BFO-valid but
  reads oddly; a life-stage class may be the better subject.
