// Library: everything the PubMed Library and OpenAlex enrichment apps did.
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { context, install, load, response, routeFetch, settle } = require('./harness.cjs');

async function library() {
  const dom = install();
  const { href, parse } = await load('router.js');
  const { confirmAction } = await load('ui.js');
  const ctx = context({ href, confirm: confirmAction });
  const { create } = await load('sections/library.js');
  const lib = create(dom.$('section-library'), ctx);
  return { dom, ctx, lib, parse, $: dom.$, a: lib.actions };
}

const libraryResult = (page = 1, total = 1205, papers = [{ paper: { pmid: '1', title: 'Paper' }, artifacts: [] }]) => ({
  page, page_size: 50, total, total_pages: Math.ceil(total / 50), papers,
});
const params = (url) => new URL(url, 'http://local').searchParams;

// ---- Search PubMed ----

test('search preview does not trigger ingestion and shows a bounded result count', async () => {
  const { $, a, ctx } = await library();
  const calls = [];
  $('lib-query').value = 'solitude'; $('lib-sort').value = 'relevance'; $('lib-limit').value = '1';
  globalThis.fetch = routeFetch({
    'POST /pubmed/api/search': { query: { query_id: 'q', total: 20 }, papers: [{ pmid: '1', title: '<script>bad</script>', pmcid: 'PMC1' }], truncated: true },
    '/pubmed/api/queries': { queries: [] },
  }, calls);
  await a.search();
  assert.deepEqual(calls.map((c) => `${c.method} ${c.url}`), ['POST /pubmed/api/search', 'GET /pubmed/api/queries']);
  assert.deepEqual(calls[0].body, { query: 'solitude', start_date: '', end_date: '', sort: 'relevance', max_results: 1 });
  assert.match($('lib-preview-summary').textContent, /1 of 20/);
  assert.match($('lib-preview').children[0].innerHTML, /&lt;script/);
  assert.doesNotMatch($('lib-preview').children[0].innerHTML, /<script/);
  assert.equal($('lib-ingest').disabled, false);
  assert.equal($('lib-ingest-all').disabled, false);
  assert.equal(ctx.replaced.at(-1), '#/library/search?query=q', 'a reload shows the same saved search');
});

test('failed searches clear the previous selection so it cannot be ingested accidentally', async () => {
  const { $, a } = await library();
  a.renderPreview([{ pmid: 'old', title: 'Old paper' }]);
  globalThis.fetch = async () => { throw new Error('Network error'); };
  await assert.rejects(a.search(), /Network error/);
  assert.equal($('lib-preview').children.length, 0);
  assert.equal($('lib-ingest').disabled, true);
  await assert.rejects(a.ingest(), /Choose a search with papers first/);
});

test('preview ingestion submits only the displayed papers of a larger search', async () => {
  const { a, ctx } = await library();
  const calls = [];
  globalThis.fetch = routeFetch({
    '/queries/aggregate-query/papers': { papers: [{ pmid: '123', title: 'Preview' }], total: 10050 },
    'POST /pubmed/api/requests': { request_id: 'request-1' },
    'GET /pubmed/api/requests': { requests: [] },
  }, calls);
  await a.chooseQuery('aggregate-query');
  await a.ingest();
  assert.deepEqual(calls.find((c) => c.method === 'POST').body, { query_id: 'aggregate-query', pmids: ['123'] });
  assert.equal(ctx.toasts.length, 1);
});

test('a late saved-search response cannot replace newer results', async () => {
  const { $, a } = await library();
  let resolveOld;
  globalThis.fetch = () => new Promise((resolve) => { resolveOld = resolve; });
  const old = a.chooseQuery('old');
  globalThis.fetch = async () => response({ papers: [{ pmid: '2', title: 'Current' }] });
  await a.chooseQuery('new');
  resolveOld(response({ papers: [{ pmid: '1', title: 'Stale' }] }));
  await old;
  assert.match($('lib-preview').children[0].innerHTML, /Current/);
});

