// Runs: the Pipeline app's New run, saved configurations and order requests.
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { context, install, load, response, routeFetch, settle } = require('./harness.cjs');

const CHOICES = {
  '/phases_v2/api/locations': { locations: [{ prefix: 'phases_v2/a', name: 'Folder A' }, { prefix: 'phases_v2/b', name: 'Folder B' }] },
  '/phases_v2/api/chunkers': { chunkers: [{ chunker_id: 'chunker', name: 'Pages', version: 2 }] },
  '/phases_v2/api/prompts': { prompts: [
    { prompt_id: 'old-version-aaaaaaaa', name: 'Effects', template: 'a {chunk_text}', output_key: 'effects' },
    { prompt_id: 'new-version-bbbbbbbb', name: 'Effects', template: 'b {chunk_text}', output_key: 'effects' },
    { prompt_id: 'causes-cccccccc', name: 'Causes', template: 'c {chunk_text}', output_key: 'causes' },
  ] },
  '/phases_v2/api/models': { models: [{ model_id: 'model', display_name: 'Model One' }, { model_id: 'gone', display_name: 'Retired model', available: false }] },
  '/phases_v2/api/collections': { collections: [{ collection_id: 'c1', name: 'Research', locations: ['phases_v2/b'] }] },
  '/phases_v2/api/pipelines': { pipelines: [{ pipeline_id: 'p1', name: 'Weekly', created_at: '2026-09-01T10:00:00Z', inputs: { locations: ['phases_v2/a'], prompt_ids: ['causes-cccccccc'], model_id: 'model', chunker_id: 'chunker' } }] },
  '/phases_v2/api/chunker-warning': { warning: null },
  '/phases_v2/api/documents': { documents: [], total: 0, ingestable: 0, already_ingested: 0, unsupported: 0 },
  '/phases_v2/api/sources/pubmed': { available: true, queries: [{ query_id: 'q1', query: 'solitude', published_paper_count: 3, last_ingested_at: '' }] },
};

async function runs(routes = {}, { loaded = true } = {}) {
  const dom = install();
  const { href, parse } = await load('router.js');
  const { confirmAction } = await load('ui.js');
  const ctx = context({ href, confirm: confirmAction });
  const calls = [];
  globalThis.fetch = routeFetch({ ...CHOICES, ...routes }, calls);
  const { create } = await load('sections/runs.js');
  const section = create(dom.$('section-runs'), ctx);
  if (loaded) await section.actions.loadChoices();
  await settle();
  return { dom, ctx, section, parse, calls, $: dom.$, a: section.actions };
}

const choose = (select, values) => { for (const option of select.options) option.selected = values.includes(option.value); };

test('every prompt is selected at first, and an unavailable model cannot be chosen', async () => {
  const { $ } = await runs();
  assert.deepEqual($('run-prompts').selectedOptions.map((o) => o.value), ['old-version-aaaaaaaa', 'new-version-bbbbbbbb', 'causes-cccccccc']);
  const retired = $('run-model').options.find((o) => o.value === 'gone');
  assert.equal(retired.disabled, true);
  assert.match(retired.textContent, /unavailable here/);
  assert.equal($('run-model').value, 'model');
  assert.equal($('run-submit').disabled, false);
});

test('prompt versions that share a name are told apart, and others show only their name', async () => {
  const { $ } = await runs();
  assert.deepEqual($('run-prompts').options.map((o) => o.textContent), ['Effects (version aaaaaaaa)', 'Effects (version bbbbbbbb)', 'Causes']);
});

test('a run sends all chosen folders and prompt versions to the resolved API', async () => {
  const { $, a, dom, calls } = await runs({ 'POST /phases_v2/api/requests': { request_id: 'request-123', status: 'pending' } });
  dom.window.__NEXUS_RUNTIME_CONFIG__ = { apiUrl: 'https://abi.example/' };
  choose($('run-locations'), ['phases_v2/a', 'phases_v2/b']);
  choose($('run-prompts'), ['old-version-aaaaaaaa', 'new-version-bbbbbbbb']);
  await a.submit();
  const sent = calls.at(-1);
  assert.equal(sent.url, 'https://abi.example/phases_v2/api/requests');
  assert.deepEqual(sent.body, { locations: ['phases_v2/a', 'phases_v2/b'], prompt_ids: ['old-version-aaaaaaaa', 'new-version-bbbbbbbb'], model_id: 'model', chunker_id: 'chunker' });
  assert.equal($('run-view-request').hidden, false);
  assert.equal($('run-view-request').href, '#/runs/request-123');
});

