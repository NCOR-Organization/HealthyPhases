# JOURNAL — HealthyPhases

> Append-only. One block per work run. Newest at the TOP.
> This is how a human catches up on what the fleet did without watching it live.
> Keep each entry to ~5 skimmable lines. Link commits/PRs.
> Running role agents? Start each headline with `[<agent>]` so runs are attributable.

---

## 2026-07-30 — Materialized `phases/merged` graph in local Fuseki
- **Picked:** human ask — one graph merging papers + extractions for easier querying
- **Did:** two SPARQL `ADD`s (papers, then extractions) → `http://ontology.naas.ai/graph/phases/merged` on local Fuseki `/ds`; registered it in the `graph/nexus` registry (`rdfs:label "Merged"`, `nexus:KnowledgeGraph`, same `hasKnowledgeGraphRole` as Papers/Extractions) — without that entry Nexus doesn't discover the graph
- **Result:** 502,578 triples = 110,423 + 392,155 exactly (sources disjoint, and unchanged after the copy). The two graphs share **zero subjects** — they link subject→object: 827,632 edges into 3,246 paper entities, mostly `documents.owl#chunk_of`. Verified an extraction→paper hop now resolves inside the single merged graph (the traversal that needed the per-hop GRAPH-scoping Composer fix)
- **Next:** if this proves useful, decide whether extraction workflows should write to `merged` directly, or keep it as a rebuilt projection
- **Blocked?:** none — but note it's a **materialized copy, not a live view**: re-run the two `ADD`s to refresh. Local only; remote Fuseki untouched

- **Picked:** backlog #1 — express phase membership via manifests (not modules), declutter `workflows/`
- **Did:** agent on `fleet/claude/phase-readmes-and-archive` created `PHASE_ONE.md` + `PHASE_TWO.md` (link each phase's workflows + ontology terms + graphs) and `git mv`'d 11 unused Axioms*/Labels*/MainIngestion/Solitude workflows → `workflows/archive/`, rewriting their imports to `phases.workflows.archive.*` (PhasesOrchestration untouched; PapersIngestion left in place)
- **Result:** PR #37 open (not merged). Verified: static import sweep clean, `py_compile` on moved files, `uv sync`, runtime import of active `PhasesOrchestration`. Skipped: pytest (not installed); runtime import of archived MainIngestion blocked by a PRE-EXISTING ontology bug (`phases.ontologies.classes.labels` missing + unrebuilt `Chunk` forward-ref), not caused by the move
- **Next:** human review/merge PR #37; fill the two `TODO: paper` links; phase-two `*Disposition.py` still WIP (linked "(pending commit)")
- **Blocked?:** none — but flagged a separate pre-existing ontology import bug worth its own fix

---

## <YYYY-MM-DD HH:MM> — <one-line headline>
- **Picked:** backlog #N — <what & why now>
- **Did:** <concrete actions — files, commits, PRs, deploys>
- **Result:** <merged / deployed / PR #123 open for review / tests green>
- **Next:** <the next unblocked thing — already queued in MISSION backlog>
- **Blocked?:** <none · or → see INBOX.md entry from this date>

---