test('saved searches are named by query and date in every picker', async () => {
  const { $, a } = await library();
  globalThis.fetch = async () => response({ queries: [{ query_id: '0f3a-uuid', query: 'solitude', created_at: '2026-09-17T10:00:00Z', start_date: '2020-01-01' }] });
  await a.history();
  for (const id of ['lib-history', 'lib-filter-query', 'lib-enrich-search', 'lib-schedule-search']) {
    assert.match($(id).children[1].textContent, /^solitude/);
    assert.doesNotMatch($(id).children[1].textContent, /0f3a/);
  }
});

// ---- Schedules ----

test('scheduled searches have their own view and show enabled and disabled states', async () => {
  const { $, lib, parse } = await library();
  globalThis.fetch = routeFetch({
    '/pubmed/api/queries': { queries: [] },
    '/openalex/api/status': { available: false },
    '/pubmed/api/schedules': { schedules: [{ schedule_id: 's', name: 'Daily <query>', search: { query: 'solitude', max_results: 100 }, interval_hours: 24, enabled: false, status: 'idle' }] },
  });
  await lib.show(parse('#/library/schedules'));
  await settle();
  assert.equal($('lib-view-schedules').hidden, false);
  assert.equal($('lib-view-search').hidden, true);
  assert.equal($('lib-tab-schedules').attributes['aria-current'], 'page');
  const row = $('lib-schedules').children[0];
  assert.match(row.innerHTML, /Disabled/);
  assert.match(row.innerHTML, /Daily &lt;query&gt;/);
  assert.equal(row.lastElementChild.children[0].textContent, 'Enable');
  assert.equal(row.lastElementChild.children[1].textContent, 'Delete');
});

test('schedule creation preserves explicit search-only and disabled choices', async () => {
  const { $, a } = await library();
  const calls = [];
  $('lib-schedule-search').value = 'q'; $('lib-schedule-name').value = 'Weekly'; $('lib-schedule-frequency').value = '168';
  $('lib-schedule-ingest').checked = false; $('lib-schedule-enabled').checked = false;
  globalThis.fetch = routeFetch({ 'POST /pubmed/api/schedules': { enabled: false }, 'GET /pubmed/api/schedules': { schedules: [] } }, calls);
  await a.createSchedule();
  assert.deepEqual(calls[0].body, { query_id: 'q', name: 'Weekly', interval_hours: 168, ingest_new: false, enabled: false });
  assert.match($('lib-schedule-message').textContent, /created and disabled/);
});

test('enabling a schedule persists through the API and refreshes the list', async () => {
  const { $, a } = await library();
  const calls = [];
  globalThis.fetch = routeFetch({ '/pubmed/api/schedules': { schedules: [] } }, calls);
  await a.toggleSchedule('s', true);
  assert.deepEqual(calls.map((c) => [c.url, c.method, c.body]), [['/pubmed/api/schedules/s', 'PATCH', { enabled: true }], ['/pubmed/api/schedules', 'GET', undefined]]);
  assert.match($('lib-schedules').innerHTML, /No scheduled searches yet/);
});

test('cancelling deletion leaves the schedule untouched', async () => {
  const { $, a } = await library();
  let called = false;
  globalThis.fetch = async () => { called = true; return response({}); };
  const pending = a.deleteSchedule({ schedule_id: 's', name: 'Daily' });
  assert.equal($('confirm-dialog').open, true);
  assert.match($('confirm-body').children[0].textContent, /Daily/);
  $('confirm-cancel').onclick();
  await pending;
  assert.equal(called, false);
  assert.equal($('confirm-dialog').open, false);
});

test('confirmed deletion accepts an empty response and refreshes schedules', async () => {
  const { $, a } = await library();
  const calls = [];
  globalThis.fetch = routeFetch({ 'DELETE /pubmed/api/schedules/s': { ok: true, status: 204 }, 'GET /pubmed/api/schedules': { schedules: [] } }, calls);
  const pending = a.deleteSchedule({ schedule_id: 's', name: 'Daily' });
  await $('confirm-ok').onclick();
  await pending;
  assert.deepEqual(calls.map((c) => [c.url, c.method]), [['/pubmed/api/schedules/s', 'DELETE'], ['/pubmed/api/schedules', 'GET']]);
  assert.equal($('confirm-dialog').open, false);
  assert.match($('lib-schedule-status').textContent, /Schedule deleted/);
});

