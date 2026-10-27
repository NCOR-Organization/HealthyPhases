// Search: find which papers, and where in them, a finding is stated.
//
// The submitted search lives in the URL (#/search?q=...&mode=keyword&prompt=...),
// so a link or a reload shows the same results. Pages come from one dataset
// snapshot, loaded by infinite scroll or the Load more button.

import { fetchBlob, phases, PREFIXES, saveBlob, search as searchApi } from '../api.js';
import { $, esc, fill, message } from '../ui.js';
import { highlight, parsePayload, probabilisticRelations, renderExtraction } from './search_render.js';

export { highlight, keywordTerms, renderExtraction } from './search_render.js';

export const MODES = {
  semantic: { label: 'Semantic', hint: 'by meaning', placeholder: 'e.g. solitude reduces stress in older adults', size: 10 },
  keyword: { label: 'Keyword', hint: 'words or quoted phrases', placeholder: 'e.g. "being alone" stress', size: 25 },
  effects: { label: 'Effects', hint: 'direction, subject, target', placeholder: 'e.g. stress', size: 25 },
};

// The same search whatever the parameter order, so a link and the URL written back match.
const keyOf = (params) => new URLSearchParams([...params].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))).toString();

const template = () => `
  <header class="page-head"><p class="eyebrow">Step 4 · Explore results</p><h1 tabindex="-1">Search</h1>
    <p class="lede">Find which papers, and where in them, a finding is stated. Search by meaning, by words, or by the effect itself.</p></header>
  <section class="card">
    <form id="sr-form" role="search">
      <div class="segmented" role="group" aria-label="Search mode">${Object.entries(MODES).map(([mode, m]) => `<button type="button" id="sr-mode-${mode}" data-mode="${mode}" aria-pressed="false">${m.label}<small>${m.hint}</small></button>`).join('')}</div>
      <label id="sr-q-label" for="sr-q">Finding to look for</label>
      <div class="search-row"><input type="search" id="sr-q" autocomplete="off"><button class="primary" id="sr-go">Search</button></div>
      <p id="sr-keyword-help" class="hint" hidden>Use quotes for an exact word or phrase, e.g. "like" or "being alone".</p>
      <div id="sr-effects" hidden>
        <p class="hint">Filter the extracted relationship itself. Leave fields blank to browse every effect.</p>
        <div class="grid three">
          <div><label for="sr-direction">Direction</label><select id="sr-direction"><option value="">Any direction</option><option value="increases">Increases</option><option value="decreases">Decreases</option><option value="no-effect">Neutral (no effect)</option></select></div>
          <div><label for="sr-subject">From / subject</label><input id="sr-subject" type="text" placeholder="e.g. meditation"></div>
          <div><label for="sr-participant">Participant</label><input id="sr-participant" type="text" placeholder="e.g. older adults"></div>
        </div>
      </div>
      <details class="filters-panel" id="sr-filters">
        <summary>Filters</summary>
        <div class="grid">
          <div><label for="sr-size">Batch size</label><input type="number" id="sr-size" value="10" min="1" max="100"></div>
          <div id="sr-threshold-wrap"><label for="sr-threshold">Minimum score</label><input type="number" id="sr-threshold" step="0.05" min="0" max="1" placeholder="any"></div>
        </div>
        <div class="facets" id="sr-prompt-facets" role="group" aria-label="Prompts"></div>
        <div class="facets" id="sr-model-facets" role="group" aria-label="Extraction models">Loading models...</div>
        <div><label for="sr-collection">Collection</label><select id="sr-collection"><option value="">All papers</option></select>
          <p class="hint">Only the papers in this collection, combined with the other filters. <a href="#/collections">Manage collections</a></p></div>
        <div><label for="sr-paths">Source folders</label><select id="sr-paths" multiple size="4" aria-describedby="sr-paths-help"></select>
          <div class="row"><span id="sr-paths-help" class="hint">Selecting a folder includes its subfolders. No selection searches every folder.</span><button type="button" class="small" id="sr-clear-paths">All folders</button></div>
          <p id="sr-paths-status" class="hint"></p></div>
      </details>
    </form>
  </section>
  <div class="row spread"><p class="msg" id="sr-status" role="status"></p><button type="button" id="sr-export" disabled>Export all matches (CSV)</button></div>
  <p id="sr-export-status" class="msg" role="status"></p>
  <div class="results" id="sr-results"></div>
  <div id="sr-sentinel" class="row center"><button type="button" id="sr-load-more" hidden>Load more</button></div>`;

