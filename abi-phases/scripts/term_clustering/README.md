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