test('failed deletion keeps the confirmation open for retry', async () => {
  const { $, a } = await library();
  globalThis.fetch = async () => response({ detail: 'Storage unavailable' }, { ok: false });
  a.deleteSchedule({ schedule_id: 's', name: 'Daily' });
  await $('confirm-ok').onclick();
  assert.equal($('confirm-dialog').open, true);
  assert.match($('confirm-error').textContent, /Storage unavailable/);
});

test('PubMed mutations send the session bearer token', async () => {
  const { $, a } = await library();
  globalThis.localStorage = { getItem: () => JSON.stringify({ state: { token: 'test-token' } }) };
  const calls = [];
  globalThis.fetch = routeFetch({ '/pubmed/api/schedules': { schedules: [] } }, calls);
  $('lib-schedule-search').value = 'q';
  await a.createSchedule();
  assert.equal(calls[0].headers.Authorization, 'Bearer test-token');
});

// ---- Downloads ----

test('full ingestion confirms the saved search and dates rather than edited inputs', async () => {
  const { $, a, lib, ctx } = await library();
  const calls = [];
  lib.state.queryId = 'saved';
  lib.state.queries = [{ query_id: 'saved', query: 'solitude', start_date: '1900-01-01', end_date: '', total: 12500, max_results: 100 }];
  $('lib-query').value = 'unsaved change';
  const pending = a.openBackfill();
  assert.equal($('confirm-dialog').open, true);
  const text = $('confirm-body').children.map((p) => p.textContent).join(' ');
  assert.match(text, /solitude.*1900-01-01.*12500/);
  assert.doesNotMatch(text, /unsaved change/);
  globalThis.fetch = routeFetch({ 'POST /pubmed/api/backfills': { backfill_id: 'new-backfill' }, 'GET /pubmed/api/backfills': { backfills: [] } }, calls);
  await $('confirm-ok').onclick();
  assert.equal(await pending, true);
  assert.deepEqual(calls[0].body, { query_id: 'saved' });
  assert.equal(ctx.navigated.at(-1), '#/library/downloads');
  assert.equal($('confirm-dialog').open, false);
});

test('cancelling full ingestion never submits a job', async () => {
  const { $, a, lib } = await library();
  let calls = 0;
  globalThis.fetch = () => { calls += 1; };
  lib.state.queryId = 'saved';
  lib.state.queries = [{ query_id: 'saved', query: 'solitude' }];
  const pending = a.openBackfill();
  $('confirm-cancel').onclick();
  assert.equal(await pending, false);
  assert.equal(calls, 0);
});

test('full ingestions report separate outcomes, escape query text and offer resume', async () => {
  const { $, lib, parse } = await library();
  globalThis.fetch = routeFetch({
    '/pubmed/api/queries': { queries: [] },
    '/openalex/api/status': { available: false },
    '/pubmed/api/requests': { requests: [] },
    '/pubmed/api/backfills': { backfills: [{ backfill_id: 'one', query_id: 'q', search: { query: '<img onerror=x>' }, status: 'failed', total: 12500, discovered: 200, completed: 20, published: 15, unavailable: 3, failed: 2, remaining: 180, error: 'Interrupted', initialized: true }] },
  });
  await lib.show(parse('#/library/downloads'));
  await settle();
  assert.equal($('lib-view-downloads').hidden, false);
  assert.equal($('lib-view-papers').hidden, true);
  const row = $('lib-backfills').children[0];
  assert.match(row.innerHTML, /12500 initial matches/);
  assert.match(row.innerHTML, /15 published/);
  assert.match(row.innerHTML, /&lt;img/);
  assert.match(row.innerHTML, /Interrupted/);
  assert.deepEqual(row.lastElementChild.children.map((b) => b.textContent), ['Resume', 'View papers']);
});

