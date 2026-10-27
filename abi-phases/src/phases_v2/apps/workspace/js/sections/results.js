// Results: every ingested paper, and one paper's page with everything extracted from it.
//
// #/results?q=...&collection=...&prompt=...&model=...&has_results=...&request=...&sort=...&page=2
// lists papers; #/results/<paper_id>?group=<prompt_id|model_id>&a=...&b=... opens one,
// with a result group shown and two compared side by side.

import { fetchBlob, phases, PREFIXES, saveBlob } from '../api.js';
import {
  $, action, emptyRow, esc, fill, formatDate, formatNumber, latest, message, pagination, plural, tableHtml,
} from '../ui.js';
import {
  compareHtml, groupHtml, groupKey, groupLabel, headerHtml, ranRows,
} from './paper_view.js';

export const PAGE_SIZE = 50;
// Items drawn at once for one group; the rest follow on "Show all".
export const ITEM_LIMIT = 200;
const FILTERS = ['q', 'collection', 'prompt', 'model', 'has_results', 'sort', 'request'];

const template = () => `
  <header class="page-head"><p class="eyebrow">Step 4 · Explore results</p><h1 tabindex="-1">Results</h1>
    <p class="lede">Open any paper to see what each prompt version and model found in it, where in the paper, and how they compare.</p></header>
  <div id="res-view-list" class="stack">
    <section class="card">
      <form id="res-filters" role="search">
        <div class="grid three">
          <div><label for="res-q">Paper</label><input id="res-q" type="search" maxlength="300" placeholder="Title, PMID, file name or folder"></div>
          <div><label for="res-collection">Collection</label><select id="res-collection"></select></div>
          <div><label for="res-has">Results</label><select id="res-has"><option value="">With or without results</option><option value="true">With results</option><option value="false">Without results</option></select></div>
          <div><label for="res-prompt">Prompt</label><select id="res-prompt"></select></div>
          <div><label for="res-model">Model</label><select id="res-model"></select></div>
          <div><label for="res-sort">Sort by</label><select id="res-sort"><option value="title">Title A-Z</option><option value="newest">Newest ingestion first</option><option value="oldest">Oldest ingestion first</option></select></div>
        </div>
        <p class="hint">With a prompt or model chosen, only papers it ran on are listed, and the counts cover its runs only.</p>
        <div class="row actions"><button class="primary" id="res-apply">Show papers</button><button type="button" id="res-clear">Clear filters</button></div>
      </form>
      <p id="res-request" class="note" hidden></p>
    </section>
    <section class="card">
      <p id="res-summary" class="msg" role="status"></p>
      <div class="wide-table">${tableHtml('res-papers', ['Paper', 'Ingested', 'Chunks', 'Extractions', 'Results'], 'Papers')}</div>
      <div class="pager" aria-label="Paper pages"><button id="res-prev" type="button" disabled>Previous</button><span id="res-page-label">Page 1</span><button id="res-next" type="button" disabled>Next</button></div>
    </section>
  </div>
  <div id="res-view-paper" class="stack" hidden>
    <p><a id="res-back" href="#/results">Back to the papers</a></p>
    <section class="card">
      <div id="res-paper-head"></div>
      <div class="row actions"><button id="res-pdf" type="button">Download PDF</button><button id="res-csv" type="button">Download all results (CSV)</button></div>
      <p id="res-paper-message" class="msg" role="status"></p>
    </section>
    <section class="card">
      <h2>What ran on this paper</h2>
      <div class="wide-table">${tableHtml('res-ran', ['Prompt version', 'Model', 'Chunks read', 'Items found', 'Runs'], 'Prompt versions and models run on this paper')}</div>
      <h3>Runs that included it</h3>
      <div id="res-requests"></div>
    </section>
    <section class="card">
      <div class="card-head"><h2>Results</h2><button id="res-group-csv" type="button" class="small">Download these results (CSV)</button></div>
      <label for="res-group">Prompt version and model</label><select id="res-group"></select>
      <div id="res-group-body" class="try-results"></div>
      <div class="row center"><button id="res-group-more" type="button" hidden>Show all</button></div>
    </section>
    <section class="card">
      <h2>Compare two versions or models</h2>
      <div class="grid"><div><label for="res-compare-a">First</label><select id="res-compare-a"></select></div>
        <div><label for="res-compare-b">Second</label><select id="res-compare-b"></select></div></div>
      <div id="res-compare-body" class="try-results"></div>
    </section>
  </div>`;

