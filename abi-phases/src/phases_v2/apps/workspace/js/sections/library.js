// Library: PubMed searches, downloads, schedules, the paper library and OpenAlex enrichment.
//
// Views: #/library (papers), #/library/search, #/library/downloads,
// #/library/schedules and #/library/enrichment (only when OpenAlex is enabled).

import { openalex, phases, pubmed } from '../api.js';
import {
  $, action, emptyRow, esc, fill, formatDate, latest, message, pagination, plural, statusPill, tableHtml,
} from '../ui.js';

const VIEWS = {
  papers: 'Papers',
  search: 'Search PubMed',
  downloads: 'Downloads',
  schedules: 'Schedules',
  enrichment: 'Enrichment',
};

const FREQUENCIES = { 1: 'Every hour', 24: 'Every day', 168: 'Every week' };
const SCHEDULE_STATUS = { idle: 'Not run yet', running: 'Running', succeeded: 'Completed', failed: 'Failed' };
const BACKFILL_STATUS = {
  pending: 'Queued', running: 'Discovering papers', waiting: 'Downloading batch',
  succeeded: 'Completed', partial: 'Completed with failures', failed: 'Interrupted',
};
const FILTER_DEFAULTS = {
  search: '', query_id: '', status: 'published', ingested_from: '', ingested_until: '', sort: 'newest',
  page_size: 50, enrichment_status: '', min_citations: 0, topic: '', institution: '',
};
const FILTER_INPUTS = {
  search: 'lib-filter-search', query_id: 'lib-filter-query', status: 'lib-filter-status',
  ingested_from: 'lib-filter-from', ingested_until: 'lib-filter-until', sort: 'lib-filter-sort',
  page_size: 'lib-filter-size', enrichment_status: 'lib-filter-enrichment', min_citations: 'lib-filter-citations',
  topic: 'lib-filter-topic', institution: 'lib-filter-institution',
};

export const frequency = (hours) => FREQUENCIES[hours] || `Every ${hours} hours`;
const pubmedLink = (pmid, title) => `<a href="https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(pmid)}/" target="_blank" rel="noopener noreferrer">${esc(title || 'Untitled paper')}</a>`;