test('a run with nothing chosen explains what is missing and sends nothing', async () => {
  const { $, a, calls } = await runs();
  choose($('run-locations'), []);
  const before = calls.length;
  await assert.rejects(a.submit(), /Choose at least one storage folder/);
  assert.equal(calls.length, before);
});

test('PubMed runs submit the search and pipeline choices without a storage rescan', async () => {
  const { $, a, calls } = await runs({ 'POST /phases_v2/api/sources/pubmed/requests': { request_id: 'new-request' } });
  $('run-source').value = 'pubmed';
  $('run-pubmed-query').value = 'q1';
  choose($('run-prompts'), ['causes-cccccccc']);
  await a.submit();
  const sent = calls.at(-1);
  assert.equal(sent.url, '/phases_v2/api/sources/pubmed/requests');
  assert.deepEqual(sent.body, { query_id: 'q1', prompt_ids: ['causes-cccccccc'], model_id: 'model', chunker_id: 'chunker' });
});

test('the PubMed preview shows only published artifacts and escapes paper titles', async () => {
  const { $, a } = await runs({ '/phases_v2/api/sources/pubmed/q1': { artifacts: [{ title: '<img onerror=x>', storage_prefix: 'pubmed/papers', storage_key: 'paper.pdf' }] } });
  $('run-source').value = 'pubmed';
  $('run-pubmed-query').value = 'q1';
  await a.refreshDocuments();
  assert.equal($('run-documents').children.length, 1);
  assert.match($('run-documents').children[0].innerHTML, /&lt;img/);
  assert.match($('run-documents-summary').textContent, /1 published artifact/);
});

test('PubMed search options show paper counts and local ingestion dates while keeping the selection', async () => {
  const timestamp = '2026-09-17T10:30:00+00:00';
  const { $, a } = await runs({ '/phases_v2/api/sources/pubmed': { available: true, queries: [
    { query_id: 'preview-query', query: 'solitude', published_paper_count: 1, last_ingested_at: '' },
    { query_id: 'full-query', query: 'solitude', published_paper_count: 350, last_ingested_at: timestamp },
    { query_id: 'empty-query', query: '<img onerror=x>', published_paper_count: 0, last_ingested_at: '' },
  ] } });
  $('run-pubmed-query').value = 'full-query';
  await a.loadPubmed();
  const options = $('run-pubmed-query').options;
  assert.equal(options[0].textContent, 'Choose a search');
  assert.equal(options[1].textContent, 'solitude | 1 published paper | No completed ingestion');
  assert.equal(options[2].textContent, `solitude | 350 published papers | Last ingestion: ${new Date(timestamp).toLocaleString()}`);
  assert.equal(options[2].selected, true);
  assert.equal(options[1].selected, false);
  assert.equal(options[3].textContent, '<img onerror=x> | 0 published papers | No completed ingestion');
  assert.equal(options[3].innerHTML, '');
});

test('choosing a collection selects its folders and previews them', async () => {
  const { $, calls } = await runs();
  $('run-collection').value = 'c1';
  await Promise.all($('run-collection').listeners.change.map((h) => h({})));
  await settle();
  assert.deepEqual($('run-locations').selectedOptions.map((o) => o.value), ['phases_v2/b']);
  assert.equal($('run-manage-collection').href, '#/collections/c1');
  assert.ok(calls.some((c) => c.url === '/phases_v2/api/documents?location=phases_v2%2Fb'));
});

test('folders sent from Collections land in the form, even before it has loaded', async () => {
  const { $, section } = await runs({}, { loaded: false });
  section.useLocations(['phases_v2/a', 'phases_v2/new'], 'c1');
  await section.actions.loadChoices();
  assert.deepEqual($('run-locations').selectedOptions.map((o) => o.value), ['phases_v2/a', 'phases_v2/new']);
  assert.equal($('run-collection').value, 'c1');
  assert.equal($('run-source').value, 'storage');
});

