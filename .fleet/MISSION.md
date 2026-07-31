# MISSION — HealthyPhases

> The bigger picture for this project. Every agent reads this FIRST, every run.
> Keep it current: when reality changes, update this file — it is the source of truth
> that lets agents act without asking.

## 🎯 North Star
HealthyPhases (PHASES) is a **research project**: *Promoting Healthy Aging through
Semantic Enrichment of Solitude Research.* The point is to understand how solitude and
gerotranscendence relate to healthy aging, and to encode that understanding rigorously in
the **phases ontology** (BFO-aligned). Everything else — the paper-ingestion/extraction
pipelines, the Nexus knowledge graphs, the Docusaurus site — exists to build, populate,
and validate that ontology. This is academic work: the ontology, the method, and the
findings all ultimately land in **published papers**, so *documenting what we do and why
is part of the deliverable, not overhead.*

## ✅ Definition of Done
The current milestone: turn research papers into trustworthy, queryable ontological
knowledge — and keep the record paper-ready.
- [ ] Phases ontology cleanly models the concepts we're extracting (dispositions,
      processes, relations) and stays BFO-consistent
- [ ] Ingestion + extraction workflows reliably turn a paper into correctly-scoped triples
      in the right Nexus named graph (papers vs. extractions)
- [ ] Extracted knowledge is queryable end-to-end through Nexus (Composer queries return
      correct cross-graph results)
- [ ] Every non-trivial modeling decision, method, and result is written down (in-repo docs
      / JOURNAL) in a form that can be lifted into a paper

## 🗺️ Current State
<Agents UPDATE this as they work so the next run starts oriented.>
- Live: Docusaurus website at **healthyphases.org**; `abi-phases` ABI package with
  Nexus knowledge graphs (papers graph + extractions graph).
- In flight: generic ingestion/extraction pipeline; `what` extraction (definition/nature
  of solitude); probability-modulating BFO process-disposition triples + the matching
  disposition ontology classes (`(In/De)creaseprobabilityDisposition`,
  `NoeffectProbabilityDisposition`, `ProbabilitymodulatingDisposition`).
- Known issues: two `naas-abi` checkouts exist — the LIVE one is the `abi-phases/.abi/`
  submodule; the sibling `abi_/` is a stale March snapshot, do NOT edit it. Cross-graph
  Composer queries needed a per-hop GRAPH-scoping fix (still to be upstreamed).

## 🔓 Authority & Guardrails  — DEFAULT AUTONOMY: full
> ⚠️ HUMAN-OWNED SECTION — agents never edit anything under this heading.
> Agents may update **Current State** and the **Backlog**, and *append* to the
> **Decisions Log**. Authority, guardrails, and red lines change only by human hand.

Act like a trusted senior research engineer who owns this. Make real progress and land
work end-to-end without checking in on reversible calls.

**Green light — just do it, no need to ask:**
- Read/search anything; write code on task branches in your own worktree (never in the
  primary checkout — see the Git workflow line in Conventions)
- Commit, push, open PRs, run tests and quality checks
- Merge green, in-scope PRs and land the work (full autonomy)
- Build/iterate on ontology classes, ingestion/extraction workflows, and prompts
- Refactor, add tests, and — critically — **write/update docs and JOURNAL** so the work is
  paper-ready. Documentation is in-scope by default, never something to defer.

**🚩 Red lines — the ONLY things that always need a human (park in INBOX.md and move on):**
- **Destroying or irreversibly mutating graph/prod data** — no wiping or destructive
  migration of a Nexus named graph or the triplestore (Jena/Fuseki in prod) without a
  verified backup + restore path.
- **Spending money / provisioning paid infra** — no new paid cloud/infra, and no large
  paid LLM/API runs. Small local/dev extraction runs are fine; a big batch that costs real
  money is not — park it.
- A decision that contradicts something in the Decisions Log below.

**What counts as "true ambiguity" worth escalating (vs. just deciding):**
- Two reasonable paths with materially different, hard-to-reverse consequences
- A modeling choice that would change the ontology's meaning in a way a co-author might
  contest (BFO alignment / class semantics) — flag it rather than silently commit
- Missing information no amount of code- or paper-reading can resolve

Everything else: pick the sensible default, record it in the Decisions Log, keep moving.
Do NOT stop and wait on a reversible call.