export function create(root, ctx) {
  root.innerHTML = template();
  const state = {
    mode: 'semantic', prompts: new Set(), selected: new Set(), models: [], modelNames: {}, selectedModels: new Set(),
    selectedPaths: new Set(), collection: '', collections: [], activeSearch: null, version: 0, loading: false, nextOffset: null, total: 0,
    seen: new Set(), controller: null, exportController: null, exporting: false, lastKey: '', started: false,
  };
  const modelName = (id) => state.modelNames[id] || id;

  function setMode(mode, size = true) {
    state.mode = MODES[mode] ? mode : 'semantic';
    for (const name of Object.keys(MODES)) $(`sr-mode-${name}`).setAttribute('aria-pressed', String(name === state.mode));
    $('sr-keyword-help').hidden = state.mode !== 'keyword';
    $('sr-effects').hidden = state.mode !== 'effects';
    $('sr-threshold-wrap').hidden = state.mode !== 'semantic';
    $('sr-q-label').textContent = state.mode === 'effects' ? 'Target process (optional)' : 'Finding to look for';
    $('sr-q').placeholder = MODES[state.mode].placeholder;
    if (size) $('sr-size').value = MODES[state.mode].size;
  }

  function facet(box, label, pressed, toggle) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'facet';
    button.setAttribute('aria-pressed', String(pressed));
    button.textContent = label;
    button.addEventListener('click', toggle);
    box.append(button);
  }

  function renderPromptFacets() {
    const box = $('sr-prompt-facets');
    box.replaceChildren();
    const names = [...new Set([...state.prompts, ...state.selected])];
    if (!names.length) return;
    const hint = document.createElement('span');
    hint.className = 'facet-label';
    hint.textContent = 'Prompts:';
    box.append(hint);
    for (const name of names) {
      facet(box, name, state.selected.has(name), () => {
        if (state.selected.has(name)) state.selected.delete(name); else state.selected.add(name);
        renderPromptFacets();
      });
    }
  }

  function renderModelFacets() {
    const box = $('sr-model-facets');
    box.replaceChildren();
    const hint = document.createElement('span');
    hint.className = 'facet-label';
    hint.textContent = 'Models:';
    box.append(hint);
    facet(box, 'All models', state.selectedModels.size === 0, () => { state.selectedModels.clear(); renderModelFacets(); });
    for (const model of [...new Set([...state.models, ...state.selectedModels])]) {
      facet(box, modelName(model), state.selectedModels.has(model), () => {
        if (state.selectedModels.has(model)) state.selectedModels.delete(model); else state.selectedModels.add(model);
        renderModelFacets();
      });
    }
  }

  function renderPaths(paths) {
    $('sr-paths').replaceChildren();
    for (const path of [...new Set([...paths, ...state.selectedPaths])]) {
      const option = document.createElement('option');
      option.value = path;
      option.textContent = path;
      option.selected = state.selectedPaths.has(path);
      $('sr-paths').append(option);
    }
  }

  function renderCollections() {
    const known = state.collections.some((c) => c.collection_id === state.collection);
    const items = [{ collection_id: '', name: 'All papers' }, ...state.collections];
    if (state.collection && !known) items.push({ collection_id: state.collection, name: 'Archived or unknown collection' });
    fill($('sr-collection'), items, 'collection_id', (c) => c.name, [state.collection]);
  }

  // Filter options are optional: search still works if one list cannot load.
  async function loadFacets() {
    await Promise.all([
      phases('/collections?counts=false').then((data) => { state.collections = data.collections || []; renderCollections(); }).catch(() => {}),
      searchApi('/prompts').then((data) => { state.prompts = new Set(data.prompts || []); renderPromptFacets(); }).catch(() => {}),
      phases('/models').then((data) => { state.modelNames = Object.fromEntries((data.models || []).map((m) => [m.model_id, m.display_name])); }).catch(() => {}),
      searchApi('/models').then((data) => { state.models = data.models || []; }).catch(() => { $('sr-model-facets').textContent = 'Model filters are unavailable. Reload the app to retry.'; state.models = null; }),
      searchApi('/paths').then((data) => {
        renderPaths(data.paths || []);
        $('sr-paths-status').textContent = (data.paths || []).length ? '' : 'No source folders have results yet. Run the pipeline first.';
      }).catch(() => { $('sr-paths-status').textContent = 'Folder filters are unavailable. Reload the app to retry.'; }),
    ]);
    if (state.models !== null) renderModelFacets();
    else state.models = [];
  }

  async function downloadPaper(hit, button, status) {
    button.disabled = true;
    button.textContent = 'Downloading...';
    status.textContent = '';
    try {
      const params = new URLSearchParams({ item_id: hit.item_id });
      const blob = await fetchBlob(`${PREFIXES.search}/paper?${params}`, { notFound: 'Source PDF is unavailable.' });
      saveBlob(blob, hit.paper_name || 'paper.pdf');
    } catch (error) {
      status.textContent = error.status && error.status !== 404 ? `Download failed (${error.status}). Please try again.` : error.message;
    } finally {
      button.disabled = false;
      button.textContent = 'Download paper';
    }
  }

  function renderHits(data, append = false) {
    $('sr-export').disabled = !data.total || state.exporting;
    const box = $('sr-results');
    if (!append) box.replaceChildren();
    if (!data.hits.length && !append) {
      box.innerHTML = `<div class="card empty">No matches for “${esc(data.query || 'all targets')}”. Try other words, another mode, or fewer filters.</div>`;
      return;
    }
    for (const h of data.hits) {
      const resultId = h.relation_id || h.item_id;
      if (state.seen.has(resultId)) continue;
      state.seen.add(resultId);
      const card = document.createElement('article');
      card.className = 'card hit';
      const score = h.score != null ? `<span class="score">score ${h.score.toFixed(3)}</span>` : '';
      const where = h.chunk_seq != null ? `<span>chunk #${esc(h.chunk_seq)}</span>` : '';
      const paper = h.paper_name ? `<span class="paper">${esc(h.paper_name)}</span>` : '<span>Unknown paper</span>';
      const prompt = h.prompt_name ? `<span class="badge">${esc(h.prompt_name)}</span>` : '';
      const model = `<span class="badge">Model: ${esc(modelName(h.model_id) || 'unknown')}</span>`;
      const source = h.source_path ? `<div class="meta source-path">Source folder: ${esc(h.source_path)}</div>` : '';
      const version = h.prompt_id ? `<a href="${esc(ctx.href('prompts', [h.prompt_id]))}">Open this prompt version</a>` : 'Prompt version unknown.';
      const promptDetails = `<details><summary>View extraction prompt</summary>
        <div class="meta">Stored template of the prompt version that produced this finding. ${version}</div>
        <div class="context">${esc(h.prompt_template || 'Stored prompt unavailable for this result.')}</div></details>`;
      const context = h.chunk_text
        ? `<details><summary>Show source chunk</summary><div class="context">${highlight(h.chunk_text, data.query, data.mode)}</div></details>`
        : '<details><summary>Source chunk</summary><div class="context">Source chunk is unavailable for this match.</div></details>';
      const raw = probabilisticRelations(parsePayload(h.extracted_text)).length
        ? `<details><summary>Show original JSON</summary><div class="context">${esc(h.extracted_text)}</div></details>` : '';
      const download = h.paper_id ? '<button class="small download" type="button">Download paper</button><span class="download-status" role="status"></span>' : '';
      card.innerHTML = `${renderExtraction(h.extracted_text, data.query, data.mode)}
        <div class="meta">${prompt}${model}${paper}${where}${score}${download}</div>
        ${source}${context}${promptDetails}${raw}`;
      const button = card.querySelector('.download');
      if (button && h.paper_id) button.addEventListener('click', () => downloadPaper(h, button, card.querySelector('.download-status')));
      box.append(card);
    }
  }

  function updateStatus() {
    const active = state.activeSearch;
    message('sr-status', `Showing ${state.seen.size} of ${state.total} matches for “${active.query}” · ${MODES[active.mode].label.toLowerCase()} search`);
    $('sr-load-more').hidden = state.nextOffset === null;
  }

  async function loadPage(append) {
    const version = state.version;
    const active = state.activeSearch;
    if (!active || state.loading || (append && state.nextOffset === null)) return;
    state.loading = true;
    $('sr-load-more').disabled = true;
    $('sr-load-more').textContent = 'Loading...';
    const params = new URLSearchParams(active.params);
    params.set('offset', append ? state.nextOffset : 0);
    let succeeded = false;
    try {
      const data = await searchApi(`/${active.mode}?${params}`, { signal: state.controller.signal });
      if (version !== state.version) return;
      if (data.snapshot != null) active.params.set('snapshot', data.snapshot);
      state.total = data.total;
      state.nextOffset = data.next_offset;
      renderHits(data, append);
      updateStatus();
      succeeded = true;
    } catch (error) {
      if (version !== state.version || error.name === 'AbortError') return;
      message('sr-status', `${append ? 'Could not load the next batch' : 'Search failed'}: ${error.message}`, 'bad');
      $('sr-load-more').hidden = !append;
    } finally {
      if (version === state.version) {
        state.loading = false;
        $('sr-go').disabled = false;
        $('sr-load-more').disabled = false;
        $('sr-load-more').textContent = 'Load more';
        // Keep filling the page while the end of the list is in view.
        const sentinel = $('sr-sentinel');
        if (succeeded && state.nextOffset !== null && !root.hidden && sentinel.getBoundingClientRect
          && sentinel.getBoundingClientRect().top < window.innerHeight + 300 && typeof requestAnimationFrame === 'function') {
          requestAnimationFrame(() => { if (version === state.version) loadPage(true); });
        }
      }
    }
  }

  function formParams() {
    const params = new URLSearchParams({ q: $('sr-q').value.trim() });
    if (state.mode === 'effects') {
      params.set('direction', $('sr-direction').value);
      params.set('subject', $('sr-subject').value.trim());
      params.set('participant', $('sr-participant').value.trim());
    }
    state.selected.forEach((p) => params.append('prompt', p));
    state.selectedModels.forEach((m) => params.append('model', m));
    state.selectedPaths.forEach((p) => params.append('path', p));
    if (state.collection) params.set('collection', state.collection);
    params.set(state.mode === 'semantic' ? 'k' : 'limit', $('sr-size').value || MODES[state.mode].size);
    if (state.mode === 'semantic' && $('sr-threshold').value) params.set('score_threshold', $('sr-threshold').value);
    return params;
  }

  async function search() {
    const query = $('sr-q').value.trim();
    if (!query && state.mode !== 'effects') {
      message('sr-status', 'Type what you are looking for, or switch to Effects to browse every effect.', 'warn');
      $('sr-q').focus();
      return;
    }
    state.controller?.abort();
    state.exportController?.abort();
    state.controller = new AbortController();
    state.exporting = false;
    state.version += 1;
    state.loading = false;
    state.seen = new Set();
    state.nextOffset = null;
    state.total = 0;
    $('sr-go').disabled = true;
    message('sr-status', 'Searching...');
    message('sr-export-status');
    $('sr-results').replaceChildren();
    $('sr-export').disabled = true;
    $('sr-load-more').hidden = true;
    const params = formParams();
    const link = new URLSearchParams(params);
    link.set('mode', state.mode);
    state.activeSearch = { query: query || 'all targets', mode: state.mode, params, link };
    state.lastKey = keyOf(link);
    ctx.replace(ctx.href('search', [], link));
    await loadPage(false);
  }

  // A link describes a search; fill the form from it.
  function applyParams(params) {
    setMode(params.get('mode') || 'semantic');
    $('sr-q').value = params.get('q') || '';
    $('sr-direction').value = params.get('direction') || '';
    $('sr-subject').value = params.get('subject') || '';
    $('sr-participant').value = params.get('participant') || '';
    const size = params.get(state.mode === 'semantic' ? 'k' : 'limit');
    if (size) $('sr-size').value = size;
    $('sr-threshold').value = params.get('score_threshold') || '';
    state.selected = new Set(params.getAll('prompt'));
    state.selectedModels = new Set(params.getAll('model'));
    state.selectedPaths = new Set(params.getAll('path'));
    for (const option of $('sr-paths').options) option.selected = state.selectedPaths.has(option.value);
    state.collection = params.get('collection') || '';
    renderCollections();
    if (state.selected.size || state.selectedModels.size || state.selectedPaths.size || state.collection) $('sr-filters').open = true;
    renderPromptFacets();
    renderModelFacets();
  }

  async function exportCsv() {
    const active = state.activeSearch;
    if (!active || !state.total || state.exporting) return;
    state.exporting = true;
    state.exportController = new AbortController();
    $('sr-export').disabled = true;
    message('sr-export-status', `Preparing every match for “${active.query}”...`);
    const params = new URLSearchParams(active.params);
    params.delete('k');
    params.delete('limit');
    params.delete('offset');
    params.set('mode', active.mode);
    try {
      const blob = await fetchBlob(`${PREFIXES.search}/export?${params}`, { signal: state.exportController.signal, accept: 'text/csv' });
      if (active !== state.activeSearch) return;
      saveBlob(blob, `healthyphases-search-${new Date().toISOString().slice(0, 10)}.csv`);
      message('sr-export-status', 'CSV downloaded with every matching result.', 'ok');
    } catch (error) {
      if (active !== state.activeSearch || error.name === 'AbortError') return;
      message('sr-export-status', `Export failed: ${error.message}`, 'bad');
    } finally {
      if (active === state.activeSearch) { state.exporting = false; $('sr-export').disabled = !state.total; }
    }
  }

  for (const mode of Object.keys(MODES)) $(`sr-mode-${mode}`).addEventListener('click', () => setMode(mode));
  $('sr-form').addEventListener('submit', (event) => { event.preventDefault(); search(); });
  $('sr-collection').addEventListener('change', () => { state.collection = $('sr-collection').value; });
  $('sr-paths').addEventListener('change', () => { state.selectedPaths = new Set([...$('sr-paths').selectedOptions].map((o) => o.value)); });
  $('sr-clear-paths').addEventListener('click', () => {
    state.selectedPaths.clear();
    for (const option of $('sr-paths').options) option.selected = false;
  });
  $('sr-load-more').addEventListener('click', () => loadPage(true));
  $('sr-export').addEventListener('click', exportCsv);
  if (typeof IntersectionObserver === 'function') {
    new IntersectionObserver((entries) => {
      if (!root.hidden && entries.some((entry) => entry.isIntersecting)) loadPage(true);
    }, { rootMargin: '300px' }).observe($('sr-sentinel'));
  }
  setMode('semantic');

  async function show(route, { entering = false } = {}) {
    if (!state.started || entering) {
      state.started = true;
      loadFacets();
    }
    const key = keyOf(route.params);
    if (key && key !== state.lastKey) {
      state.lastKey = key;
      applyParams(route.params);
      return search();
    }
    // Back on Search from elsewhere: keep the URL describing what is shown.
    if (!key && state.activeSearch) ctx.replace(ctx.href('search', [], state.activeSearch.link));
    return undefined;
  }

  return {
    show,
    hide() {},
    // New results appear on the next search; refreshing only re-reads the filter options.
    refresh: loadFacets,
    state,
    actions: { search, setMode, renderHits, downloadPaper, loadPage, exportCsv, applyParams },
  };
}