test('a prompt version saved in Prompts replaces the one it came from in the next run', async () => {
  const added = { prompt_id: 'newest-dddddddd', name: 'Causes', template: 'd {chunk_text}', output_key: 'causes' };
  const { $, section } = await runs();
  globalThis.fetch = routeFetch({ ...CHOICES, '/phases_v2/api/prompts': { prompts: [...CHOICES['/phases_v2/api/prompts'].prompts, added] } });
  await section.selectPrompts(['newest-dddddddd'], ['causes-cccccccc']);
  const chosen = $('run-prompts').selectedOptions.map((o) => o.value);
  assert.ok(chosen.includes('newest-dddddddd'));
  assert.ok(!chosen.includes('causes-cccccccc'));
});

test('a refresh keeps the draft and shows newly added options', async () => {
  const { $, a } = await runs();
  choose($('run-prompts'), ['causes-cccccccc']);
  choose($('run-locations'), ['phases_v2/a']);
  globalThis.fetch = routeFetch({ ...CHOICES, '/phases_v2/api/locations': { locations: [...CHOICES['/phases_v2/api/locations'].locations, { prefix: 'phases_v2/c', name: 'Folder C' }] } });
  await a.loadChoices();
  assert.deepEqual($('run-prompts').selectedOptions.map((o) => o.value), ['causes-cccccccc']);
  assert.deepEqual($('run-locations').selectedOptions.map((o) => o.value), ['phases_v2/a']);
  assert.equal($('run-locations').options.length, 3);
});

test('saving folders as a collection selects the new collection', async () => {
  const { $, a, calls } = await runs({ 'POST /phases_v2/api/collections': { collection_id: 'c2', name: 'Quick', locations: ['phases_v2/a'] } });
  choose($('run-locations'), ['phases_v2/a']);
  $('run-quick-name').value = ' Quick ';
  await a.quickSave();
  assert.deepEqual(calls.find((c) => c.method === 'POST').body, { name: 'Quick', locations: ['phases_v2/a'] });
  assert.equal($('run-collection').value, 'c2');
});

test('saved configurations are saved from the form, loaded back into it, and run after confirmation', async () => {
  const { $, a, calls } = await runs({
    'POST /phases_v2/api/pipelines': { pipeline_id: 'p2', name: 'Mine' },
    'POST /phases_v2/api/pipelines/p1/requests': { request_id: 'from-saved' },
  });
  choose($('run-locations'), ['phases_v2/b']);
  $('run-config-name').value = 'Mine';
  await a.saveConfiguration();
  assert.deepEqual(calls.find((c) => c.url.endsWith('/pipelines') && c.method === 'POST').body, {
    name: 'Mine', inputs: { locations: ['phases_v2/b'], chunker_id: 'chunker', prompt_ids: ['old-version-aaaaaaaa', 'new-version-bbbbbbbb', 'causes-cccccccc'], model_id: 'model' },
  });

  $('run-saved').value = 'p1';
  await a.loadConfiguration();
  assert.deepEqual($('run-locations').selectedOptions.map((o) => o.value), ['phases_v2/a']);
  assert.deepEqual($('run-prompts').selectedOptions.map((o) => o.value), ['causes-cccccccc']);
  assert.equal($('run-config-name').value, 'Weekly');

  const pending = a.runConfiguration();
  const summary = $('confirm-body').children.map((p) => p.textContent).join(' ');
  assert.match(summary, /Folder A/);
  assert.match(summary, /Causes/);
  assert.match(summary, /Model One/);
  assert.equal(calls.some((c) => c.url.endsWith('/pipelines/p1/requests')), false, 'nothing is queued before confirmation');
  await $('confirm-ok').onclick();
  await pending;
  assert.equal(calls.filter((c) => c.url.endsWith('/pipelines/p1/requests')).length, 1);
  assert.equal($('run-view-request').href, '#/runs/from-saved');
});