test('full ingestion refresh does not overlap slow requests', async () => {
  const { a } = await library();
  let calls = 0;
  let finish;
  globalThis.fetch = () => { calls += 1; return new Promise((resolve) => { finish = resolve; }); };
  const first = a.backfills();
  await a.backfills();
  assert.equal(calls, 1);
  finish(response({ backfills: [] }));
  await first;
});

test('ingestion requests name their search, show progress and offer retry only when something failed', async () => {
  const { $, a, lib } = await library();
  lib.state.queries = [{ query_id: 'q', query: 'solitude' }];
  globalThis.fetch = async () => response({ requests: [
    { request_id: 'r1', query_id: 'q', status: 'partial', pmids: ['1', '2'], outcomes: { 1: { status: 'ready' }, 2: { status: 'failed' } }, requested_at: '2026-09-17T10:00:00Z' },
    { request_id: 'r2', query_id: 'q', status: 'succeeded', pmids: ['3'], outcomes: { 3: { status: 'ready' } }, requested_at: '2026-09-17T10:00:00Z' },
  ] });
  await a.requests();
  const [partial, done] = $('lib-requests').children;
  assert.match(partial.innerHTML, /solitude/);
  assert.match(partial.innerHTML, /1 published \/ 2 requested/);
  assert.equal(partial.lastElementChild.children[0].textContent, 'Retry remaining');
  assert.equal(done.lastElementChild.children.length, 0);
});

test('the downloads view keeps polling every 10 seconds only while it is open and visible', async () => {
  const { dom, lib, ctx, parse } = await library();
  const calls = [];
  globalThis.fetch = routeFetch({
    '/pubmed/api/queries': { queries: [] }, '/openalex/api/status': { available: false },
    '/pubmed/api/requests': { requests: [] }, '/pubmed/api/backfills': { backfills: [] },
  }, calls);
  assert.equal(ctx.intervals[0].ms, 10000);
  await lib.show(parse('#/library/downloads'));
  await settle();
  const before = calls.length;
  ctx.intervals[0].work();
  await settle();
  assert.equal(calls.length, before + 2);
  dom.document.hidden = true;
  ctx.intervals[0].work();
  lib.hide();
  dom.document.hidden = false;
  ctx.intervals[0].work();
  await settle();
  assert.equal(calls.length, before + 2);
});

// ---- Paper library ----

test('the library defaults to downloaded papers and pages beyond 1000', async () => {
  const { $, lib, a, parse } = await library();
  const calls = [];
  globalThis.fetch = routeFetch({
    '/pubmed/api/queries': { queries: [] }, '/openalex/api/status': { available: false },
    '/pubmed/api/papers': (url) => libraryResult(Number(params(url).get('page'))),
  }, calls);
  await lib.show(parse('#/library'));
  const first = calls.find((c) => c.url.includes('/papers'));
  assert.equal(params(first.url).get('status'), 'published');
  assert.equal($('lib-view-papers').hidden, false);
  assert.equal($('lib-prev').disabled, true);
  assert.equal($('lib-next').disabled, false);
  await a.library(25);
  assert.match($('lib-summary').textContent, /1201-1201 of 1205/);
  assert.equal($('lib-page-label').textContent, 'Page 25 of 25');
  assert.equal($('lib-page-label-top').textContent, 'Page 25 of 25');
  assert.equal($('lib-prev').disabled, false);
  assert.equal($('lib-next').disabled, true);
});

test('library filters reset paging, and page changes keep the applied filters', async () => {
  const { $, a } = await library();
  const seen = [];
  globalThis.fetch = async (url) => { seen.push(params(url)); return response(libraryResult()); };
  $('lib-filter-search').value = 'O\'Brien & solitude'; $('lib-filter-query').value = 'query-id';
  $('lib-filter-from').value = '2026-01-01'; $('lib-filter-until').value = '2026-09-17';
  $('lib-filter-sort').value = 'title'; $('lib-filter-size').value = '100';
  await a.applyLibrary();
  assert.equal(seen[0].get('page'), '1');
  assert.equal(seen[0].get('search'), "O'Brien & solitude");
  assert.equal(seen[0].get('query_id'), 'query-id');
  assert.equal(seen[0].get('page_size'), '100');
  assert.equal(seen[0].get('ingested_until'), '2026-09-17');
  $('lib-filter-search').value = 'unapplied draft';
  await a.library(2);
  assert.equal(seen[1].get('search'), "O'Brien & solitude");
  await a.clearLibrary();
  assert.equal(seen[2].get('page'), '1');
  assert.equal(seen[2].get('search'), '');
  assert.equal(seen[2].get('query_id'), '');
  assert.equal(seen[2].get('status'), 'published');
});

