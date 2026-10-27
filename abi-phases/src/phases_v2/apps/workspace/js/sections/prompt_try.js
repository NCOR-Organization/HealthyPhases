// Try it: run the prompt in the editor on a few chunks of an ingested paper and
// see each chunk's items straight away, beside what an earlier version stored for
// the same chunks with the same model. Nothing is saved by trying.

import { phases } from '../api.js';
import { $, esc, fill, latest, message, plural, statusPill } from '../ui.js';
import { probabilisticRelations } from './search_render.js';

export const MAX_CHUNKS = 10;
// The server stops waiting at 90 s; this only covers a request that never returns.
export const CLIENT_TIMEOUT_MS = 120000;
const PAPER_PAGE = 25;
const SEARCH_DELAY_MS = 250;

export const template = () => `
  <section class="card" aria-labelledby="pr-try-title">
    <div class="card-head"><div><h2 id="pr-try-title">Try it</h2>
      <p class="hint">Runs the text in the editor on up to ${MAX_CHUNKS} chunks of a paper and shows the result here. Nothing is saved.</p></div></div>
    <div class="filters">
      <div><label for="pr-try-chunker">Chunker</label><select id="pr-try-chunker"></select></div>
      <div><label for="pr-try-model">Model</label><select id="pr-try-model"></select></div>
      <div><label for="pr-try-baseline">Compare with</label><select id="pr-try-baseline"></select></div>
    </div>
    <div class="grid">
      <div><label for="pr-try-paper-q">Find an ingested paper</label><input id="pr-try-paper-q" type="search" placeholder="Search by file name">
        <label for="pr-try-paper" class="sr-only">Paper</label><select id="pr-try-paper" size="6"></select>
        <p id="pr-try-papers-hint" class="hint"></p></div>
      <div><label for="pr-try-chunks">Chunks</label><select id="pr-try-chunks" multiple size="6"></select>
        <div class="row"><label for="pr-try-first">If none is picked, try the first</label><input id="pr-try-first" type="number" min="1" max="${MAX_CHUNKS}" value="3" style="width:5rem"></div>
        <p id="pr-try-chunks-hint" class="hint"></p></div>
    </div>
    <div class="row actions"><button id="pr-try-run" type="button" class="primary">Try it</button>
      <button id="pr-try-save" type="button">Save as new version</button><button id="pr-try-use" type="button" disabled>Use in new run</button></div>
    <p id="pr-try-message" class="msg" role="status" aria-live="polite"></p>
    <div id="pr-try-results" class="try-results"></div>
  </section>`;

export const shortId = (promptId) => String(promptId || '').slice(-8);

// The request body for one try. `source` is { prompt_id } or { draft }.
export function tryBody({ source, modelId, paperId, chunkerId, seqs = [], first = 3, baselineId = '' }) {
  const body = { ...source, model_id: modelId, paper_id: paperId, chunker_id: chunkerId };
  if (seqs.length) body.seqs = seqs;
  else body.first = first;
  if (baselineId) body.baseline_prompt_id = baselineId;
  return body;
}

function renderRelationItem(r) {
  const direction = { increases: 'increases', decreases: 'decreases', 'no-effect': 'has no effect on' }[r.direction] || esc(r.direction);
  return `<li class="try-relation"><span><strong>${esc(r.subject_process)}</strong> <span class="relation-edge ${esc(r.direction)}">${direction}</span> <strong>${esc(r.target_process)}</strong></span>
    <small>Participant: ${esc(r.subject_participant)}</small>${r.evidence_text ? `<blockquote class="evidence">${esc(r.evidence_text)}</blockquote>` : ''}</li>`;
}

// Claims as text, relations as subject → direction → target with their evidence.
export function renderItems(items) {
  if (!items?.length) return '<p class="empty">No items.</p>';
  return `<ol class="try-items">${items.map((item) => {
    if (item && typeof item === 'object') {
      const [relation] = probabilisticRelations(item);
      return relation ? renderRelationItem(relation) : `<li><pre class="json-payload">${esc(JSON.stringify(item, null, 2))}</pre></li>`;
    }
    return `<li>${esc(item)}</li>`;
  }).join('')}</ol>`;
}

const STATUS_LABELS = { succeeded: 'Succeeded', failed: 'Failed', timed_out: 'Timed out', not_run: 'Not run yet' };
const seconds = (ms) => `${(Number(ms || 0) / 1000).toFixed(1)} s`;

function renderOutcome(chunk) {
  if (chunk.status === 'succeeded') return renderItems(chunk.items);
  const raw = chunk.raw_output
    ? `<details><summary>Raw output</summary><pre class="context">${esc(chunk.raw_output)}</pre></details>` : '';
  return `<p class="msg bad">${esc(chunk.error || 'No result.')}</p>${raw}`;
}