// Filters as the API takes them.
export function listQuery(params, page = 1) {
  const query = new URLSearchParams();
  for (const [from, to] of [['q', 'q'], ['collection', 'collection'], ['prompt', 'prompt'], ['model', 'model'], ['has_results', 'has_results'], ['request', 'request_id']]) {
    const value = params.get(from);
    if (value) query.set(to, value);
  }
  query.set('sort', params.get('sort') || 'title');
  query.set('limit', PAGE_SIZE);
  query.set('offset', (Math.max(1, page) - 1) * PAGE_SIZE);
  return query;
}

export function itemCounts(paper) {
  const entries = Object.entries(paper.items || {});
  if (!entries.length) return '<span class="muted">None</span>';
  return `${formatNumber(paper.item_count)}<small>${esc(entries.map(([name, count]) => `${name}: ${formatNumber(count)}`).join(' · '))}</small>`;
}

export function create(root, ctx) {
  root.innerHTML = template();
  const state = {
    active: false, view: 'list', params: new URLSearchParams(), page: 1, pages: 0, loaded: false,
    collections: [], prompts: [], models: [], modelNames: {},
    paperId: '', detail: null, group: '', a: '', b: '', showAll: false, listHash: '#/results',
  };
  const listGuard = latest();
  const paperGuard = latest();
  const modelName = (id) => state.modelNames[id] || id;

  // ---- Choices ----

  function fillChoices() {
    const p = state.params;
    const collections = [{ collection_id: '', name: 'All papers' }, ...state.collections];
    if (p.get('collection') && !state.collections.some((c) => c.collection_id === p.get('collection'))) {
      collections.push({ collection_id: p.get('collection'), name: 'Archived or unknown collection' });
    }
    fill($('res-collection'), collections, 'collection_id', (c) => c.name, [p.get('collection') || '']);
    const names = [...new Set([...state.prompts, p.get('prompt')].filter(Boolean))].sort();
    fill($('res-prompt'), [{ name: '' }, ...names.map((name) => ({ name }))], 'name', (x) => x.name || 'Any prompt', [p.get('prompt') || '']);
    const models = [...new Set([...state.models, p.get('model')].filter(Boolean))];
    fill($('res-model'), [{ model_id: '' }, ...models.map((id) => ({ model_id: id }))], 'model_id', (m) => (m.model_id ? modelName(m.model_id) : 'Any model'), [p.get('model') || '']);
  }

  // The filters still work when one of these lists cannot load.
  async function loadChoices() {
    await Promise.all([
      phases('/collections?counts=false').then((d) => { state.collections = d.collections || []; }).catch(() => {}),
      phases('/prompts').then((d) => { state.prompts = [...new Set((d.prompts || []).map((p) => p.name))]; }).catch(() => {}),
      phases('/models').then((d) => {
        state.models = (d.models || []).map((m) => m.model_id);
        state.modelNames = Object.fromEntries((d.models || []).map((m) => [m.model_id, m.display_name]));
      }).catch(() => {}),
    ]);
    state.loaded = true;
    fillChoices();
  }

  // ---- The list ----

  function formParams() {
    const params = new URLSearchParams();
    const values = {
      q: $('res-q').value.trim(), collection: $('res-collection').value, prompt: $('res-prompt').value,
      model: $('res-model').value, has_results: $('res-has').value, request: state.params.get('request') || '',
      sort: $('res-sort').value === 'title' ? '' : $('res-sort').value,
    };
    for (const key of FILTERS) if (values[key]) params.set(key, values[key]);
    return params;
  }

  function applyParams(params) {
    state.params = new URLSearchParams([...params].filter(([key]) => FILTERS.includes(key)));
    state.page = Math.max(1, Number(params.get('page')) || 1);
    $('res-q').value = params.get('q') || '';
    $('res-has').value = params.get('has_results') || '';
    $('res-sort').value = params.get('sort') || 'title';
    fillChoices();
    const request = params.get('request');
    $('res-request').hidden = !request;
    if (request) {
      $('res-request').innerHTML = `Showing the papers run <a href="${esc(ctx.href('runs', [request]))}">${esc(request.slice(0, 8))}</a> covered. <a href="${esc(ctx.href('results', [], new URLSearchParams([...state.params].filter(([key]) => key !== 'request'))))}">Show every paper</a>`;
    }
  }

  function listHref(page = state.page) {
    const params = new URLSearchParams(state.params);
    if (page > 1) params.set('page', page);
    return ctx.href('results', [], params);
  }

  function renderPapers(data) {
    const body = $('res-papers');
    body.replaceChildren();
    if (!data.papers.length) {
      body.innerHTML = emptyRow(5, state.params.toString()
        ? 'No papers match these filters. Clear the filters to see every paper.'
        : 'No papers have been ingested yet. Run the pipeline on a collection first.');
      return;
    }
    for (const paper of data.papers) {
      const row = document.createElement('tr');
      const where = [paper.pmid ? `PMID ${paper.pmid}` : '', paper.path || paper.file_name].filter(Boolean).join(' · ');
      const chunks = Object.values(paper.chunks || {}).reduce((sum, n) => sum + n, 0);
      const { succeeded = 0, failed = 0 } = paper.extractions || {};
      row.innerHTML = `<td><a class="row-link" href="${esc(ctx.href('results', [paper.paper_id]))}">${esc(paper.title)}</a><small>${esc(where)}</small></td>`
        + `<td>${esc(formatDate(paper.discovered_at))}</td><td>${formatNumber(chunks)}</td>`
        + `<td>${formatNumber(succeeded)}${failed ? `<small class="bad">${esc(formatNumber(failed))} failed</small>` : ''}</td>`
        + `<td>${itemCounts(paper)}</td>`;
      body.append(row);
    }
  }

  function paging(loading = false) {
    const pages = pagination(state.page, state.pages, loading);
    $('res-prev').disabled = pages.prev;
    $('res-next').disabled = pages.next;
    $('res-page-label').textContent = pages.label;
  }

  async function loadList(page = state.page) {
    const token = listGuard.next();
    state.page = page;
    paging(true);
    message('res-summary', 'Loading papers...');
    try {
      const data = await phases(`/papers?${listQuery(state.params, page)}`);
      if (!listGuard.is(token)) return;
      state.pages = Math.ceil(data.total / PAGE_SIZE);
      if (state.pages && page > state.pages) { await loadList(state.pages); return; }
      state.listHash = listHref(page);
      // A late answer must not rewrite the URL of a section opened since.
      if (state.active && state.view === 'list') ctx.replace(state.listHash);
      const first = data.offset + 1;
      message('res-summary', data.total
        ? `Showing ${first}-${data.offset + data.papers.length} of ${plural(data.total, 'paper')}.`
        : '');
      renderPapers(data);
    } catch (error) {
      if (!listGuard.is(token)) return;
      state.pages = 0;
      $('res-papers').replaceChildren();
      message('res-summary', `Could not load the papers: ${error.message}`, 'bad');
    } finally {
      if (listGuard.is(token)) paging();
    }
  }

  // ---- One paper ----

  const groups = () => state.detail?.results || [];
  const findGroup = (key) => groups().find((g) => groupKey(g) === key);

  function paperHref() {
    return ctx.href('results', [state.paperId], { group: state.group, a: state.a, b: state.b });
  }

  function renderGroup() {
    const group = findGroup(state.group);
    $('res-group-csv').disabled = !group;
    $('res-group-more').hidden = true;
    if (!group) {
      $('res-group-body').innerHTML = '<p class="empty">Nothing has been run on this paper yet. Run the pipeline on a collection that holds it.</p>';
      return;
    }
    const limit = state.showAll ? Infinity : ITEM_LIMIT;
    $('res-group-body').innerHTML = groupHtml(group, state.detail.chunks, limit);
    if (group.items.length > limit) {
      $('res-group-more').hidden = false;
      $('res-group-more').textContent = `Show all ${formatNumber(group.items.length)} items`;
    }
  }

  function renderCompare() {
    const [a, b] = [findGroup(state.a), findGroup(state.b)];
    $('res-compare-body').innerHTML = a && b
      ? compareHtml(a, b, state.detail.chunks, { modelName })
      : '<p class="empty">Two versions or models must have run on this paper to compare them.</p>';
  }

  function renderPaper() {
    const detail = state.detail;
    $('res-paper-head').innerHTML = headerHtml(detail);
    const ran = ranRows(detail, { modelName, href: ctx.href });
    $('res-ran').innerHTML = ran.length ? ran.join('') : emptyRow(5, 'Nothing has been run on this paper yet.');
    $('res-requests').innerHTML = detail.requests.length
      ? `<ul>${detail.requests.map((r) => `<li><a href="${esc(ctx.href('runs', [r.request_id]))}">${esc(formatDate(r.requested_at))}</a> · ${esc(r.status)} · ${esc(modelName(r.model_id))}${r.requested_by ? ` · ${esc(r.requested_by)}` : ''}</li>`).join('')}</ul>`
      : '<p class="muted">No recorded run included this paper.</p>';
    $('res-csv').disabled = !groups().length;
    const options = groups().map((g) => ({ key: groupKey(g), label: `${groupLabel(g, modelName)} · ${plural(g.item_count, 'item')}` }));
    const keys = options.map((o) => o.key);
    if (!keys.includes(state.group)) state.group = keys[0] || '';
    if (!keys.includes(state.a)) state.a = keys[0] || '';
    if (!keys.includes(state.b) || (state.b === state.a && keys.length > 1)) state.b = keys.find((k) => k !== state.a) || '';
    fill($('res-group'), options, 'key', (o) => o.label, [state.group]);
    fill($('res-compare-a'), options, 'key', (o) => o.label, [state.a]);
    fill($('res-compare-b'), options, 'key', (o) => o.label, [state.b]);
    renderGroup();
    renderCompare();
    if (state.active && state.view === 'paper') ctx.replace(paperHref());
  }

  // `quiet` re-reads the open paper in place, keeping what is shown until the answer comes.
  async function loadPaper(params, { quiet = false } = {}) {
    const token = paperGuard.next();
    const id = state.paperId;
    state.group = params.get('group') || '';
    state.a = params.get('a') || '';
    state.b = params.get('b') || '';
    if (!quiet) {
      state.showAll = false;
      $('res-paper-head').innerHTML = '<p class="muted">Loading the paper...</p>';
      for (const target of ['res-ran', 'res-requests', 'res-group-body', 'res-compare-body']) $(target).replaceChildren();
      message('res-paper-message');
    }
    try {
      const detail = await phases(`/papers/${encodeURIComponent(id)}`);
      if (!paperGuard.is(token)) return;
      state.detail = detail;
      renderPaper();
    } catch (error) {
      if (!paperGuard.is(token)) return;
      state.detail = null;
      $('res-paper-head').innerHTML = `<h2 id="res-paper-title" tabindex="-1">Paper unavailable</h2>`;
      message('res-paper-message', error.status === 404 ? 'This paper is not in the corpus. It may not have been ingested yet.' : `Could not load this paper: ${error.message}`, 'bad');
    }
  }

  function fileName(extension) {
    const paper = state.detail?.paper;
    if (!paper) return `paper.${extension}`;
    if (extension === 'pdf' && paper.pmid) return `PMID-${paper.pmid}.pdf`;
    if (extension === 'pdf') return paper.file_name || 'paper.pdf';
    return `healthyphases-${paper.pmid ? `PMID-${paper.pmid}` : paper.paper_id.slice(0, 12)}.csv`;
  }

  async function downloadPdf() {
    const params = new URLSearchParams({ paper_id: state.paperId });
    const blob = await fetchBlob(`${PREFIXES.search}/paper?${params}`, { accept: 'application/pdf', notFound: 'The PDF of this paper is unavailable.' });
    saveBlob(blob, fileName('pdf'));
  }

  async function downloadCsv(group) {
    const params = new URLSearchParams();
    if (group) { params.set('prompt_id', group.prompt_id); params.set('model_id', group.model_id || ''); }
    const blob = await fetchBlob(`${PREFIXES.phases}/papers/${encodeURIComponent(state.paperId)}/export?${params}`, { accept: 'text/csv' });
    saveBlob(blob, fileName('csv'));
    message('res-paper-message', group ? `Results of ${groupLabel(group, modelName)} downloaded.` : 'Every result of this paper downloaded.', 'ok');
  }

  // ---- Wiring ----

  $('res-filters').addEventListener('submit', (event) => {
    event.preventDefault();
    ctx.navigate(ctx.href('results', [], formParams()));
  });
  $('res-clear').addEventListener('click', () => ctx.navigate(ctx.href('results')));
  $('res-prev').addEventListener('click', () => loadList(state.page - 1));
  $('res-next').addEventListener('click', () => loadList(state.page + 1));
  $('res-pdf').addEventListener('click', () => action($('res-pdf'), 'res-paper-message', downloadPdf));
  $('res-csv').addEventListener('click', () => action($('res-csv'), 'res-paper-message', () => downloadCsv(null)));
  $('res-group-csv').addEventListener('click', () => action($('res-group-csv'), 'res-paper-message', () => downloadCsv(findGroup(state.group))));
  $('res-group').addEventListener('change', () => { state.group = $('res-group').value; state.showAll = false; renderGroup(); ctx.replace(paperHref()); });
  $('res-group-more').addEventListener('click', () => { state.showAll = true; renderGroup(); });
  for (const side of ['a', 'b']) {
    $(`res-compare-${side}`).addEventListener('change', () => { state[side] = $(`res-compare-${side}`).value; renderCompare(); ctx.replace(paperHref()); });
  }

  async function show(route, { entering = false } = {}) {
    state.active = true;
    const id = route.parts[0] || '';
    state.view = id ? 'paper' : 'list';
    $('res-view-list').hidden = state.view !== 'list';
    $('res-view-paper').hidden = state.view !== 'paper';
    const choices = !state.loaded || entering ? loadChoices() : null;
    if (id) {
      $('res-back').href = state.listHash;
      const opened = id !== state.paperId || !state.detail;
      state.paperId = id;
      if (choices) await choices;
      await loadPaper(route.params);
      if (opened) $('res-paper-title').focus();
      return;
    }
    if (choices) await choices;
    applyParams(route.params);
    await loadList(state.page);
  }

  async function refresh() {
    if (state.view === 'paper' && state.paperId) {
      const params = new URLSearchParams({ group: state.group, a: state.a, b: state.b });
      return loadPaper(params, { quiet: true });
    }
    return loadList(state.page);
  }

  return {
    show, hide() { state.active = false; }, refresh, state,
    actions: { loadList, loadPaper, downloadPdf, downloadCsv, renderGroup, renderCompare, formParams, applyParams },
  };
}