test('applied filters and the page go in the URL, and a link restores them', async () => {
  const { $, a, lib, ctx, parse } = await library();
  const seen = [];
  globalThis.fetch = routeFetch({
    '/pubmed/api/queries': { queries: [] }, '/openalex/api/status': { available: false },
    '/pubmed/api/papers': (url) => { seen.push(params(url)); return libraryResult(Number(params(url).get('page'))); },
  });
  await lib.show(parse('#/library?query_id=q1&search=stress&page=3'));
  assert.equal(seen[0].get('query_id'), 'q1');
  assert.equal(seen[0].get('search'), 'stress');
  assert.equal(seen[0].get('page'), '3');
  assert.equal($('lib-filter-search').value, 'stress');
  await a.library(4);
  assert.equal(ctx.replaced.at(-1), '#/library?search=stress&query_id=q1&page=4');
});

test('late library results cannot overwrite newer filters or errors', async () => {
  const { $, a } = await library();
  let finish;
  globalThis.fetch = () => new Promise((resolve) => { finish = resolve; });
  const slow = a.library();
  globalThis.fetch = async () => response(libraryResult(1, 1, [{ paper: { pmid: '2', title: 'Current selection' }, artifacts: [] }]));
  await a.applyLibrary();
  finish(response(libraryResult()));
  await slow;
  assert.match($('lib-papers').children[0].innerHTML, /Current selection/);
  globalThis.fetch = async () => { throw new Error('Dataset unavailable'); };
  await a.library();
  assert.equal($('lib-papers').children.length, 0);
  assert.match($('lib-summary').textContent, /Dataset unavailable/);
  assert.equal($('lib-next').disabled, true);
});

test('the library handles empty results and clamps a page after the result set shrinks', async () => {
  const { $, a } = await library();
  const pages = [];
  globalThis.fetch = async (url) => {
    const page = Number(params(url).get('page'));
    pages.push(page);
    return response(libraryResult(page, 1, page === 1 ? [{ paper: { pmid: '1' }, artifacts: [] }] : []));
  };
  await a.library(25);
  assert.deepEqual(pages, [25, 1]);
  globalThis.fetch = async () => response(libraryResult(1, 0, []));
  await a.library();
  assert.match($('lib-summary').textContent, /No papers match/);
  assert.equal($('lib-prev').disabled, true);
  assert.equal($('lib-next').disabled, true);
});

test('the library escapes metadata and storage locations without starting jobs', async () => {
  const { $, a } = await library();
  let method;
  globalThis.fetch = async (_url, options) => {
    method = options.method;
    return response(libraryResult(1, 1, [{ paper: { pmid: '1', title: '<img onerror=x>', authors: ['<script>'], doi: '<svg>' }, artifacts: [{ storage_prefix: '<b>', storage_key: '<img>', content_sha256: '<script>' }] }]));
  };
  await a.library();
  const markup = $('lib-papers').children[0].innerHTML;
  assert.match(markup, /&lt;img/);
  assert.match(markup, /&lt;script/);
  assert.doesNotMatch(markup, /<img|<script|<svg/);
  assert.equal(method, 'GET');
});

test('opening a search in the library clears stale filters and keeps the exact search', async () => {
  const { $, a, ctx } = await library();
  globalThis.fetch = async () => response({ queries: [{ query_id: 'full-query', query: 'solitude', created_at: '2026-09-17' }] });
  $('lib-filter-search').value = 'old filter'; $('lib-filter-from').value = '2026-09-01';
  await a.openLibrary('full-query');
  assert.equal(ctx.navigated.at(-1), '#/library?query_id=full-query');
  assert.equal($('lib-filter-query').value, 'full-query');
  assert.equal($('lib-filter-search').value, '');
  assert.equal($('lib-filter-from').value, '');
  assert.equal($('lib-filter-status').value, 'published');
});

