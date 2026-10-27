const assert = require('node:assert/strict');
const { test } = require('node:test');
const { install, load } = require('./harness.cjs');

test('routes name a section, its parts and its parameters', async () => {
  install();
  const { parse } = await load('router.js');
  const run = parse('#/runs/request-123');
  assert.equal(run.section, 'runs');
  assert.deepEqual(run.parts, ['request-123']);
  const search = parse('#/search?q=being+alone&mode=keyword&prompt=a&prompt=b');
  assert.equal(search.section, 'search');
  assert.equal(search.params.get('q'), 'being alone');
  assert.deepEqual(search.params.getAll('prompt'), ['a', 'b']);
  assert.deepEqual(parse('#/library/schedules?query=q1').parts, ['schedules']);
});

test('an empty or unknown route opens the overview', async () => {
  install();
  const { parse } = await load('router.js');
  for (const hash of ['', '#', '#/', '#/nowhere/else?x=1', '#unknown']) {
    const route = parse(hash);
    assert.equal(route.section, 'overview');
    assert.deepEqual(route.parts, []);
    assert.equal(route.params.toString(), '');
  }
});

test('links round-trip through parse, including awkward characters', async () => {
  install();
  const { href, parse } = await load('router.js');
  const link = href('runs', ['a/b c?#'], { q: 'stress & "alone"', prompt: ['x', 'y'], empty: '', missing: undefined });
  assert.equal(link.startsWith('#/runs/a%2Fb%20c%3F%23?'), true);
  const route = parse(link);
  assert.deepEqual(route.parts, ['a/b c?#']);
  assert.equal(route.params.get('q'), 'stress & "alone"');
  assert.deepEqual(route.params.getAll('prompt'), ['x', 'y']);
  assert.equal(route.params.has('empty'), false);
  assert.equal(href('overview'), '#/overview');
  assert.equal(href('search', [], new URLSearchParams('q=x&mode=keyword')), '#/search?q=x&mode=keyword');
});

test('malformed escapes are kept rather than throwing', async () => {
  install();
  const { parse } = await load('router.js');
  assert.deepEqual(parse('#/runs/%E0%A4%A').parts, ['%E0%A4%A']);
});

test('the router reports every hash change and remembers the route for the session', async () => {
  const dom = install({ hash: '#/runs/r1' });
  const { createRouter } = await load('router.js');
  const seen = [];
  const router = createRouter((route) => seen.push([route.section, ...route.parts]));
  router.start();
  dom.location.hash = '#/search?q=x';
  dom.hashchange();
  assert.deepEqual(seen, [['runs', 'r1'], ['search']]);
  assert.equal(dom.session['healthyphases.workspace.route'], '#/search?q=x');
});

test('opening the app without a hash restores the last route, so a Nexus reload keeps the user there', async () => {
  const dom = install({ hash: '', session: { 'healthyphases.workspace.route': '#/library/schedules' } });
  const { createRouter } = await load('router.js');
  const seen = [];
  createRouter((route) => seen.push([route.section, ...route.parts])).start();
  assert.equal(dom.location.hash, '#/library/schedules');
  assert.deepEqual(seen, [['library', 'schedules']]);
});

test('a deep link wins over the remembered route', async () => {
  const dom = install({ hash: '#/prompts/p1', session: { 'healthyphases.workspace.route': '#/library' } });
  const { createRouter } = await load('router.js');
  const seen = [];
  createRouter((route) => seen.push(route.section)).start();
  assert.deepEqual(seen, ['prompts']);
  assert.equal(dom.location.hash, '#/prompts/p1');
});

test('replace records state without re-rendering; navigate to the same route re-renders it', async () => {
  const dom = install({ hash: '#/search' });
  const { createRouter } = await load('router.js');
  let renders = 0;
  const router = createRouter(() => { renders += 1; });
  router.start();
  router.replace('#/search?q=stress');
  assert.equal(dom.location.hash, '#/search?q=stress');
  assert.equal(dom.session['healthyphases.workspace.route'], '#/search?q=stress');
  assert.equal(renders, 1);
  router.navigate('#/search?q=stress');
  assert.equal(renders, 2);
  router.navigate('#/runs');
  assert.equal(dom.location.hash, '#/runs');
});

test('storage that refuses access does not stop routing', async () => {
  const dom = install({ hash: '#/runs' });
  globalThis.sessionStorage = { getItem() { throw new Error('denied'); }, setItem() { throw new Error('denied'); } };
  const { createRouter } = await load('router.js');
  const seen = [];
  createRouter((route) => seen.push(route.section)).start();
  dom.location.hash = '#/search';
  dom.hashchange();
  assert.deepEqual(seen, ['runs', 'search']);
});
