const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const html = readFileSync(join(__dirname, 'index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function app() {
  function element() {
    return {
      value: '', textContent: '', innerHTML: '', hidden: false, disabled: false,
      children: [], selectedOptions: [], options: [], attributes: {},
      replaceChildren() { this.children = []; this.options = []; this.innerHTML = ''; },
      append(child) { this.children.push(child); this.options.push(child); },
      get lastElementChild() { if (!this.lastChild) this.lastChild = element(); return this.lastChild; },
      addEventListener() {}, focus() {}, showModal() { this.open = true; }, close() { this.open = false; },
      setAttribute(key, value) { this.attributes[key] = value; },
      removeAttribute(key) { delete this.attributes[key]; },
      querySelector() { return element(); },
    };
  }
  const elements = new Map();
  const document = {
    hidden: false,
    getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
    querySelectorAll() { return []; }, createElement: element,
  };
  const context = vm.createContext({ document, location: { hash: '' }, URLSearchParams,
    window: { addEventListener() {} }, setInterval() {},
    // Catalog initialization stays pending; each test controls its API responses.
    fetch: () => new Promise(() => {}),
  });
  vm.runInContext(script, context);
  return { context, document, $: document.getElementById };
}

const response = (payload, ok = true) => ({ ok, status: ok ? 200 : 422, text: async () => JSON.stringify(payload) });
const preview = (name) => ({ documents: [{ name, location: 'phases_v2', key: name, supported: true }], total: 1, ingestable: 1, already_ingested: 0, unsupported: 0 });


test('search preview does not trigger ingestion and shows a bounded result count', async () => {
  const { context, $ } = app(); const calls = [];
  $('query').value = 'solitude'; $('sort').value = 'relevance'; $('limit').value = '1';
  context.fetch = async (url, options) => { calls.push(url); return response(url.endsWith('/queries') ? {queries:[]} : {query:{query_id:'q',total:20},papers:[{pmid:'1',title:'<script>bad</script>',pmcid:'PMC1'}],truncated:true}); };
  await context.search();
  assert.deepEqual(calls, ['/pubmed/api/search', '/pubmed/api/queries']);
  assert.match($('summary').textContent, /1 of 20/);
  assert.match($('papers').children[0].innerHTML, /&lt;script/);
  assert.equal($('ingest').disabled, false);
});

test('failed searches clear the previous selection so it cannot be ingested accidentally', async () => {
  const { context, $ } = app();
  context.renderPapers([{pmid:'old',title:'Old paper'}]);
  context.fetch = async () => { throw new Error('Network error'); };
  await assert.rejects(context.search(), /Network error/);
  assert.equal($('papers').children.length, 0);
  assert.equal($('ingest').disabled, true);
  await assert.rejects(context.ingest(), /Choose a nonempty query/);
});

test('preview ingestion submits only the displayed papers of a larger backfill', async () => {
  const { context, $ } = app(); let sent;
  $('history').value = 'aggregate-query';
  context.fetch = async (url, options) => {
    if (options.method === 'POST') { sent = JSON.parse(options.body); return response({request_id:'request'}); }
    return response(url.endsWith('/requests') ? {requests:[]} : {papers:[{pmid:'123',title:'Preview'}],total:10050});
  };
  await context.chooseQuery();
  await context.ingest();
  assert.deepEqual(sent, {query_id:'aggregate-query',pmids:['123']});
});

test('search history cannot replace newer results with a late response', async () => {
  const { context, $ } = app(); let resolveOld;
  $('history').value = 'old'; context.fetch = () => new Promise((resolve) => { resolveOld = resolve; });
  const old = context.chooseQuery();
  $('history').value = 'new'; context.fetch = async () => response({papers:[{pmid:'2',title:'Current'}]});
  await context.chooseQuery(); resolveOld(response({papers:[{pmid:'1',title:'Stale'}]})); await old;
  assert.match($('papers').children[0].innerHTML, /Current/);
});

test('scheduled queries have a separate page and show enabled and disabled states', async () => {
  const { context, $ } = app();
  context.location.hash = '#schedules';
  context.fetch = async () => response({schedules:[{schedule_id:'s',name:'Daily <query>',search:{query:'solitude',max_results:100},interval_hours:24,enabled:false,status:'idle'}]});
  context.showPage(); await context.schedules();
  assert.equal($('search-page').hidden, true);
  assert.equal($('schedules-page').hidden, false);
  assert.match($('schedules').children[0].innerHTML, /Disabled/);
  assert.match($('schedules').children[0].innerHTML, /Daily &lt;query&gt;/);
  assert.equal($('schedules').children[0].lastElementChild.children[0].textContent, 'Enable');
});

test('schedule creation preserves explicit search-only and disabled choices', async () => {
  const { context, $ } = app(); let sent;
  $('schedule-query').value='q'; $('schedule-name').value='Weekly'; $('schedule-frequency').value='168';
  $('schedule-ingest').checked=false; $('schedule-enabled').checked=false;
  context.fetch=async (url,options)=>{ if(options.method==='POST'){sent=JSON.parse(options.body);return response({enabled:false});}return response({schedules:[]});};
  await context.createSchedule();
  assert.deepEqual(sent,{query_id:'q',name:'Weekly',interval_hours:168,ingest_new:false,enabled:false});
  assert.match($('schedule-message').textContent,/created and disabled/);
});

test('enabling a schedule persists through the API and refreshes the list', async () => {
  const { context, $ } = app(); const calls=[];
  context.fetch=async (url,options)=>{calls.push([url,options.method,options.body]);return response({schedules:[]});};
  await context.toggleSchedule('s',true);
  assert.deepEqual(calls,[['/pubmed/api/schedules/s','PATCH','{"enabled":true}'],['/pubmed/api/schedules','GET',undefined]]);
  assert.match($('schedule-status').textContent,/No scheduled queries/);
});


test('canceling deletion leaves the schedule untouched', async () => {
  const { context, $ } = app(); let called = false;
  context.fetch = async () => { called = true; return response({}); };
  context.openDelete({schedule_id:'s',name:'Daily'});
  assert.equal($('delete-schedule-dialog').open,true);
  context.cancelDelete(); await context.deleteSchedule();
  assert.equal(called,false);
  assert.equal($('delete-schedule-dialog').open,false);
});

test('confirmed deletion accepts an empty response and refreshes schedules', async () => {
  const { context, $ } = app(); const calls = [];
  context.fetch = async (url, options) => { calls.push([url,options.method]); return options.method === 'DELETE' ? {ok:true,status:204} : response({schedules:[]}); };
  context.openDelete({schedule_id:'s',name:'Daily'}); await context.deleteSchedule();
  assert.deepEqual(calls,[['/pubmed/api/schedules/s','DELETE'],['/pubmed/api/schedules','GET']]);
  assert.equal($('delete-schedule-dialog').open,false);
  assert.match($('schedule-status').textContent,/Schedule deleted/);
});

test('failed deletion keeps the confirmation open for retry', async () => {
  const { context, $ } = app(); context.fetch = async () => response({detail:'Storage unavailable'},false);
  context.openDelete({schedule_id:'s',name:'Daily'});
  await assert.rejects(context.deleteSchedule(),/Storage unavailable/);
  assert.equal($('delete-schedule-dialog').open,true);
});

test('PubMed mutations send Nexus bearer authentication', async () => {
  const { context } = app(); let headers;
  context.localStorage = { getItem: () => JSON.stringify({ state: { token: 'test-token' } }) };
  context.fetch = async (_url, options) => { headers = options.headers; return response({}); };
  await context.api('/schedules', 'POST', {});
  assert.equal(headers.Authorization, 'Bearer test-token');
});

test('full ingestion confirms the saved query and dates rather than edited inputs', async () => {
  const { context, $ } = app(); let sent;
  vm.runInContext("state.queryId = 'saved'; state.queries = [{query_id:'saved',query:'solitude',start_date:'1900-01-01',end_date:'',total:12500,max_results:100}];", context);
  $('query').value = 'unsaved change';
  context.openBackfill();
  assert.equal($('backfill-dialog').open, true);
  assert.match($('backfill-description').textContent, /solitude.*1900-01-01.*12500/);
  assert.doesNotMatch($('backfill-description').textContent, /unsaved change/);
  context.fetch = async (url, options) => {
    if (options.method === 'POST') { sent = JSON.parse(options.body); return response({backfill_id:'new'}); }
    return response({backfills:[]});
  };
  await context.createBackfill();
  assert.deepEqual(sent, {query_id:'saved'});
  assert.equal(context.location.hash, 'backfills');
  assert.equal($('backfill-dialog').open, false);
});

test('canceling full ingestion never submits a job', () => {
  const { context } = app(); let calls = 0;
  context.fetch = () => { calls++; };
  context.cancelBackfill();
  assert.equal(calls, 0);
});

test('full ingestion page reports separate outcomes and escapes query text', async () => {
  const { context, $ } = app();
  context.fetch = async () => response({backfills:[{backfill_id:'one', search:{query:'<img onerror=x>'},status:'failed',total:12500,discovered:200,completed:20,published:15,unavailable:3,failed:2,remaining:180,error:'Interrupted'}]});
  context.location.hash = '#backfills'; context.showPage(); await new Promise(resolve => setImmediate(resolve));
  assert.equal($('backfills-page').hidden, false);
  assert.equal($('search-page').hidden, true);
  const row = $('backfills').children[0];
  assert.match(row.innerHTML, /12500 initial matches/);
  assert.match(row.innerHTML, /15 published/);
  assert.match(row.innerHTML, /&lt;img/);
  assert.equal(row.lastElementChild.children[0].textContent, 'Resume');
});

test('full ingestion refresh does not overlap slow requests', async () => {
  const { context } = app(); let calls = 0, finish;
  context.fetch = () => { calls++; return new Promise(resolve => { finish = resolve; }); };
  const first = context.backfills(); await context.backfills();
  assert.equal(calls, 1); finish(response({backfills:[]})); await first;
});

const libraryResult = (page = 1, total = 1205, papers = [{paper:{pmid:'1',title:'Paper'},artifacts:[]}]) => ({page,page_size:50,total,total_pages:Math.ceil(total / 50),papers});

test('library navigation defaults to downloaded papers and supports pages beyond 1000', async () => {
  const { context, $ } = app(); const calls = [];
  context.fetch = async url => { calls.push(url); return response(libraryResult(Number(new URL('http://local' + url).searchParams.get('page')))); };
  context.location.hash = '#library'; context.showPage();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal($('library-page').hidden, false); assert.equal($('search-page').hidden, true);
  assert.equal(new URL('http://local' + calls[0]).searchParams.get('status'), 'published');
  assert.equal($('library-prev').disabled, true); assert.equal($('library-next').disabled, false);
  await context.library(25);
  assert.match($('library-summary').textContent, /1201-1201 of 1205/);
  assert.equal($('library-page-label').textContent, 'Page 25 of 25');
  assert.equal($('library-prev').disabled, false); assert.equal($('library-next').disabled, true);
});

test('library filters reset pagination and page navigation preserves applied filters', async () => {
  const { context, $ } = app(); const calls = [];
  context.fetch = async url => { calls.push(new URL('http://local' + url).searchParams); return response(libraryResult()); };
  $('library-search').value = 'O\'Brien & solitude'; $('library-query').value = 'query-id';
  $('library-from').value = '2026-01-01'; $('library-until').value = '2026-09-17';
  $('library-sort').value = 'title'; $('library-size').value = '100';
  await context.applyLibrary();
  assert.equal(calls[0].get('page'), '1'); assert.equal(calls[0].get('search'), "O'Brien & solitude");
  assert.equal(calls[0].get('query_id'), 'query-id'); assert.equal(calls[0].get('page_size'), '100');
  assert.equal(calls[0].get('ingested_until'), '2026-09-17');
  $('library-search').value = 'unapplied draft'; await context.library(2);
  assert.equal(calls[1].get('search'), "O'Brien & solitude");
  await context.clearLibrary();
  assert.equal(calls[2].get('page'), '1'); assert.equal(calls[2].get('search'), '');
  assert.equal(calls[2].get('query_id'), ''); assert.equal(calls[2].get('status'), 'published');
});

test('late library results cannot overwrite newer filters or errors', async () => {
  const { context, $ } = app(); let finish;
  context.fetch = () => new Promise(resolve => { finish = resolve; });
  const slow = context.library();
  context.fetch = async () => response(libraryResult(1, 1, [{paper:{pmid:'2',title:'Current selection'},artifacts:[]}]));
  await context.applyLibrary(); finish(response(libraryResult())); await slow;
  assert.match($('library-papers').children[0].innerHTML, /Current selection/);
  context.fetch = async () => { throw new Error('Dataset unavailable'); };
  await context.library();
  assert.equal($('library-papers').children.length, 0);
  assert.match($('library-summary').textContent, /Dataset unavailable/);
  assert.equal($('library-next').disabled, true);
});

test('library handles empty results and clamps a page after the result set shrinks', async () => {
  const { context, $ } = app(); const pages = [];
  context.fetch = async url => { const page = Number(new URL('http://local' + url).searchParams.get('page')); pages.push(page); return response(libraryResult(page, 1, page === 1 ? [{paper:{pmid:'1'},artifacts:[]}] : [])); };
  await context.library(25);
  assert.deepEqual(pages, [25, 1]);
  context.fetch = async () => response(libraryResult(1, 0, [])); await context.library();
  assert.match($('library-summary').textContent, /No papers match/);
  assert.equal($('library-prev').disabled, true); assert.equal($('library-next').disabled, true);
});

test('library escapes metadata and storage locations without starting jobs', async () => {
  const { context, $ } = app(); let method;
  context.fetch = async (_url, options) => { method = options.method; return response(libraryResult(1, 1, [{paper:{pmid:'1',title:'<img onerror=x>',authors:['<script>'],doi:'<svg>'},artifacts:[{storage_prefix:'<b>',storage_key:'<img>',content_sha256:'<script>'}]}])); };
  await context.library();
  const markup = $('library-papers').children[0].innerHTML;
  assert.match(markup, /&lt;img/); assert.match(markup, /&lt;script/); assert.doesNotMatch(markup, /<img|<script|<svg/);
  assert.equal(method, 'GET');
});

test('opening a query library clears stale filters and retains the exact query ID', async () => {
  const { context, $ } = app();
  context.fetch = async () => response({queries:[{query_id:'full-query',query:'solitude',created_at:'2026-09-17'}]});
  $('library-search').value = 'old filter'; $('library-from').value = '2026-09-01';
  await context.openLibrary('full-query');
  assert.equal(context.location.hash, 'library');
  assert.equal($('library-query').value, 'full-query'); assert.equal($('library-search').value, '');
  assert.equal($('library-from').value, ''); assert.equal($('library-status').value, 'published');
});