// ---- OpenAlex ----

test('OpenAlex controls appear only when the module is available, with its configuration', async () => {
  const { $, a } = await library();
  globalThis.fetch = async () => response({ available: true, api_key_configured: false, cache_days: 7, request_budget: 10000 });
  await a.initializeEnrichment();
  for (const id of ['lib-tab-enrichment', 'lib-enrich-query', 'lib-enrich-library']) assert.equal($(id).hidden, false, id);
  assert.match($('lib-oa-configuration').textContent, /anonymous API access.*7 days.*10000/);
  globalThis.fetch = async () => { throw new Error('not enabled'); };
  await a.initializeEnrichment();
  assert.equal($('lib-tab-enrichment').hidden, true);
});

test('OpenAlex enrichment uses the entire saved search and an explicit refresh choice', async () => {
  const { $, a } = await library();
  const calls = [];
  globalThis.fetch = routeFetch({
    '/pubmed/api/queries': { queries: [{ query_id: 'saved', query: 'Solitude', created_at: '2026-01-01' }] },
    'POST /openalex/api/requests': { total: 5000 },
    'GET /openalex/api/requests': { requests: [] },
  }, calls);
  await a.history();
  const pending = a.openEnrichment('saved');
  assert.equal($('confirm-option').hidden, false);
  assert.equal($('confirm-option-input').checked, false);
  $('confirm-option-input').checked = true;
  await $('confirm-ok').onclick();
  assert.equal(await pending, true);
  assert.deepEqual(calls.find((c) => c.method === 'POST').body, { query_id: 'saved', force_refresh: true });
  assert.match($('lib-enrichment-message').textContent, /5000/);
});

test('enriching without a chosen search explains what to do', async () => {
  const { a } = await library();
  assert.throws(() => a.openEnrichment(''), /Choose one saved search/);
});

test('OpenAlex filter parameters reach server-side pagination', async () => {
  const { $, a } = await library();
  let url;
  $('lib-filter-topic').value = 'Mental health'; $('lib-filter-institution').value = 'Paris';
  $('lib-filter-citations').value = '50'; $('lib-filter-enrichment').value = 'enriched';
  globalThis.fetch = async (u) => { url = u; return response({ papers: [], total: 0, total_pages: 0, page: 1, page_size: 50 }); };
  await a.applyLibrary();
  assert.equal(params(url).get('topic'), 'Mental health');
  assert.equal(params(url).get('institution'), 'Paris');
  assert.equal(params(url).get('min_citations'), '50');
  assert.equal(params(url).get('enrichment_status'), 'enriched');
});

test('OpenAlex details escape metadata and reject executable source links', async () => {
  const { $, a } = await library();
  globalThis.fetch = async () => response({ enrichment: { status: 'enriched' }, work: { work_id: 'W1', title: '<script>bad</script>', citation_count: 3, locations: [{ landing_page_url: 'javascript:alert(1)', pdf_url: 'https://example.org/paper.pdf', source_name: 'Library' }] } });
  await a.paperDetail('1', 'A paper');
  const detail = $('lib-detail-content').innerHTML;
  assert.match(detail, /&lt;script/);
  assert.doesNotMatch(detail, /javascript:/);
  assert.match(detail, /https:\/\/example.org\/paper.pdf/);
  assert.equal($('lib-detail').open, true);
  assert.match($('lib-detail-title').textContent, /A paper/);
});

test('late OpenAlex paper details cannot replace the selected paper', async () => {
  const { $, a } = await library();
  let resolve;
  globalThis.fetch = () => new Promise((r) => { resolve = r; });
  const older = a.paperDetail('1');
  globalThis.fetch = async () => response({ enrichment: { status: 'no_match', error: 'New paper has no match' } });
  await a.paperDetail('2');
  resolve(response({ enrichment: { status: 'no_match', error: 'Old result' } }));
  await older;
  assert.match($('lib-detail-content').innerHTML, /New paper/);
});

