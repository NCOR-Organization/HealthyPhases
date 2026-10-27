// Collections and Prompts: the Pipeline app's collection, folder, upload and prompt library pages.
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { context, element, install, load, response, routeFetch, settle } = require('./harness.cjs');

const LOCATIONS = { locations: [{ prefix: 'phases_v2', name: 'phases_v2 (all)' }, { prefix: 'phases_v2/a', name: 'Folder A' }] };
const COLLECTIONS = { collections: [{ collection_id: 'c1', name: 'Research', locations: ['phases_v2/a'] }, { collection_id: 'c2', name: 'Other', locations: ['phases_v2'] }] };
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

const collections = (routes = {}) => mount('collections', {
  '/phases_v2/api/locations': LOCATIONS, '/phases_v2/api/collections': COLLECTIONS, '/phases_v2/api/documents': preview('paper.pdf'), ...routes,
});

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

// ---- Collections ----

test('the first collection opens by default and a deep link opens a given one', async () => {
  const { $, section, parse, ctx } = await collections();
  await section.show(parse('#/collections'));
  assert.equal($('col-name').value, 'Research');
  assert.equal(ctx.replaced.at(-1), '#/collections/c1');
  assert.match($('col-list').children[0].innerHTML, /Research<small>1 storage folder/);
  assert.equal($('col-list').children[0].attributes['aria-pressed'], 'true');
  await section.show(parse('#/collections/c2'));
  assert.equal($('col-name').value, 'Other');
  assert.equal($('col-archive').hidden, false);
  assert.equal($('col-title').textContent, 'Edit Other');
});

test('coming back from the sidebar keeps an unsaved collection draft', async () => {
  const { $, section, parse, ctx } = await collections();
  await section.show(parse('#/collections/new'));
  $('col-name').value = 'Draft in progress';
  await section.show(parse('#/collections'));
  assert.equal($('col-name').value, 'Draft in progress');
  assert.equal(ctx.replaced.at(-1), '#/collections/new');
});

test('an unknown collection link says so and offers a new form', async () => {
  const { $, section, parse } = await collections();
  await section.show(parse('#/collections/gone'));
  assert.match($('col-message').textContent, /no longer exists/);
  assert.equal($('col-title').textContent, 'New collection');
});

test('saving creates a new collection, then updates the same one', async () => {
  const { $, a, section, parse, calls, ctx } = await collections({
    'POST /phases_v2/api/collections': { collection_id: 'c3', name: 'Fresh', locations: ['phases_v2/a'] },
    'PUT /phases_v2/api/collections/c3': { collection_id: 'c3', name: 'Renamed', locations: ['phases_v2/a'] },
  });
  await section.show(parse('#/collections/new'));
  $('col-name').value = ' Fresh ';
  for (const option of $('col-locations').options) option.selected = option.value === 'phases_v2/a';
  await a.save();
  assert.deepEqual(calls.find((c) => c.method === 'POST').body, { name: 'Fresh', locations: ['phases_v2/a'] });
  assert.equal(ctx.replaced.at(-1), '#/collections/c3');
  $('col-name').value = 'Renamed';
  await a.save();
  assert.equal(calls.filter((c) => c.method === 'PUT').length, 1);
  assert.equal($('col-message').textContent, 'Collection saved.');
});

test('a collection needs at least one folder', async () => {
  const { $, a, section, parse } = await collections();
  await section.show(parse('#/collections/new'));
  $('col-name').value = 'Empty';
  await assert.rejects(a.save(), /at least one storage folder/);
});

test('archiving asks first, and cancelling keeps the collection', async () => {
  const { $, a, section, parse, calls } = await collections({ 'DELETE /phases_v2/api/collections/c1': { archived: true } });
  await section.show(parse('#/collections/c1'));
  const cancelled = a.archive();
  assert.match($('confirm-title').textContent, /Archive "Research"/);
  assert.equal($('confirm-ok').className, 'danger-solid');
  $('confirm-cancel').onclick();
  assert.equal(await cancelled, false);
  assert.equal(calls.some((c) => c.method === 'DELETE'), false);
  const confirmed = a.archive();
  await $('confirm-ok').onclick();
  assert.equal(await confirmed, true);
  assert.equal(calls.filter((c) => c.method === 'DELETE').length, 1);
  assert.match($('col-message').textContent, /archived/);
});

test('use in a new run hands the folders to Runs, naming the collection only when unchanged', async () => {
  const { $, a, section, parse, runs, ctx } = await collections();
  await section.show(parse('#/collections/c1'));
  a.useInRun();
  assert.deepEqual(runs.located[0], [['phases_v2/a'], 'c1']);
  assert.equal(ctx.navigated.at(-1), '#/runs/new');
  for (const option of $('col-locations').options) option.selected = true;
  a.useInRun();
  assert.deepEqual(runs.located[1], [['phases_v2', 'phases_v2/a'], '']);
});

