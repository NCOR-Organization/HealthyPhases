// Document previews and Prompts: the shared preview and the prompt library page.
// Collections have their own file, collection_pages_test.cjs.
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { context, element, install, load, response, routeFetch, settle } = require('./harness.cjs');

const preview = (name) => ({ documents: [{ name, location: 'phases_v2/a', key: name, supported: true }], total: 1, ingestable: 1, already_ingested: 0, unsupported: 0 });

async function mount(name, routes) {
  const dom = install();
  const { href, parse } = await load('router.js');
  const { confirmAction } = await load('ui.js');
  const runs = { located: [], prompts: [], useLocations(l, c) { runs.located.push([l, c]); }, selectPrompts(a, r = []) { runs.prompts.push([a, r]); } };
  const ctx = context({ href, confirm: confirmAction, sections: { runs } });
  const calls = [];
  globalThis.fetch = routeFetch(routes, calls);
  const { create } = await load(`sections/${name}.js`);
  const section = create(dom.$(`section-${name}`), ctx);
  return { dom, ctx, section, parse, calls, runs, $: dom.$, a: section.actions };
}

// ---- Document previews ----

test('late document responses cannot replace a newer selection', async () => {
  install();
  const { documentPreview } = await load('documents.js');
  const body = element('tbody');
  const summary = element('p');
  const docs = documentPreview(body, summary);
  let finishFirst;
  globalThis.fetch = () => new Promise((resolve) => { finishFirst = resolve; });
  const first = docs.storage(['phases_v2/old']);
  globalThis.fetch = async () => response(preview('current.pdf'));
  await docs.storage(['phases_v2/new']);
  finishFirst(response(preview('stale.pdf')));
  await first;
  assert.equal(body.children.length, 1);
  assert.match(body.children[0].innerHTML, /current.pdf/);
  assert.doesNotMatch(body.children[0].innerHTML, /stale.pdf/);
});

test('failed previews clear old document rows and report the error', async () => {
  install();
  const { documentPreview } = await load('documents.js');
  const body = element('tbody');
  const summary = element('p');
  const docs = documentPreview(body, summary);
  globalThis.fetch = async () => response(preview('old.pdf'));
  await docs.storage(['phases_v2/a']);
  globalThis.fetch = async () => { throw new Error('Storage unavailable'); };
  await docs.storage(['phases_v2/b']);
  assert.equal(body.children.length, 0);
  assert.match(summary.textContent, /Storage unavailable/);
  assert.equal(summary.className, 'msg bad');
});

test('document names and paths cannot introduce executable markup', async () => {
  install();
  const { documentPreview } = await load('documents.js');
  const body = element('tbody');
  const docs = documentPreview(body, element('p'));
  globalThis.fetch = async () => response(preview('<img src=x onerror=alert(1)>.pdf'));
  await docs.storage(['phases_v2']);
  const markup = body.children[0].innerHTML;
  assert.match(markup, /&lt;img/);
  assert.doesNotMatch(markup, /<img/);
});