test('enrichment requests escape errors and offer resume only for interrupted requests', async () => {
  const { $, a } = await library();
  globalThis.fetch = async () => response({ requests: [
    { request_id: 'r', query: '<img src=x>', status: 'failed', error: '<script>x</script>', processed: 1, total: 10 },
    { request_id: 's', query: 'ok', status: 'succeeded', processed: 10, total: 10 },
  ] });
  await a.enrichmentRequests();
  const [failed, done] = $('lib-enrichment-requests').children;
  assert.match(failed.innerHTML, /&lt;img/);
  assert.match(failed.innerHTML, /&lt;script/);
  assert.equal(failed.lastElementChild.children[0].textContent, 'Resume');
  assert.equal(done.lastElementChild.children.length, 0);
});

test('an older enrichment status response cannot replace newer progress', async () => {
  const { $, a } = await library();
  let resolve;
  globalThis.fetch = () => new Promise((r) => { resolve = r; });
  const old = a.enrichmentRequests();
  globalThis.fetch = async () => response({ requests: [{ request_id: 'a', query: 'new', status: 'succeeded' }] });
  await a.enrichmentRequests();
  resolve(response({ requests: [] }));
  await old;
  assert.match($('lib-enrichment-requests').children[0].innerHTML, /new/);
});

// ---- Review round 1 ----

test('the Enrichment view navigates to Papers when OpenAlex is unavailable', async () => {
  const { lib, ctx, parse } = await library();
  globalThis.fetch = routeFetch({ '/pubmed/api/queries': { queries: [] }, '/openalex/api/status': () => response({ detail: 'Not found' }, { ok: false, status: 404 }), '/openalex/api/requests': { requests: [] } });
  await lib.show(parse('#/library/enrichment'));
  await settle();
  assert.equal(ctx.navigated.at(-1), '#/library');
});

test('a saved search that no longer exists falls back to the placeholder in every picker', async () => {
  const { $, a } = await library();
  $('lib-filter-query').value = 'gone';
  globalThis.fetch = async () => response({ queries: [{ query_id: 'q1', query: 'solitude', created_at: '2026-09-17' }] });
  await a.history();
  assert.equal($('lib-filter-query').value, '');
  assert.equal($('lib-filter-query').children[0].textContent, 'All searches');
});

test('coming back to the Library re-reads saved searches', async () => {
  const { lib, parse } = await library();
  const calls = [];
  globalThis.fetch = routeFetch({ '/pubmed/api/queries': { queries: [] }, '/openalex/api/status': { available: false }, '/pubmed/api/schedules': { schedules: [] } }, calls);
  await lib.show(parse('#/library/schedules'));
  await lib.show(parse('#/library/schedules'), { entering: true });
  assert.equal(calls.filter((c) => c.url === '/pubmed/api/queries').length, 2);
});

// ---- Collections ----

test('downloaded papers in the library and in search results can be added to a collection; others cannot', async () => {
  const { $, a, ctx } = await library();
  const added = [];
  ctx.sections.collections = { addToCollection: async (commands, what) => { added.push([commands, what]); return { collection_id: 'c1' }; } };
  globalThis.fetch = async () => response(libraryResult(1, 2, [
    { paper: { pmid: '1', title: 'Downloaded' }, artifacts: [{ storage_prefix: 'pubmed/papers', storage_key: '1.pdf', content_sha256: 'a'.repeat(64) }] },
    { paper: { pmid: '2', title: 'Not downloaded' }, artifacts: [] },
  ]));
  await a.library();
  const [downloaded, missing] = $('lib-papers').children;
  assert.equal(missing.lastElementChild.children.length, 0);
  const button = downloaded.lastElementChild.children[0];
  assert.equal(button.textContent, 'Add to collection');
  await Promise.all(button.listeners.click.map((h) => h({})));
  assert.deepEqual(added[0], [[{ paper: { pmid: '1' } }], '"Downloaded"']);

  a.renderPreview([{ pmid: '3', title: 'Previewed', artifacts: [{}] }, { pmid: '4', title: 'Only a record', pmcid: 'PMC4' }]);
  const [previewed, record] = $('lib-preview').children;
  assert.equal(record.lastElementChild.children.length, 0);
  await Promise.all(previewed.lastElementChild.children[0].listeners.click.map((h) => h({})));
  assert.deepEqual(added[1][0], [{ paper: { pmid: '3' } }]);
});