export function safeLink(url, label) {
  if (!/^https?:\/\//i.test(url || '')) return esc(label);
  return `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`;
}

// A saved search is named by its query text and when it was made.
export const queryLabel = (q) => `${q.query} · ${formatDate(q.created_at)}`;

const template = () => `
  <header class="page-head"><p class="eyebrow">Step 1 · Collect papers</p><h1 tabindex="-1">Library</h1>
    <p class="lede">Find papers on PubMed, download them, keep searches up to date and enrich them with citation data.</p></header>
  <nav class="tabs" aria-label="Library views">${Object.entries(VIEWS).map(([view, label]) => `<a id="lib-tab-${view}" href="#/library/${view}" ${view === 'enrichment' ? 'hidden' : ''}>${label}</a>`).join('')}</nav>

  <div id="lib-view-papers" class="stack" hidden>
    <section class="card">
      <div class="card-head"><div><h2>Paper library</h2><p class="muted">Every paper across your saved searches and full ingestions, listed once.</p></div>
        <div class="row"><button id="lib-enrich-library" type="button" hidden>Enrich selected search</button><button id="lib-refresh-library" type="button">Refresh papers</button></div></div>
      <form id="lib-filters"><div class="filters">
        <div><label for="lib-filter-search">Search your library</label><input id="lib-filter-search" maxlength="300" placeholder="Title, author, journal, PMID or DOI"></div>
        <div><label for="lib-filter-query">Saved search</label><select id="lib-filter-query"><option value="">All searches</option></select></div>
        <div><label for="lib-filter-status">Papers to show</label><select id="lib-filter-status"><option value="published">Downloaded papers</option><option value="all">All discovered records</option><option value="unpublished">Not downloaded</option></select></div>
        <div><label for="lib-filter-from">Ingested from (UTC)</label><input id="lib-filter-from" type="date"></div>
        <div><label for="lib-filter-until">Ingested until (UTC)</label><input id="lib-filter-until" type="date"></div>
        <div><label for="lib-filter-sort">Sort by</label><select id="lib-filter-sort"><option value="newest">Newest ingestion first</option><option value="oldest">Oldest ingestion first</option><option value="title">Title A-Z</option></select></div>
        <div><label for="lib-filter-size">Papers per page</label><select id="lib-filter-size"><option value="25">25</option><option value="50" selected>50</option><option value="100">100</option></select></div>
        <div class="oa-filter" hidden><label for="lib-filter-enrichment">OpenAlex status</label><select id="lib-filter-enrichment"><option value="">Any status</option><option value="enriched">Enriched</option><option value="not_enriched">Not enriched</option><option value="no_match">No exact match</option><option value="ambiguous">Ambiguous match</option><option value="failed">Refresh failed</option></select></div>
        <div class="oa-filter" hidden><label for="lib-filter-citations">Minimum citations</label><input id="lib-filter-citations" type="number" min="0" max="2147483647" value="0"></div>
        <div class="oa-filter" hidden><label for="lib-filter-topic">OpenAlex topic</label><input id="lib-filter-topic" maxlength="300"></div>
        <div class="oa-filter" hidden><label for="lib-filter-institution">Institution</label><input id="lib-filter-institution" maxlength="300"></div>
      </div><div class="row"><button id="lib-apply" class="primary">Apply filters</button><button id="lib-clear" type="button">Clear filters</button></div></form>
      <p class="hint">Ingestion dates refer to a paper's latest downloaded PDF; reusing the same PDF does not change that date. Date filters include the whole UTC day.</p>
      <p id="lib-summary" class="msg" role="status" aria-live="polite"></p>
      <div class="pager" aria-label="Paper pages, top"><button id="lib-prev-top" type="button" disabled>Previous</button><span id="lib-page-label-top">Page 1</span><button id="lib-next-top" type="button" disabled>Next</button></div>
      ${tableHtml('lib-papers', ['Paper', 'Published', 'Last ingested', 'Files'], 'Papers in the library')}
      <form id="lib-pagination" class="pager" aria-label="Paper pages"><button id="lib-prev" type="button" disabled>Previous</button><span id="lib-page-label">Page 1</span><button id="lib-next" type="button" disabled>Next</button>
        <label for="lib-page-number">Go to page</label><input id="lib-page-number" type="number" min="1" value="1" required><button id="lib-go" disabled>Go</button></form>
    </section>
  </div>

  <div id="lib-view-search" class="stack" hidden>
    <section class="card">
      <h2>Search PubMed</h2>
      <form id="lib-search-form">
        <label for="lib-query">PubMed query</label>
        <div class="search-row"><input id="lib-query" required maxlength="2000" placeholder="e.g. solitude AND mental health" autocomplete="off"><button class="primary" id="lib-search">Search</button></div>
        <div class="grid four">
          <div><label for="lib-start">Published from</label><input type="date" id="lib-start"></div>
          <div><label for="lib-end">Published until</label><input type="date" id="lib-end"></div>
          <div><label for="lib-sort">Sort results</label><select id="lib-sort"><option value="relevance">Best match</option><option value="pub_date">Publication date</option></select></div>
          <div><label for="lib-limit">Maximum results</label><input id="lib-limit" type="number" min="1" max="1000" value="100" required></div>
        </div>
      </form>
      <p class="hint">Searching saves the search and its paper records only. Nothing is downloaded until you choose to ingest.</p>
      <p id="lib-message" class="msg" role="status" aria-live="polite"></p>
    </section>
    <section class="card">
      <div class="card-head"><h2>Results</h2>
        <div class="row"><button id="lib-ingest" class="primary" disabled>Ingest previewed papers</button><button id="lib-ingest-all" disabled>Ingest all matching papers</button></div></div>
      <div class="row end">
        <div class="grow"><label for="lib-history">Previous searches</label><select id="lib-history"><option value="">Choose a search</option></select></div>
        <button id="lib-refresh-history" type="button">Refresh searches</button>
        <button id="lib-browse-query" type="button" disabled>Browse downloaded papers</button>
        <button id="lib-collect-query" type="button" disabled>Add search to a collection</button>
        <a id="lib-schedule-query" class="button" href="#/library/schedules">Schedule this search</a>
        <button id="lib-enrich-query" type="button" hidden disabled>Enrich with OpenAlex</button>
      </div>
      <p id="lib-preview-summary" class="muted">Run a search, or choose a previous one, to preview its papers.</p>
      ${tableHtml('lib-preview', ['Paper', 'Published', 'Full text'], 'Search results')}
    </section>
  </div>

  <div id="lib-view-downloads" class="stack" hidden>
    <section class="card">
      <div class="card-head"><div><h2>Ingestion requests</h2><p class="muted">Downloads of previewed papers. Requests run when the orchestrator is available.</p></div><button id="lib-refresh-requests" type="button">Refresh status</button></div>
      <p id="lib-request-message" class="msg" role="status"></p>
      ${tableHtml('lib-requests', ['Search', 'Status', 'Progress', 'Details'], 'Ingestion requests')}
    </section>
    <section class="card">
      <div class="card-head"><div><h2>Full ingestions</h2><p class="muted">Every matching record of a search, downloaded in batches. Saved date filters still apply.</p></div><button id="lib-refresh-backfills" type="button">Refresh progress</button></div>
      <p class="hint">There is no total-paper limit. Published PDFs are reused. PubMed can change while a large ingestion runs, so the initial match count is an estimate. Interrupted discovery can be resumed here; failed downloads can be retried above.</p>
      <p id="lib-backfill-status" class="msg" role="status" aria-live="polite"></p>
      ${tableHtml('lib-backfills', ['Search', 'Status', 'Discovery', 'Downloads', 'Actions'], 'Full ingestions')}
    </section>
  </div>

  <div id="lib-view-schedules" class="stack" hidden>
    <section class="card">
      <div class="card-head"><div><h2>Scheduled searches</h2><p class="muted">Repeat saved searches and optionally download the new papers they find.</p></div><button id="lib-refresh-schedules" type="button">Refresh schedules</button></div>
      <p class="hint">Times are in your local timezone. Disabling stops future runs; work already started can finish. Re-enabling starts a fresh interval.</p>
      <p id="lib-schedule-status" class="msg" role="status" aria-live="polite"></p>
      ${tableHtml('lib-schedules', ['Search', 'Schedule', 'Next run', 'Last run', 'Actions'], 'Scheduled searches')}
    </section>
    <section class="card">
      <h2>Schedule a saved search</h2>
      <p class="muted">The search's query, dates, sort order and result limit are kept.</p>
      <form id="lib-schedule-form">
        <div class="grid three">
          <div><label for="lib-schedule-search">Saved search</label><select id="lib-schedule-search" required><option value="">Choose a search</option></select></div>
          <div><label for="lib-schedule-name">Schedule name</label><input id="lib-schedule-name" maxlength="120" required placeholder="e.g. Weekly solitude research"></div>
          <div><label for="lib-schedule-frequency">Repeat</label><select id="lib-schedule-frequency"><option value="1">Every hour</option><option value="24" selected>Every day</option><option value="168">Every week</option></select></div>
        </div>
        <label class="check"><input type="checkbox" id="lib-schedule-ingest" checked>Download newly found papers</label>
        <label class="check"><input type="checkbox" id="lib-schedule-enabled" checked>Enable this schedule</label>
        <p class="hint">The first run is one interval after creation. Downloading skips papers already published or queued. Searches keep their result limit, so narrow broad queries to avoid missing papers. Pipeline runs stay separate.</p>
        <button id="lib-save-schedule" class="primary">Create schedule</button>
        <p id="lib-schedule-message" class="msg" role="status" aria-live="polite"></p>
      </form>
    </section>
  </div>

  <div id="lib-view-enrichment" class="stack" hidden>
    <section class="card">
      <h2>Enrich a saved search</h2>
      <p class="muted">Adds citations, topics, affiliations, references and open-access locations from OpenAlex to every record saved for the search, including papers without a PDF.</p>
      <form id="lib-enrich-form" class="row end">
        <div class="grow"><label for="lib-enrich-search">Saved search</label><select id="lib-enrich-search" required><option value="">Choose a search</option></select></div>
        <button id="lib-enrich-submit" class="primary">Queue enrichment</button>
        <button id="lib-enrich-refresh-queries" type="button">Refresh searches</button>
      </form>
      <p id="lib-enrich-message" class="msg" role="status"></p>
      <p id="lib-oa-configuration" class="hint"></p>
    </section>
    <section class="card">
      <div class="card-head"><h2>Enrichment requests</h2><button id="lib-refresh-enrichment" type="button">Refresh progress</button></div>
      <p id="lib-enrichment-message" class="msg" role="status"></p>
      ${tableHtml('lib-enrichment-requests', ['Search', 'Status', 'Progress', 'Actions'], 'Enrichment requests')}
    </section>
  </div>

  <p class="hint">Literature metadata: NCBI PubMed. Full text: NLM PubMed Central. Citation data: OpenAlex.</p>
  <dialog id="lib-detail" aria-labelledby="lib-detail-title" class="wide"><h2 id="lib-detail-title">OpenAlex details</h2><div id="lib-detail-content" role="status"></div><div class="dialog-actions"><button id="lib-close-detail" type="button">Close</button></div></dialog>`;

export function create(root, ctx) {
  root.innerHTML = template();
  const state = {
    view: 'papers', active: false, queryId: '', papers: [], queries: [],
    libraryPage: 1, libraryPages: 0, libraryFilters: null, backfillsLoading: false, oaAvailable: false,
  };
  const previewGuard = latest();
  const libraryGuard = latest();
  const enrichmentGuard = latest();
  const detailGuard = latest();
  const queryText = (id) => state.queries.find((q) => q.query_id === id)?.query || 'Saved search';

  // ---- Collections ----

  // A paper with a downloaded PDF, or a whole saved search, joins a collection
  // through the picker Collections provides.
  function collectButton(target, label, commands, what) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'small';
    button.textContent = 'Add to collection';
    button.setAttribute('aria-label', `Add ${label} to a collection`);
    button.addEventListener('click', () => action(button, target, () => ctx.section('collections').addToCollection(commands, what)));
    return button;
  }

  // ---- Search PubMed ----

  function renderPreview(papers) {
    state.papers = papers;
    $('lib-preview').replaceChildren();
    if (!papers.length) $('lib-preview').innerHTML = emptyRow(3, state.queryId ? 'This search found no papers. Try a broader query.' : 'Run a search to preview its papers here.');
    for (const p of papers) {
      const row = document.createElement('tr');
      row.innerHTML = `<td>${pubmedLink(p.pmid, p.title)}<small>${esc(p.journal)} · PMID ${esc(p.pmid)}</small></td><td>${esc(p.publication_date || '—')}</td><td>${p.artifacts?.length ? statusPill('published', 'Downloaded') : (p.pmcid ? 'Checked during ingestion' : 'No PMC record')}</td>`;
      if (p.artifacts?.length) {
        const title = p.title || `PMID ${p.pmid}`;
        row.lastElementChild.append(collectButton('lib-message', title, [{ paper: { pmid: p.pmid } }], `"${title}"`));
      }
      $('lib-preview').append(row);
    }
    $('lib-ingest').disabled = !papers.length;
    $('lib-ingest-all').disabled = !state.queryId;
    $('lib-browse-query').disabled = !state.queryId;
    $('lib-collect-query').disabled = !state.queryId;
    $('lib-enrich-query').disabled = !state.queryId;
    $('lib-schedule-query').href = ctx.href('library', ['schedules'], { query: state.queryId });
  }

  async function search() {
    const token = previewGuard.next();
    state.queryId = '';
    renderPreview([]);
    message('lib-message', 'Searching PubMed...');
    const data = await pubmed('/search', {
      method: 'POST',
      body: { query: $('lib-query').value.trim(), start_date: $('lib-start').value, end_date: $('lib-end').value, sort: $('lib-sort').value, max_results: Number($('lib-limit').value) },
    });
    if (!previewGuard.is(token)) return;
    state.queryId = data.query.query_id;
    renderPreview(data.papers);
    $('lib-preview-summary').textContent = `${data.papers.length} of ${data.query.total} matching papers.${data.truncated ? ' This is a preview: choose Ingest all matching papers to download the whole search.' : ''}`;
    message('lib-message', 'Search saved. Review the results, then choose what to ingest.', 'ok');
    ctx.replace(ctx.href('library', ['search'], { query: state.queryId }));
    await history();
  }

  async function chooseQuery(queryId = $('lib-history').value) {
    const token = previewGuard.next();
    state.queryId = queryId;
    renderPreview([]);
    ctx.replace(ctx.href('library', ['search'], { query: queryId }));
    if (!queryId) { $('lib-preview-summary').textContent = 'Run a search, or choose a previous one, to preview its papers.'; return; }
    const data = await pubmed(`/queries/${encodeURIComponent(queryId)}/papers`);
    if (!previewGuard.is(token)) return;
    renderPreview(data.papers);
    $('lib-preview-summary').textContent = `Showing ${data.papers.length} of ${data.total ?? data.papers.length} discovered papers in this saved search.`;
  }

  async function ingest() {
    if (!state.queryId || !state.papers.length) throw new Error('Choose a search with papers first.');
    const row = await pubmed('/requests', { method: 'POST', body: { query_id: state.queryId, pmids: state.papers.map((p) => p.pmid) } });
    message('lib-message', `Download of ${plural(state.papers.length, 'paper')} queued. Follow it under Downloads.`, 'ok');
    ctx.toast(`Ingestion request ${row.request_id.slice(0, 8)} queued.`);
    await requests();
  }

  // Confirms the saved search, not whatever is typed in the form now.
  function openBackfill() {
    const query = state.queries.find((q) => q.query_id === state.queryId);
    if (!query) throw new Error('Choose a saved search first.');
    return ctx.confirm({
      title: 'Ingest all matching papers?',
      body: [
        `Search: ${query.query}. Published ${query.start_date || 'from the beginning'} to ${query.end_date || 'any date'}. The saved search reported ${query.total} matches; the ${query.max_results}-paper preview limit will not apply.`,
        'This searches beyond the preview and downloads every available PDF in batches. Published PDFs are reused; some records have no accessible full text.',
      ],
      confirmLabel: 'Start full ingestion',
      run: () => createBackfill(query.query_id),
    });
  }

  async function createBackfill(queryId) {
    const row = await pubmed('/backfills', { method: 'POST', body: { query_id: queryId } });
    ctx.navigate(ctx.href('library', ['downloads']));
    await backfills();
    message('lib-backfill-status', `Full ingestion ${row.backfill_id.slice(0, 8)} queued. Progress is saved as each batch completes.`, 'ok');
  }

  async function history() {
    state.queries = (await pubmed('/queries')).queries;
    // A choice that no longer exists falls back to the placeholder rather than a blank select.
    const fillQueries = (id, placeholder, label = queryLabel, chosen = $(id).value) => {
      fill($(id), [{ query_id: '', placeholder }, ...state.queries], 'query_id', (q) => (q.query_id ? label(q) : q.placeholder), [chosen || '']);
    };
    fillQueries('lib-history', 'Choose a search', queryLabel, state.queryId);
    fillQueries('lib-schedule-search', 'Choose a search', (q) => `${q.query} (${q.start_date || 'any start'} to ${q.end_date || 'any end'}) · ${formatDate(q.created_at)}`);
    fillQueries('lib-filter-query', 'All searches');
    fillQueries('lib-enrich-search', 'Choose a search');
  }

  // ---- Paper library ----

  function libraryFilters() {
    const value = (key) => $(FILTER_INPUTS[key]).value;
    return {
      search: value('search').trim(), query_id: value('query_id'), status: value('status') || 'published',
      ingested_from: value('ingested_from'), ingested_until: value('ingested_until'), sort: value('sort') || 'newest',
      page_size: Number(value('page_size') || 50), enrichment_status: value('enrichment_status'),
      min_citations: Number(value('min_citations') || 0), topic: value('topic').trim(), institution: value('institution').trim(),
    };
  }

  function setFilters(filters) {
    for (const [key, id] of Object.entries(FILTER_INPUTS)) $(id).value = String(filters[key] ?? FILTER_DEFAULTS[key]);
  }

  // Only non-default filters go in the URL, so a plain #/library stays plain.
  function filterParams(filters, page) {
    const params = {};
    for (const [key, value] of Object.entries(filters)) if (String(value) !== String(FILTER_DEFAULTS[key])) params[key] = value;
    if (page > 1) params.page = page;
    return params;
  }

  function filtersFromParams(params) {
    const filters = { ...FILTER_DEFAULTS };
    for (const key of Object.keys(FILTER_DEFAULTS)) if (params.has(key)) filters[key] = params.get(key);
    filters.page_size = Number(filters.page_size) || 50;
    filters.min_citations = Number(filters.min_citations) || 0;
    return filters;
  }

  function libraryPaging(loading = false) {
    const paging = pagination(state.libraryPage, state.libraryPages, loading);
    for (const id of ['lib-prev', 'lib-prev-top']) $(id).disabled = paging.prev;
    for (const id of ['lib-next', 'lib-next-top']) $(id).disabled = paging.next;
    $('lib-go').disabled = paging.go;
  }

  function filesCell(artifacts) {
    if (!artifacts.length) return statusPill('unavailable', 'Not downloaded');
    return `<details><summary>${plural(artifacts.length, 'PDF version')}</summary>${artifacts.map((a) => `<p><small>Storage location</small><code>${esc(a.storage_prefix)}/${esc(a.storage_key)}</code><small>SHA-256</small><code>${esc(a.content_sha256)}</code></p>`).join('')}</details>`;
  }

  // A downloaded paper that has been ingested links to its results. Optional:
  // the library reads the same without it.
  async function linkResults(shown, token) {
    const ids = [...new Set(shown.flatMap(([, hashes]) => hashes))].slice(0, 200);
    if (!ids.length) return;
    let ingested;
    try {
      const params = new URLSearchParams([...ids.map((id) => ['paper_id', id]), ['limit', 200]]);
      ingested = new Set((await phases(`/papers?${params}`)).papers.map((p) => p.paper_id));
    } catch (_unavailable) {
      return;
    }
    if (!libraryGuard.is(token)) return;
    for (const [tr, hashes] of shown) {
      const id = hashes.find((hash) => ingested.has(hash));
      if (!id) continue;
      const link = document.createElement('a');
      link.className = 'button small';
      link.href = ctx.href('results', [id]);
      link.textContent = 'Open results';
      tr.lastElementChild.append(link);
    }
  }

  async function library(page = state.libraryPage) {
    if (!state.libraryFilters) state.libraryFilters = libraryFilters();
    const token = libraryGuard.next();
    libraryPaging(true);
    $('lib-papers').replaceChildren();
    message('lib-summary', 'Loading papers...');
    try {
      const params = new URLSearchParams({ ...state.libraryFilters, page });
      const data = await pubmed(`/papers?${params}`);
      if (!libraryGuard.is(token)) return;
      if (data.total_pages > 0 && page > data.total_pages) return library(data.total_pages);
      state.libraryPage = data.total ? data.page : 1;
      state.libraryPages = data.total_pages;
      const label = pagination(state.libraryPage, data.total ? data.total_pages : 0).label;
      $('lib-page-label').textContent = label;
      $('lib-page-label-top').textContent = label;
      $('lib-page-number').value = state.libraryPage;
      $('lib-page-number').max = Math.max(1, data.total_pages);
      if (state.view === 'papers') ctx.replace(ctx.href('library', [], filterParams(state.libraryFilters, state.libraryPage)));
      const first = (data.page - 1) * data.page_size + 1;
      message('lib-summary', data.total
        ? `Showing ${first}-${first + data.papers.length - 1} of ${data.total} papers.`
        : 'No papers match these filters. Clear the filters, or search PubMed and download papers first.');
      if (!data.total) $('lib-papers').innerHTML = emptyRow(4, 'Nothing to show yet.');
      const shown = [];
      for (const row of data.papers) {
        const p = row.paper;
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${pubmedLink(p.pmid, p.title)}<small>${esc((p.authors || []).join(', '))}</small><small>${esc(p.journal)} · PMID ${esc(p.pmid)}${p.doi ? ` · DOI ${esc(p.doi)}` : ''}</small></td><td>${esc(p.publication_date || '—')}</td><td>${esc(formatDate(row.last_ingested_at, 'Not downloaded'))}</td><td>${filesCell(row.artifacts || [])}</td>`;
        if (row.openalex && row.openalex.status !== 'not_enriched') {
          const detail = document.createElement('button');
          detail.type = 'button';
          detail.className = 'small';
          detail.textContent = row.openalex.work_id
            ? `OpenAlex: ${row.openalex.citation_count} citations${row.openalex.status === 'failed' ? ' (refresh failed)' : ''}`
            : `OpenAlex: ${row.openalex.status}`;
          detail.addEventListener('click', () => paperDetail(p.pmid, p.title));
          tr.firstElementChild.append(detail);
        }
        if (row.artifacts?.length) {
          const title = p.title || `PMID ${p.pmid}`;
          tr.lastElementChild.append(collectButton('lib-summary', title, [{ paper: { pmid: p.pmid } }], `"${title}"`));
        }
        $('lib-papers').append(tr);
        shown.push([tr, (row.artifacts || []).map((a) => a.content_sha256).filter(Boolean)]);
      }
      linkResults(shown, token);
    } catch (error) {
      if (libraryGuard.is(token)) { state.libraryPages = 0; message('lib-summary', error.message, 'bad'); }
    } finally {
      if (libraryGuard.is(token)) libraryPaging();
    }
  }

  async function applyLibrary() {
    state.libraryFilters = libraryFilters();
    await library(1);
  }

  async function clearLibrary() {
    setFilters(FILTER_DEFAULTS);
    await applyLibrary();
  }

  // Opens the library on exactly one saved search, with every other filter cleared.
  async function openLibrary(queryId) {
    await history();
    setFilters({ ...FILTER_DEFAULTS, query_id: queryId });
    state.libraryFilters = libraryFilters();
    state.libraryPage = 1;
    ctx.navigate(ctx.href('library', [], filterParams(state.libraryFilters, 1)));
  }

  // ---- Downloads ----

  async function requests() {
    const data = await pubmed('/requests');
    $('lib-requests').replaceChildren();
    if (!data.requests.length) $('lib-requests').innerHTML = emptyRow(4, 'No ingestion requests yet. Search PubMed and ingest the previewed papers.');
    for (const row of data.requests) {
      const outcomes = Object.values(row.outcomes || {});
      const ready = outcomes.filter((o) => o.status === 'ready').length;
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${esc(queryText(row.query_id))}<small>Requested ${esc(formatDate(row.requested_at))}</small></td><td>${statusPill(row.status)}</td><td>${ready} published / ${row.pmids.length} requested</td><td><details><summary>Paper outcomes</summary><pre>${esc(JSON.stringify({ error: row.error, papers: row.outcomes }, null, 2))}</pre></details></td>`;
      if (['failed', 'partial'].includes(row.status)) {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = 'Retry remaining';
        button.addEventListener('click', () => action(button, 'lib-request-message', async () => {
          await pubmed(`/requests/${encodeURIComponent(row.request_id)}/retry`, { method: 'POST' });
          await requests();
          ctx.toast('Retry queued for the remaining papers.');
        }));
        tr.lastElementChild.append(button);
      }
      $('lib-requests').append(tr);
    }
    message('lib-request-message', data.requests.length ? `Updated ${new Date().toLocaleTimeString()}.` : '');
  }

  async function backfills() {
    if (state.backfillsLoading) return;
    state.backfillsLoading = true;
    try {
      const data = await pubmed('/backfills');
      $('lib-backfills').replaceChildren();
      if (!data.backfills.length) $('lib-backfills').innerHTML = emptyRow(5, 'No full ingestions yet. Search PubMed, then choose Ingest all matching papers.');
      for (const row of data.backfills) {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td>${esc(row.search.query)}<small>Published ${esc(row.search.start_date || 'any start')} to ${esc(row.search.end_date || 'any end')}</small></td><td>${statusPill(row.status, BACKFILL_STATUS[row.status] || row.status)}${row.error ? `<small class="bad">${esc(row.error)}</small>` : ''}</td><td>${row.discovered} discovered<small>${row.total} initial matches</small><small>${row.discovery_complete ? 'Discovery finished' : 'Discovery continues in batches'}</small></td><td>${row.published} published<small>${row.unavailable} unavailable · ${row.failed} failed</small><small>${row.completed} processed · ${row.remaining} pending in discovered batches</small></td><td></td>`;
        if (row.status === 'failed') {
          const resume = document.createElement('button');
          resume.type = 'button';
          resume.textContent = 'Resume';
          resume.addEventListener('click', () => action(resume, 'lib-backfill-status', async () => {
            await pubmed(`/backfills/${encodeURIComponent(row.backfill_id)}/resume`, { method: 'POST' });
            await backfills();
          }));
          tr.lastElementChild.append(resume);
        }
        if (row.initialized) {
          const view = document.createElement('button');
          view.type = 'button';
          view.textContent = 'View papers';
          view.addEventListener('click', () => action(view, 'lib-backfill-status', () => openLibrary(row.query_id)));
          tr.lastElementChild.append(view);
        }
        $('lib-backfills').append(tr);
      }
      message('lib-backfill-status', data.backfills.length ? `Updated ${new Date().toLocaleTimeString()}. Refreshes every 10 seconds.` : '');
    } finally {
      state.backfillsLoading = false;
    }
  }

  // ---- Schedules ----

  async function schedules() {
    const data = await pubmed('/schedules');
    $('lib-schedules').replaceChildren();
    if (!data.schedules.length) $('lib-schedules').innerHTML = emptyRow(5, 'No scheduled searches yet. Create one from a saved search below.');
    for (const row of data.schedules) {
      const tr = document.createElement('tr');
      const last = row.last_finished_at || row.last_started_at;
      tr.innerHTML = `<td><strong>${esc(row.name)}</strong><small>${esc(row.search.query)}</small><small>Published ${esc(row.search.start_date || 'any start')} to ${esc(row.search.end_date || 'any end')} · limit ${esc(row.search.max_results)}</small></td>`
        + `<td>${statusPill(row.enabled ? 'enabled' : 'disabled', row.enabled ? 'Enabled' : 'Disabled')}<small>${esc(frequency(row.interval_hours))}</small><small>${row.ingest_new ? 'Downloads new papers' : 'Search only'}</small></td>`
        + `<td>${row.enabled ? esc(formatDate(row.next_run_at, 'Not scheduled')) : 'Paused'}</td>`
        + `<td>${esc(SCHEDULE_STATUS[row.status] || row.status)}<small>${last ? esc(formatDate(last)) : ''}</small>${row.last_request_id ? '<small>Download request queued</small>' : ''}${row.last_truncated ? '<small class="bad">Result limit reached. Some matching papers were not checked.</small>' : ''}${row.error ? `<small class="bad">${esc(row.error)}</small>` : ''}</td><td></td>`;
      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.textContent = row.enabled ? 'Disable' : 'Enable';
      toggle.setAttribute('aria-label', `${toggle.textContent} ${row.name}`);
      toggle.addEventListener('click', () => action(toggle, 'lib-schedule-status', () => toggleSchedule(row.schedule_id, !row.enabled)));
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.textContent = 'Delete';
      remove.className = 'danger';
      remove.setAttribute('aria-label', `Delete ${row.name}`);
      remove.addEventListener('click', () => deleteSchedule(row));
      tr.lastElementChild.append(toggle, remove);
      $('lib-schedules').append(tr);
    }
    message('lib-schedule-status', data.schedules.length ? `${data.schedules.filter((r) => r.enabled).length} of ${plural(data.schedules.length, 'schedule')} enabled.` : '');
  }

  async function toggleSchedule(id, enabled) {
    await pubmed(`/schedules/${encodeURIComponent(id)}`, { method: 'PATCH', body: { enabled } });
    await schedules();
  }

  async function deleteSchedule(row) {
    const deleted = await ctx.confirm({
      title: 'Delete this scheduled search?',
      body: [`Delete "${row.name}" and stop its future runs?`, 'Saved searches and downloaded papers stay. Work already started may finish.'],
      confirmLabel: 'Delete schedule',
      danger: true,
      run: () => pubmed(`/schedules/${encodeURIComponent(row.schedule_id)}`, { method: 'DELETE' }),
    });
    if (!deleted) return;
    await schedules();
    message('lib-schedule-status', 'Schedule deleted.', 'ok');
    $('lib-refresh-schedules').focus();
  }

  async function createSchedule() {
    const row = await pubmed('/schedules', {
      method: 'POST',
      body: {
        query_id: $('lib-schedule-search').value, name: $('lib-schedule-name').value.trim(),
        interval_hours: Number($('lib-schedule-frequency').value),
        ingest_new: $('lib-schedule-ingest').checked, enabled: $('lib-schedule-enabled').checked,
      },
    });
    message('lib-schedule-message', row.enabled ? `Schedule created. First run: ${formatDate(row.next_run_at)}.` : 'Schedule created and disabled. Enable it when ready.', 'ok');
    await schedules();
  }

  // ---- OpenAlex enrichment ----

  async function initializeEnrichment() {
    try {
      const status = await openalex('/status');
      state.oaAvailable = Boolean(status.available);
      $('lib-oa-configuration').textContent = `${status.api_key_configured ? 'API key configured.' : 'Using anonymous API access. Configure OPENALEX_API_KEY for a higher allowance.'} Recent matches are reused for ${status.cache_days} days. HTTP allowance per request: ${status.request_budget}.`;
    } catch (_optional) {
      // The library works without the optional OpenAlex module.
      state.oaAvailable = false;
    }
    for (const id of ['lib-tab-enrichment', 'lib-enrich-query', 'lib-enrich-library']) $(id).hidden = !state.oaAvailable;
    for (const el of root.querySelectorAll('.oa-filter')) el.hidden = !state.oaAvailable;
    // Leave the Enrichment view for Papers, re-rendering it, when OpenAlex is not enabled.
    if (state.view === 'enrichment' && !state.oaAvailable) ctx.navigate(ctx.href('library'));
  }

  function openEnrichment(queryId) {
    const query = state.queries.find((q) => q.query_id === queryId);
    if (!query) throw new Error('Choose one saved search to enrich.');
    return ctx.confirm({
      title: 'Enrich this saved search?',
      body: [queryLabel(query), 'Enriches every record saved for this search now, including papers without a PDF. Papers found later need another request.'],
      confirmLabel: 'Queue enrichment',
      option: { label: 'Refresh recent matches too', checked: false },
      run: (force) => createEnrichment(queryId, force),
    });
  }

  async function createEnrichment(queryId, force) {
    const row = await openalex('/requests', { method: 'POST', body: { query_id: queryId, force_refresh: Boolean(force) } });
    await enrichmentRequests();
    message('lib-enrichment-message', `Queued enrichment of ${row.total} saved records. The orchestrator processes them in batches.`, 'ok');
    ctx.toast('Enrichment queued.');
  }

  async function enrichmentRequests() {
    const token = enrichmentGuard.next();
    const data = await openalex('/requests');
    if (!enrichmentGuard.is(token)) return;
    $('lib-enrichment-requests').replaceChildren();
    if (!data.requests.length) $('lib-enrichment-requests').innerHTML = emptyRow(4, 'No enrichment requests yet. Choose a saved search above to enrich it.');
    for (const row of data.requests) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${esc(row.query)}<small>${esc(formatDate(row.created_at))}</small></td><td>${statusPill(row.status)}<small class="bad">${esc(row.error)}</small></td><td>${esc(row.processed)} / ${esc(row.total)} checked<small>${esc(row.enriched)} enriched; ${esc(row.no_match)} unmatched; ${esc(row.ambiguous)} ambiguous; ${esc(row.cached)} cached</small></td><td></td>`;
      if (row.status === 'failed') {
        const resume = document.createElement('button');
        resume.type = 'button';
        resume.textContent = 'Resume';
        resume.addEventListener('click', () => action(resume, 'lib-enrichment-message', async () => {
          await openalex(`/requests/${encodeURIComponent(row.request_id)}/resume`, { method: 'POST' });
          await enrichmentRequests();
        }));
        tr.lastElementChild.append(resume);
      }
      $('lib-enrichment-requests').append(tr);
    }
    message('lib-enrichment-message', data.requests.length ? 'Progress refreshes every 10 seconds. Resume keeps completed papers and renews the HTTP request allowance.' : '');
  }

  async function paperDetail(pmid, title = '') {
    const token = detailGuard.next();
    $('lib-detail-title').textContent = title ? `OpenAlex details: ${title}` : `OpenAlex details for PMID ${pmid}`;
    $('lib-detail-content').textContent = 'Loading enrichment...';
    $('lib-detail').showModal();
    try {
      const data = await openalex(`/papers/${encodeURIComponent(pmid)}`);
      if (!detailGuard.is(token)) return;
      const e = data.enrichment;
      const w = data.work;
      let content = `<p>Status: ${esc(e.status)}. Checked ${esc(formatDate(e.checked_at, 'not yet'))}.</p><p class="bad">${esc(e.error)}</p>`;
      if (w) {
        content += `<h3>${esc(w.title)}</h3><p>${safeLink(`https://openalex.org/${encodeURIComponent(w.work_id)}`, 'View on OpenAlex')} · ${esc(w.citation_count)} citations · ${esc(w.oa_status || 'Access unknown')}</p><p class="muted">Matched by ${esc(e.matched_by)}. Metadata retrieved ${esc(formatDate(w.fetched_at))}; source updated ${esc(w.source_updated_at || 'unknown')}.</p>`;
        content += `<h3>Topics</h3><p>${esc((w.topics || []).map((t) => t.name).join(', ') || 'None recorded')}</p><h3>Authors and affiliations</h3><ul>${(w.authorships || []).map((a) => `<li>${esc(a.name)}: ${esc((a.institutions || []).map((i) => `${i.name}${i.country_code ? ` (${i.country_code})` : ''}`).join(', ') || 'No affiliation recorded')}</li>`).join('')}</ul>`;
        content += `<h3>Locations</h3><p class="muted">Links reported by OpenAlex. Availability and licensing depend on the source.</p><ul>${(w.locations || []).map((l) => `<li>${esc(l.source_name || 'Source')} ${l.landing_page_url ? safeLink(l.landing_page_url, 'Landing page') : ''} ${l.pdf_url ? safeLink(l.pdf_url, 'PDF') : ''} ${esc(l.license)}</li>`).join('')}</ul><h3>References (${(w.referenced_work_ids || []).length})</h3><p>${(w.referenced_work_ids || []).map((id) => safeLink(`https://openalex.org/${encodeURIComponent(id)}`, id)).join(', ') || 'None recorded'}</p>`;
      } else if (e.candidate_ids?.length) {
        content += `<p>Conflicting candidates: ${e.candidate_ids.map((id) => safeLink(`https://openalex.org/${encodeURIComponent(id)}`, id)).join(', ')}</p>`;
      }
      $('lib-detail-content').innerHTML = content;
    } catch (error) {
      if (detailGuard.is(token)) $('lib-detail-content').textContent = error.message;
    }
  }

  // ---- Wiring ----

  const report = (target) => (error) => message(target, error.message, 'bad');

  $('lib-search-form').addEventListener('submit', (event) => { event.preventDefault(); action($('lib-search'), 'lib-message', search); });
  $('lib-ingest').addEventListener('click', () => action($('lib-ingest'), 'lib-message', ingest));
  $('lib-ingest-all').addEventListener('click', () => action($('lib-ingest-all'), 'lib-message', openBackfill));
  $('lib-history').addEventListener('change', () => action($('lib-history'), 'lib-message', () => chooseQuery()));
  $('lib-refresh-history').addEventListener('click', () => action($('lib-refresh-history'), 'lib-message', history));
  $('lib-browse-query').addEventListener('click', () => action($('lib-browse-query'), 'lib-message', () => openLibrary(state.queryId)));
  $('lib-collect-query').addEventListener('click', () => action($('lib-collect-query'), 'lib-message', () => ctx.section('collections').addToCollection(
    [{ pubmed_query: { query_id: state.queryId } }], `the search "${queryText(state.queryId)}" (papers it downloads later join too)`,
  )));
  $('lib-enrich-query').addEventListener('click', () => action($('lib-enrich-query'), 'lib-message', () => openEnrichment(state.queryId)));
  $('lib-refresh-requests').addEventListener('click', () => action($('lib-refresh-requests'), 'lib-request-message', requests));
  $('lib-refresh-backfills').addEventListener('click', () => action($('lib-refresh-backfills'), 'lib-backfill-status', backfills));
  $('lib-filters').addEventListener('submit', (event) => { event.preventDefault(); action($('lib-apply'), 'lib-summary', applyLibrary); });
  $('lib-clear').addEventListener('click', () => action($('lib-clear'), 'lib-summary', clearLibrary));
  $('lib-refresh-library').addEventListener('click', () => action($('lib-refresh-library'), 'lib-summary', async () => { await history(); await library(); }));
  $('lib-enrich-library').addEventListener('click', () => action($('lib-enrich-library'), 'lib-summary', () => openEnrichment($('lib-filter-query').value)));
  for (const id of ['lib-prev', 'lib-prev-top']) $(id).addEventListener('click', () => library(state.libraryPage - 1));
  for (const id of ['lib-next', 'lib-next-top']) $(id).addEventListener('click', () => library(state.libraryPage + 1));
  $('lib-pagination').addEventListener('submit', (event) => { event.preventDefault(); library(Number($('lib-page-number').value)); });
  $('lib-schedule-form').addEventListener('submit', (event) => { event.preventDefault(); action($('lib-save-schedule'), 'lib-schedule-message', createSchedule); });
  $('lib-refresh-schedules').addEventListener('click', () => action($('lib-refresh-schedules'), 'lib-schedule-status', schedules));
  $('lib-enrich-form').addEventListener('submit', (event) => { event.preventDefault(); action($('lib-enrich-submit'), 'lib-enrich-message', () => openEnrichment($('lib-enrich-search').value)); });
  $('lib-enrich-refresh-queries').addEventListener('click', () => action($('lib-enrich-refresh-queries'), 'lib-enrich-message', history));
  $('lib-refresh-enrichment').addEventListener('click', () => action($('lib-refresh-enrichment'), 'lib-enrichment-message', enrichmentRequests));
  $('lib-close-detail').addEventListener('click', () => $('lib-detail').close());
  $('lib-detail').addEventListener('close', () => { detailGuard.next(); });

  // Pages that already polled keep polling, only while visible.
  ctx.every(10000, () => {
    if (!state.active || document.hidden) return;
    if (state.view === 'downloads') {
      requests().catch(report('lib-request-message'));
      backfills().catch(report('lib-backfill-status'));
    }
    if (state.view === 'enrichment' && state.oaAvailable) enrichmentRequests().catch(report('lib-enrichment-message'));
  });

  // Loads what the current view shows.
  function load() {
    if (state.view === 'papers') return library();
    if (state.view === 'downloads') {
      requests().catch(report('lib-request-message'));
      return backfills().catch(report('lib-backfill-status'));
    }
    if (state.view === 'schedules') return schedules().catch(report('lib-schedule-status'));
    if (state.view === 'enrichment') return enrichmentRequests().catch(report('lib-enrichment-message'));
    return undefined;
  }

  let started = false;
  async function show(route, { entering = false } = {}) {
    state.active = true;
    const view = VIEWS[route.parts[0]] ? route.parts[0] : 'papers';
    state.view = view;
    for (const name of Object.keys(VIEWS)) {
      $(`lib-view-${name}`).hidden = name !== view;
      if (name === view) $(`lib-tab-${name}`).setAttribute('aria-current', 'page');
      else $(`lib-tab-${name}`).removeAttribute('aria-current');
    }
    if (!started) {
      started = true;
      initializeEnrichment();
      await history().catch(report('lib-message'));
    } else if (entering) {
      // Searches saved elsewhere since the last visit appear in every picker.
      await history().catch(report('lib-message'));
    }
    if (view === 'papers') {
      const filters = filtersFromParams(route.params);
      setFilters(filters);
      state.libraryFilters = libraryFilters();
      state.libraryPage = Math.max(1, Number(route.params.get('page')) || 1);
      return library(state.libraryPage);
    }
    if (view === 'search') {
      const queryId = route.params.get('query') || '';
      if (queryId && queryId !== state.queryId) {
        $('lib-history').value = queryId;
        return action($('lib-history'), 'lib-message', () => chooseQuery(queryId));
      }
      if (!queryId && state.queryId) ctx.replace(ctx.href('library', ['search'], { query: state.queryId }));
      return undefined;
    }
    if (view === 'schedules') {
      const queryId = route.params.get('query') || state.queryId;
      if (queryId) $('lib-schedule-search').value = queryId;
    }
    return load();
  }

  async function refresh() {
    await history().catch(report('lib-message'));
    return load();
  }

  return {
    show,
    hide() { state.active = false; },
    refresh,
    state,
    actions: {
      search, chooseQuery, ingest, openBackfill, createBackfill, history, library, applyLibrary, clearLibrary,
      openLibrary, requests, backfills, schedules, toggleSchedule, deleteSchedule, createSchedule,
      initializeEnrichment, openEnrichment, createEnrichment, enrichmentRequests, paperDetail, renderPreview,
    },
  };
}