function renderBaseline(baseline, modelLabel) {
  if (!baseline) return '';
  if (baseline.status === 'not_run') return `<p class="empty">Not run yet with ${esc(modelLabel)}.</p>`;
  if (baseline.status === 'succeeded') return renderItems(baseline.items);
  return `<p class="msg bad">${esc(baseline.error || 'This chunk failed in that run.')}</p>`;
}

export function renderChunk(chunk, { draftLabel, baselineLabel, modelLabel }) {
  const compare = baselineLabel !== undefined;
  return `<article class="try-chunk">
    <div class="row spread"><h3>Chunk ${esc(chunk.seq)}</h3><span class="row">${statusPill(chunk.status === 'timed_out' ? 'partial' : chunk.status, STATUS_LABELS[chunk.status] || chunk.status)}<span class="hint">${seconds(chunk.elapsed_ms)}</span></span></div>
    <details><summary>Chunk text</summary><p class="context">${esc(chunk.text)}</p></details>
    <div class="${compare ? 'compare' : ''}">
      <div><h4>${esc(draftLabel)}</h4>${renderOutcome(chunk)}</div>
      ${compare ? `<div><h4>${esc(baselineLabel)} ${statusPill(chunk.baseline?.status === 'not_run' ? 'idle' : chunk.baseline?.status, STATUS_LABELS[chunk.baseline?.status] || '')}</h4>${renderBaseline(chunk.baseline, modelLabel)}</div>` : ''}
    </div>
  </article>`;
}

export function reportSummary(report) {
  const failed = report.chunks.filter((c) => c.status === 'failed').length;
  const timedOut = report.chunks.filter((c) => c.status === 'timed_out').length;
  const parts = [`Tried on ${plural(report.chunks.length, 'chunk')} in ${seconds(report.elapsed_ms)}.`];
  if (failed) parts.push(`${plural(failed, 'chunk')} failed; the error and raw output are shown below.`);
  if (timedOut) parts.push(`${plural(timedOut, 'chunk')} did not answer in time. Try fewer chunks, or a faster model.`);
  return { text: parts.join(' '), kind: timedOut || failed ? 'warn' : 'ok' };
}