test('a new folder joins the collection being edited', async () => {
  const { $, a, section, parse } = await collections({ 'POST /phases_v2/api/locations': { prefix: 'phases_v2/new', name: 'New one' } });
  await section.show(parse('#/collections/c1'));
  globalThis.fetch = routeFetch({
    'POST /phases_v2/api/locations': { prefix: 'phases_v2/new', name: 'New one' },
    '/phases_v2/api/locations': { locations: [...LOCATIONS.locations, { prefix: 'phases_v2/new', name: 'New one' }] },
    '/phases_v2/api/documents': preview('x.pdf'),
  });
  $('col-location-name').value = 'New one';
  await a.createLocation();
  assert.deepEqual($('col-locations').selectedOptions.map((o) => o.value), ['phases_v2/a', 'phases_v2/new']);
  assert.equal($('col-upload-location').value, 'phases_v2/new');
});

test('uploads report each file, refuse files over 25 MiB and send the PDF bytes', async () => {
  const { $, a, section, parse, calls } = await collections({
    'POST /phases_v2/api/documents': (url) => (url.includes('bad.pdf') ? response({ detail: 'Not a PDF.' }, { ok: false }) : response({ key: 'ok' })),
  });
  await section.show(parse('#/collections/c1'));
  $('col-upload-location').value = 'phases_v2/a';
  const good = { name: 'good.pdf', size: 10 };
  $('col-upload-files').files = [good, { name: 'bad.pdf', size: 10 }, { name: 'huge.pdf', size: 26 * 1024 * 1024 }];
  await a.upload();
  const uploads = calls.filter((c) => c.method === 'POST');
  assert.equal(uploads.length, 2, 'the oversized file is never sent');
  assert.equal(uploads[0].url, '/phases_v2/api/documents?location=phases_v2%2Fa&filename=good.pdf');
  assert.equal(uploads[0].body, good);
  assert.equal(uploads[0].headers['Content-Type'], 'application/pdf');
  assert.equal($('col-upload-message').textContent, 'good.pdf: uploaded\nbad.pdf: failed - Not a PDF.\nhuge.pdf: failed - larger than 25 MiB');
  assert.equal($('col-upload-message').className, 'msg warn');
});

test('an upload with nothing chosen explains what to do', async () => {
  const { $, a, section, parse } = await collections();
  await section.show(parse('#/collections/c1'));
  $('col-upload-files').files = [];
  await assert.rejects(a.upload(), /Choose a storage folder and at least one PDF/);
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

test('coming back to Collections shows a collection saved in Runs, and its link opens it', async () => {
  const { $, section, parse } = await collections();
  await section.show(parse('#/collections/c1'));
  globalThis.fetch = routeFetch({
    '/phases_v2/api/locations': LOCATIONS, '/phases_v2/api/documents': preview('paper.pdf'),
    '/phases_v2/api/collections': { collections: [...COLLECTIONS.collections, { collection_id: 'c9', name: 'Saved in Runs', locations: ['phases_v2/a'] }] },
  });
  await section.show(parse('#/collections/c9'), { entering: true });
  assert.equal($('col-name').value, 'Saved in Runs');
  assert.doesNotMatch($('col-message').textContent, /no longer exists/);
  assert.ok($('col-list').children.some((b) => /Saved in Runs/.test(b.innerHTML)));
});

test('coming back keeps an open collection draft while re-reading the lists', async () => {
  const { $, section, parse, calls } = await collections();
  await section.show(parse('#/collections/c1'));
  $('col-name').value = 'Edited but not saved';
  const before = calls.filter((c) => c.url.endsWith('/collections')).length;
  await section.show(parse('#/collections/c1'), { entering: true });
  assert.equal($('col-name').value, 'Edited but not saved');
  assert.ok(calls.filter((c) => c.url.endsWith('/collections')).length > before);
});

test('New collection always gives a blank form, even over a draft or after an archive', async () => {
  const { $, a, section, parse } = await collections({ 'DELETE /phases_v2/api/collections/c1': { archived: true } });
  await section.show(parse('#/collections/new'));
  $('col-name').value = 'Abandoned draft';
  await section.show(parse('#/collections/new'));
  assert.equal($('col-name').value, '');
  await section.show(parse('#/collections/c1'));
  const archived = a.archive();
  await $('confirm-ok').onclick();
  await archived;
  $('col-name').value = 'Typed after archiving';
  await section.show(parse('#/collections/new'));
  assert.equal($('col-name').value, '');
});

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
