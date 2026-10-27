const assert = require('node:assert/strict');
const { test } = require('node:test');
const { context, install, load, routeFetch } = require('./harness.cjs');

const ROUTES = {
  '/pubmed/api/papers': { total: 1205, page: 1, page_size: 1, total_pages: 1205, papers: [] },
  '/pubmed/api/queries': { queries: [{ query_id: 'a' }, { query_id: 'b' }] },
  '/phases_v2/api/collections': { collections: [{ collection_id: 'c' }] },
  '/phases_v2/api/prompts': { prompts: [{ prompt_id: '1', name: 'Effects' }, { prompt_id: '2', name: 'Effects' }, { prompt_id: '3', name: 'Causes' }] },
  '/phases_v2/api/requests?limit=100': { requests: [
    { request_id: 'latest', status: 'running', requested_at: '2026-09-17T10:00:00Z' },
    { request_id: 'b', status: 'pending' }, { request_id: 'c', status: 'succeeded' }, { request_id: 'd', status: 'failed' },
  ] },
  '/phases_v2/api/search/prompts': { prompts: ['Effects'] },
  '/phases_v2/api/search/models': { models: ['m1', 'm2'] },
  '/phases_v2/api/search/paths': { paths: ['phases_v2', 'phases_v2/a', 'pubmed/papers'] },
};

async function overview(routes = ROUTES) {
  const dom = install();
  const { href } = await load('router.js');
  const ctx = context({ href });
  const calls = [];
  globalThis.fetch = routeFetch(routes, calls);
  const { create } = await load('sections/overview.js');
  const section = create(dom.$('section-overview'), ctx);
  return { dom, ctx, section, calls, $: dom.$ };
}

test('the four steps show live counts from the existing endpoints', async () => {
  const { $, section, calls } = await overview();
  await section.refresh();
  assert.equal($('ov-papers').textContent, (1205).toLocaleString());
  assert.equal($('ov-queries').textContent, '2');
  assert.equal($('ov-collections').textContent, '1');
  assert.equal($('ov-prompts').textContent, '2', 'prompts count names, not versions');
  assert.equal($('ov-versions').textContent, '3');
  assert.equal($('ov-active').textContent, '2');
  assert.equal($('ov-succeeded').textContent, '1');
  assert.equal($('ov-failed').textContent, '1');
  assert.equal($('ov-result-prompts').textContent, '1');
  assert.equal($('ov-result-models').textContent, '2');
  assert.equal($('ov-result-paths').textContent, '3');
  assert.match($('ov-latest').innerHTML, /href="#\/runs\/latest"/);
  assert.equal($('ov-message').textContent, '');
  assert.ok(calls.every((c) => c.method === 'GET'), 'the overview only reads');
});

test('one unavailable source shows a dash and a warning, the rest still load', async () => {
  const routes = { ...ROUTES };
  delete routes['/pubmed/api/papers'];
  delete routes['/pubmed/api/queries'];
  const { $, section } = await overview(routes);
  await section.refresh();
  assert.equal($('ov-papers').textContent, '—');
  assert.equal($('ov-queries').textContent, '—');
  assert.equal($('ov-prompts').textContent, '2');
  assert.match($('ov-message').textContent, /Some counts could not be loaded \(2 sources\)/);
  assert.equal($('ov-message').className, 'msg warn');
});

test('with no runs yet the next step is named', async () => {
  const { $, section } = await overview({ ...ROUTES, '/phases_v2/api/requests?limit=100': { requests: [] } });
  await section.refresh();
  assert.match($('ov-latest').innerHTML, /No runs yet/);
});

test('the quick search opens Search with the query', async () => {
  const { $, ctx } = await overview();
  $('ov-q').value = ' being alone ';
  $('ov-search').listeners.submit[0]({ preventDefault() {} });
  assert.equal(ctx.navigated.at(-1), '#/search?q=being+alone&mode=semantic');
});