// `source()` returns { prompt_id } or { draft }, and the label to show for it.
export function createTry(ctx, { source }) {
  const state = {
    loaded: false, running: false, models: [], chunkers: [], papers: [], chunks: [], report: null,
    paperGuard: latest(), chunkGuard: latest(), searchTimer: null,
  };

  const modelLabel = (id) => state.models.find((m) => m.model_id === id)?.display_name || id;

  async function load() {
    if (state.loaded) return;
    const [models, chunkers] = await Promise.all([phases('/models'), phases('/chunkers')]);
    state.models = models.models;
    state.chunkers = chunkers.chunkers;
    fill($('pr-try-model'), state.models, 'model_id', (m) => m.display_name);
    fill($('pr-try-chunker'), state.chunkers, 'chunker_id', (c) => `${c.name} v${c.version}`);
    state.loaded = true;
    await searchPapers();
  }

  async function searchPapers() {
    const token = state.paperGuard.next();
    const chunker = $('pr-try-chunker').value;
    const query = new URLSearchParams({ q: $('pr-try-paper-q').value.trim(), chunker_id: chunker, limit: String(PAPER_PAGE) });
    try {
      const page = await phases(`/papers?${query}`);
      if (!state.paperGuard.is(token)) return;
      const keep = $('pr-try-paper').value;
      state.papers = page.papers;
      fill($('pr-try-paper'), state.papers, 'paper_id', (p) => `${p.file_name} (${plural(p.chunks?.[chunker] || 0, 'chunk')})`, keep ? [keep] : undefined);
      $('pr-try-papers-hint').textContent = page.total
        ? (page.total > page.papers.length ? `Showing ${page.papers.length} of ${page.total} papers. Search to narrow the list.` : '')
        : 'No ingested paper is chunked with this chunker yet. Ingest papers in Library, or run the pipeline with this chunker.';
      await loadChunks();
    } catch (error) {
      if (state.paperGuard.is(token)) $('pr-try-papers-hint').textContent = `Could not load papers: ${error.message}`;
    }
  }

  async function loadChunks() {
    const token = state.chunkGuard.next();
    const paper = $('pr-try-paper').value;
    const chunker = $('pr-try-chunker').value;
    state.chunks = [];
    $('pr-try-chunks').replaceChildren();
    $('pr-try-chunks-hint').textContent = '';
    if (!paper || !chunker) return;
    try {
      const body = await phases(`/papers/${encodeURIComponent(paper)}/chunks?chunker_id=${encodeURIComponent(chunker)}`);
      if (!state.chunkGuard.is(token)) return;
      state.chunks = body.chunks;
      fill($('pr-try-chunks'), state.chunks, 'seq', (c) => `${c.seq} · ${c.preview}`, []);
      $('pr-try-chunks-hint').textContent = `${plural(state.chunks.length, 'chunk')}. Pick up to ${MAX_CHUNKS}.`;
    } catch (error) {
      if (state.chunkGuard.is(token)) $('pr-try-chunks-hint').textContent = `Could not load chunks: ${error.message}`;
    }
  }

  const pickedSeqs = () => [...$('pr-try-chunks').selectedOptions].map((option) => Number(option.value));

  function checkPicked() {
    const count = pickedSeqs().length;
    if (count > MAX_CHUNKS) {
      message('pr-try-message', `${count} chunks are picked; try at most ${MAX_CHUNKS} at a time.`, 'warn');
    } else {
      message('pr-try-message');
    }
    return count <= MAX_CHUNKS;
  }

  // Versions offered as the baseline, newest first. `chosen` keeps or sets the pick.
  function setBaselines(versions, chosen) {
    const options = [{ prompt_id: '', label: 'Nothing' }, ...versions.map((v) => ({ prompt_id: v.prompt_id, label: `Version ${shortId(v.prompt_id)}${v.label ? ` · ${v.label}` : ''}` }))];
    const keep = chosen ?? $('pr-try-baseline').value;
    fill($('pr-try-baseline'), options, 'prompt_id', (o) => o.label, keep ? [keep] : ['']);
  }

  async function run() {
    if (state.running) return undefined;
    const { body: src, label } = source();
    if (src.draft && !src.draft.template.includes('{chunk_text}')) {
      message('pr-try-message', 'The prompt text must contain {chunk_text}, where each chunk\'s text is placed.', 'bad');
      return undefined;
    }
    if (!$('pr-try-paper').value) { message('pr-try-message', 'Choose an ingested paper to try the prompt on.', 'bad'); return undefined; }
    if (!$('pr-try-model').value) { message('pr-try-message', 'Choose an available model.', 'bad'); return undefined; }
    if (!checkPicked()) return undefined;
    const first = Math.round(Number($('pr-try-first').value) || 3);
    if (!pickedSeqs().length && (first < 1 || first > MAX_CHUNKS)) {
      message('pr-try-message', `Try between 1 and ${MAX_CHUNKS} chunks at a time.`, 'bad');
      return undefined;
    }
    const body = tryBody({
      source: src, modelId: $('pr-try-model').value, paperId: $('pr-try-paper').value, chunkerId: $('pr-try-chunker').value,
      seqs: pickedSeqs(), first, baselineId: $('pr-try-baseline').value,
    });
    const count = body.seqs?.length || body.first;
    const button = $('pr-try-run');
    state.running = true;
    button.disabled = true;
    button.textContent = 'Trying…';
    message('pr-try-message', `Trying on ${plural(count, 'chunk')} with ${modelLabel(body.model_id)}. This can take a minute.`);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), CLIENT_TIMEOUT_MS);
    try {
      const report = await phases('/prompts/try', { method: 'POST', body, signal: controller.signal });
      state.report = report;
      const baselineLabel = report.baseline_prompt_id ? `Version ${shortId(report.baseline_prompt_id)}, stored` : undefined;
      $('pr-try-results').innerHTML = report.chunks.map((chunk) => renderChunk(chunk, {
        draftLabel: label, baselineLabel, modelLabel: modelLabel(report.model_id),
      })).join('');
      const summary = reportSummary(report);
      message('pr-try-message', summary.text, summary.kind);
      return report;
    } catch (error) {
      message('pr-try-message', error?.name === 'AbortError'
        ? `No answer after ${CLIENT_TIMEOUT_MS / 60000} minutes, so the try was stopped. Try fewer chunks, or a faster model.`
        : `The try failed: ${error?.message || error}`, 'bad');
      return undefined;
    } finally {
      clearTimeout(timer);
      state.running = false;
      button.disabled = false;
      button.textContent = 'Try it';
    }
  }

  $('pr-try-chunker').addEventListener('change', searchPapers);
  $('pr-try-paper').addEventListener('change', loadChunks);
  $('pr-try-chunks').addEventListener('change', checkPicked);
  $('pr-try-paper-q').addEventListener('input', () => {
    clearTimeout(state.searchTimer);
    state.searchTimer = setTimeout(searchPapers, SEARCH_DELAY_MS);
  });
  $('pr-try-run').addEventListener('click', run);

  return { load, run, searchPapers, loadChunks, setBaselines, state };
}