test('the preview tells new, already ingested and unreadable objects apart and names folders', async () => {
  install();
  const { documentPreview } = await load('documents.js');
  const body = element('tbody');
  const summary = element('p');
  const docs = documentPreview(body, summary, (prefix) => (prefix === 'phases_v2/a' ? 'Folder A' : prefix));
  globalThis.fetch = async () => response({
    documents: [
      { name: 'new.pdf', location: 'phases_v2/a', key: 'k1', supported: true, already_ingested: false },
      { name: 'old.pdf', location: 'phases_v2/a', key: 'k2', supported: true, already_ingested: true },
      { name: 'notes.txt', location: 'phases_v2/a', key: 'k3', supported: false },
    ],
    total: 3, ingestable: 2, already_ingested: 1, unsupported: 1, failed_locations: ['phases_v2/b'],
  });
  await docs.storage(['phases_v2/a', 'phases_v2/b']);
  assert.deepEqual(body.children.map((row) => row.innerHTML.match(/pill \w+">([^<]+)/)[1]), ['new', 'ingested', 'not a document']);
  assert.match(body.children[0].innerHTML, /Folder A/);
  assert.match(summary.textContent, /3 objects: 1 new, 1 already ingested, 1 unsupported\. Could not read: phases_v2\/b/);
  assert.equal(summary.className, 'msg warn');
});

test('no folders chosen means no request and a hint instead', async () => {
  const dom = install();
  const { documentPreview } = await load('documents.js');
  const summary = element('p');
  await documentPreview(element('tbody'), summary).storage([]);
  assert.match(summary.textContent, /Choose storage folders/);
  assert.equal(dom.calls.length, 0);
});

// ---- Prompts ----

const PROMPTS = { prompts: [
  { prompt_id: 'effects-aaaaaaaa', name: 'Effects', template: 'A {chunk_text}', output_key: 'effects' },
  { prompt_id: 'effects-bbbbbbbb', name: 'Effects', template: 'B {chunk_text}', output_key: 'effects' },
  { prompt_id: 'causes-cccccccc', name: '<b>Causes</b>', template: 'C {chunk_text}', output_key: 'causes' },
] };
const prompts = (routes = {}) => mount('prompts', { '/phases_v2/api/prompts': PROMPTS, ...routes });

test('the prompt library lists names, telling versions apart only when they share one, and escapes them', async () => {
  const { $, section, parse } = await prompts();
  await section.show(parse('#/prompts'));
  const labels = $('pr-list').children.map((b) => b.innerHTML);
  assert.match(labels[0], /^Effects \(version aaaaaaaa\)<small>effects/);
  assert.match(labels[2], /^&lt;b&gt;Causes&lt;\/b&gt;<small>causes/);
  $('pr-search').value = 'caus';
  $('pr-search').listeners.input[0]();
  assert.equal($('pr-list').children.length, 1);
  $('pr-search').value = 'nothing';
  $('pr-search').listeners.input[0]();
  assert.match($('pr-list').innerHTML, /No prompt matches/);
});

test('a prompt deep link opens that exact version with its output format', async () => {
  const { $, section, parse } = await prompts();
  await section.show(parse('#/prompts/effects-bbbbbbbb'));
  assert.equal($('pr-template').value, 'B {chunk_text}');
  assert.equal($('pr-output').value, 'effects');
  assert.match($('pr-format').textContent, /\{"effects":\["An extracted claim"\]\}/);
  assert.equal($('pr-use').disabled, false);
});

test('saving creates a new version, selects it for the next run in place of the old one, and keeps the link', async () => {
  const saved = { prompt_id: 'effects-dddddddd', name: 'Effects', template: 'D {chunk_text}', output_key: 'effects' };
  const { $, a, section, parse, runs, ctx, calls } = await prompts();
  await section.show(parse('#/prompts/effects-bbbbbbbb'));
  globalThis.fetch = routeFetch({ 'POST /phases_v2/api/prompts': saved, '/phases_v2/api/prompts': { prompts: [...PROMPTS.prompts, saved] } }, calls);
  $('pr-template').value = 'D {chunk_text}';
  await a.save();
  assert.deepEqual(calls.find((c) => c.method === 'POST').body, { name: 'Effects', template: 'D {chunk_text}', output_key: 'effects' });
  assert.deepEqual(runs.prompts.at(-1), [['effects-dddddddd'], ['effects-bbbbbbbb']]);
  assert.equal(ctx.replaced.at(-1), '#/prompts/effects-dddddddd');
  assert.match($('pr-message').textContent, /selected for your next run/);
});

test('duplicating starts a new prompt from the current text', async () => {
  const { $, a, section, parse, ctx } = await prompts();
  await section.show(parse('#/prompts/causes-cccccccc'));
  a.duplicate();
  assert.equal($('pr-name').value, '<b>Causes</b> copy');
  assert.equal($('pr-template').value, 'C {chunk_text}');
  assert.equal($('pr-use').disabled, true);
  assert.equal(ctx.replaced.at(-1), '#/prompts/new');
});

test('add to a new run selects the version in Runs and opens the form', async () => {
  const { a, section, parse, runs, ctx } = await prompts();
  await section.show(parse('#/prompts/causes-cccccccc'));
  a.useInRun();
  assert.deepEqual(runs.prompts.at(-1), [['causes-cccccccc'], []]);
  assert.equal(ctx.navigated.at(-1), '#/runs/new');
});

test('an empty library tells the user how to start', async () => {
  const { $, section, parse } = await prompts({ '/phases_v2/api/prompts': { prompts: [] } });
  await section.show(parse('#/prompts'));
  assert.match($('pr-list').innerHTML, /No prompts yet/);
  assert.equal($('pr-title').textContent, 'New prompt');
});

test('the relations output format points to the full example', async () => {
  install();
  const { formatExample } = await load('sections/prompts.js');
  assert.match(formatExample('relations'), /probabilistic_processes/);
  await settle(1);
});

// ---- Review round 1 ----

test('New prompt gives a blank form after Duplicate', async () => {
  const { $, a, section, parse } = await prompts();
  await section.show(parse('#/prompts/causes-cccccccc'));
  a.duplicate();
  assert.equal($('pr-name').value, '<b>Causes</b> copy');
  await section.show(parse('#/prompts/new'));
  assert.equal($('pr-name').value, '');
  assert.equal($('pr-template').value, '');
});

test('coming back to Prompts lists a version saved elsewhere and keeps the open draft', async () => {
  const added = { prompt_id: 'later-eeeeeeee', name: 'Later', template: 'L {chunk_text}', output_key: 'results' };
  const { $, section, parse } = await prompts();
  await section.show(parse('#/prompts/causes-cccccccc'));
  $('pr-template').value = 'Draft {chunk_text}';
  globalThis.fetch = routeFetch({ '/phases_v2/api/prompts': { prompts: [...PROMPTS.prompts, added] } });
  await section.show(parse('#/prompts/causes-cccccccc'), { entering: true });
  assert.equal($('pr-template').value, 'Draft {chunk_text}');
  assert.ok($('pr-list').children.some((b) => /^Later/.test(b.innerHTML)));
});