test('a saved search can join a collection as a whole, so its later downloads join too', async () => {
  const { $, a, ctx } = await library();
  const added = [];
  ctx.sections.collections = { addToCollection: async (commands, what) => { added.push([commands, what]); return null; } };
  globalThis.fetch = routeFetch({
    '/pubmed/api/queries/q1/papers': { papers: [], total: 0 },
    '/pubmed/api/queries': { queries: [{ query_id: 'q1', query: 'solitude', created_at: '2026-09-17T10:00:00Z' }] },
  });
  await a.history();
  a.renderPreview([]);
  assert.equal($('lib-collect-query').disabled, true, 'no saved search is chosen yet');
  await a.chooseQuery('q1');
  assert.equal($('lib-collect-query').disabled, false);
  await Promise.all($('lib-collect-query').listeners.click.map((h) => h({})));
  assert.deepEqual(added[0][0], [{ pubmed_query: { query_id: 'q1' } }]);
  assert.match(added[0][1], /the search "solitude" \(papers it downloads later join too\)/);
});

test('a failure to open the collection picker is shown next to the paper list', async () => {
  const { $, a, ctx } = await library();
  ctx.sections.collections = { addToCollection: async () => { throw new Error('Could not load collections.'); } };
  globalThis.fetch = async () => response(libraryResult(1, 1, [{ paper: { pmid: '1', title: 'Downloaded' }, artifacts: [{}] }]));
  await a.library();
  await Promise.all($('lib-papers').children[0].lastElementChild.children[0].listeners.click.map((h) => h({})));
  assert.equal($('lib-summary').textContent, 'Could not load collections.');
});

test('a downloaded paper that has been ingested links to its results', async () => {
  const { $, a } = await library();
  const calls = [];
  globalThis.fetch = routeFetch({
    '/pubmed/api/papers': libraryResult(1, 2, [
      { paper: { pmid: '1', title: 'Ingested' }, artifacts: [{ storage_prefix: 'pubmed/papers', storage_key: 'k1.pdf', content_sha256: 'a'.repeat(64) }] },
      { paper: { pmid: '2', title: 'Downloaded only' }, artifacts: [{ storage_prefix: 'pubmed/papers', storage_key: 'k2.pdf', content_sha256: 'b'.repeat(64) }] },
    ]),
    '/phases_v2/api/papers': { papers: [{ paper_id: 'a'.repeat(64) }], total: 1, limit: 200, offset: 0 },
  }, calls);
  await a.library();
  await settle();
  const asked = params(calls.find((c) => c.url.includes('/phases_v2/api/papers')).url);
  assert.deepEqual(asked.getAll('paper_id'), ['a'.repeat(64), 'b'.repeat(64)]);
  const links = (row) => row.lastElementChild.children.filter((child) => child.tagName === 'A');
  const [ingested, downloaded] = $('lib-papers').children;
  assert.deepEqual(links(ingested).map((l) => [l.textContent, l.href]), [['Open results', `#/results/${'a'.repeat(64)}`]]);
  assert.deepEqual(links(downloaded), []);
});

test('the library still lists papers when ingestion cannot be checked', async () => {
  const { $, a } = await library();
  globalThis.fetch = routeFetch({
    '/pubmed/api/papers': libraryResult(1, 1, [{ paper: { pmid: '1', title: 'Paper' }, artifacts: [{ content_sha256: 'a'.repeat(64) }] }]),
    '/phases_v2/api/papers': () => response({ detail: 'down' }, { ok: false, status: 503 }),
  });
  await a.library();
  await settle();
  assert.equal($('lib-papers').children.length, 1);
  assert.match($('lib-summary').textContent, /Showing 1-1 of 1 papers/);
});