test('cancelling a saved configuration run queues nothing', async () => {
  const { $, a, calls } = await runs();
  $('run-saved').value = 'p1';
  const pending = a.runConfiguration();
  $('confirm-cancel').onclick();
  assert.equal(await pending, undefined);
  assert.equal(calls.some((c) => c.method === 'POST'), false);
});

const REQUESTS = { requests: [
  { request_id: 'r-1', status: 'running', requested_at: '2026-09-17T10:00:00Z', locations: ['phases_v2/a'], prompt_ids: ['causes-cccccccc'], model_id: 'model' },
  { request_id: 'r-2', status: 'failed', requested_at: '2026-09-16T10:00:00Z', locations: ['dataset:pubmed:q1'], prompt_ids: ['old-version-aaaaaaaa'], model_id: 'model', error: 'Boom' },
] };

test('requests are named by their papers, prompts and model rather than ids, and filter by status', async () => {
  const { $, a } = await runs({ '/phases_v2/api/requests?limit=100': REQUESTS });
  await a.loadPubmed();
  await a.loadRequests();
  const [first, second] = $('run-requests').children;
  assert.match(first.innerHTML, /Folder A/);
  assert.match(first.innerHTML, /Causes/);
  assert.match(first.innerHTML, /Model One/);
  assert.match(first.innerHTML, /href="#\/runs\/r-1"/);
  assert.match(second.innerHTML, /PubMed: solitude/);
  $('run-status').value = 'failed';
  a.renderRequests();
  assert.equal($('run-requests').children.length, 1);
  $('run-status').value = 'succeeded';
  a.renderRequests();
  assert.match($('run-requests').innerHTML, /No runs have this status/);
});

test('a deep link opens the request details', async () => {
  const { $, section, parse } = await runs({
    '/phases_v2/api/requests?limit=100': REQUESTS,
    '/phases_v2/api/requests/r-1': { ...REQUESTS.requests[0], status: 'succeeded', chunker_id: 'chunker', run_id: 'dagster-run', counts: { succeeded: 4, failed: 1, skipped: 0, prompts_run: 1 } },
  });
  await section.show(parse('#/runs/r-1'));
  assert.equal($('run-view-list').hidden, false);
  assert.equal($('run-detail').hidden, false);
  const detail = $('run-detail-content').innerHTML;
  assert.match(detail, /Folder A/);
  assert.match(detail, /Pages v2/);
  assert.match(detail, /4 succeeded, 1 failed, 0 skipped across 1 prompt\./);
  assert.match(detail, /dagster-run/);
  assert.equal($('run-detail-results').hidden, false);
  assert.equal($('run-detail-results').href, '#/search?mode=semantic&prompt=Causes&model=model');
  assert.equal($('run-detail-title').focused, true);
});

test('slow request refreshes never overlap', async () => {
  const { a } = await runs();
  let finish;
  let calls = 0;
  globalThis.fetch = () => { calls += 1; return new Promise((resolve) => { finish = resolve; }); };
  const first = a.loadRequests();
  await a.loadRequests();
  assert.equal(calls, 1);
  finish(response({ requests: [] }));
  await first;
});

test('requests refresh every 10 seconds only while the list is open and the page visible', async () => {
  const { section, ctx, parse, dom, calls } = await runs({ '/phases_v2/api/requests?limit=100': { requests: [] } });
  const poll = ctx.intervals.find((i) => i.ms === 10000);
  await section.show(parse('#/runs'));
  const count = () => calls.filter((c) => c.url.includes('/requests?limit=100')).length;
  const before = count();
  poll.work();
  await settle();
  assert.equal(count(), before + 1);
  dom.document.hidden = true;
  poll.work();
  dom.document.hidden = false;
  await section.show(parse('#/runs/new'));
  poll.work();
  section.hide();
  poll.work();
  await settle();
  assert.equal(count(), before + 1);
});

test('the new-run view and the list are separate views with their own tab', async () => {
  const { $, section, parse } = await runs();
  await section.show(parse('#/runs/new'));
  assert.equal($('run-view-new').hidden, false);
  assert.equal($('run-view-list').hidden, true);
  assert.equal($('run-tab-new').attributes['aria-current'], 'page');
  assert.equal($('run-tab-list').attributes['aria-current'], undefined);
});