## 📜 Decisions Log  (append-only — so nobody re-asks a settled question)
- 2026-07-08 — Primary focus is the **phases ontology**; pipelines/site serve it — Maxime
- 2026-07-08 — This is a research project; **document everything toward eventual papers** — Maxime
- 2026-07-08 — Default autonomy = **full** (agents merge & land in-scope work) — Maxime
- 2026-07-08 — Red lines: no destructive graph/prod-data ops; no paid infra/spend — Maxime
- 2026-07-08 — Always work in the `.abi/` submodule; the sibling `abi_/` is stale, never edit — Maxime
- 2026-07-09 — Do NOT create phase modules; the unified ontology (merged `phases.ttl` + `bfo_core`) must stay whole, so splitting code per phase is the wrong shape. Instead express phase membership via **per-phase README manifests** (`PHASE_ONE.md`, `PHASE_TWO.md`) that link to each phase's workflows + ontology terms + named graphs, for paper-review traceability. Separately, move only the genuinely-unused workflows (Axioms*, Labels*, MainIngestionOrchestration, Solitude…) into `workflows/archive/`. Not git branches — phases are permanent structure, branches are ephemeral. — Maxime

## 📋 Backlog  (prioritized; pull from the top, mark status, add what you discover)
Status keys: `[ ]` todo · `[~]` / `[~ <agent>]` claimed/in progress · `[x]` done · `[!]` blocked→INBOX
Routing (only when `.fleet/agents/` exists): tag an item `@<agent>` right after the
status to reserve it for that agent; untagged items belong to the generalist.
1. [ ] Add per-phase README manifests (`PHASE_ONE.md`, `PHASE_TWO.md`) linking each phase's
       workflows + ontology terms + graphs, and move unused workflows into
       `workflows/archive/` — full brief in `.fleet/tasks/phase-readmes-and-archive.md`
2. [ ] Finish + document the generic ingestion/extraction pipeline (one paper → correctly
       scoped triples in the right named graph), with tests for success and failure paths
3. [ ] Validate the probability-modulating disposition classes against BFO and write up the
       modeling rationale (paper-ready) in-repo
4. [ ] Verify cross-graph Composer queries return correct results for
       `ExtractedItem → Chunk → PDFPaperFile`; upstream the per-hop GRAPH-scoping fix
5. [ ] Add a short "how extraction works" doc: graph split, workflows involved, how to run

## 🔗 Task Sources  (optional — external feeders into the Backlog above)
> The Backlog is the ONLY queue agents pull from; these sources sync INTO it.
> Refresh by running `scripts/fleet-pull.sh` from this repo — the repo is auto-detected
> by `gh` from the git remote. Idempotent: issues already listed by #number are skipped,
> and new items append to the BOTTOM so your hand-set priorities stay on top.
- [ ] **GitHub issues** — `assignee:@me state:open labels:`  ← tick the box `[x]` to enable; edit the filter inline (comma-separate labels)

## 🔧 Conventions & Facts  (the stuff an agent would otherwise ask about)
- Stack: **Docusaurus** website (Node ≥18 <20) at repo root · **`abi-phases/`** ABI Python
  package (uv, Python ≥3.12) driving Nexus knowledge graphs · live `naas-abi` code lives in
  the `abi-phases/.abi/` git submodule.
- Domains: ontology in `abi-phases/src/phases/ontologies/` · ingestion/extraction in
  `abi-phases/src/phases/workflows/` (e.g. `PapersIngestionWorkflow`,
  `GenericChunkExtractionWorkflow`, `ProcessDispositionExtractionWorkflow`).
- Named-graph split (intentional): `…/graph/phases/papers` holds `PDFPaperFile`, `Chunk`,
  `chunk_of`; `…/graph/phases/extractions` holds `ExtractedItem`, `Extraction`,
  `extracted_from_chunk`. Extraction chains cross the graph boundary at hop 1.
- Run/test: website `npm run start` / `npm run build`; ABI `cd abi-phases && uv sync`,
  `make api`, `make chat`, tests `uv run pytest`. Full workspace checks: `make check` /
  `make test`, format with `uvx ruff format`.
- Triplestore: Apache Jena TDB2/Fuseki in prod; Oxigraph in nexus dev.
- Prod is: **healthyphases.org** (website). Website deploys via Docusaurus.
- Architecture: hexagonal — keep business logic independent of frameworks/APIs; organize by
  domain; ports/adapters for external systems; tests near the code (`*_test.py`).
- Git workflow: default branch `main` · task branches `fleet/<agent>/<slug>` in worktrees
  under `.fleet/worktrees/` · land via PR merge (full autonomy) · the primary checkout stays
  on `main` and carries `.fleet/` state.
- Gotchas: never edit the stale `abi_/` snapshot — work in `.abi/`. Don't commit secrets
  from `.env` / `config*.yaml`. This is research: when you make a modeling or method
  decision, write down the *why*, not just the *what*.
