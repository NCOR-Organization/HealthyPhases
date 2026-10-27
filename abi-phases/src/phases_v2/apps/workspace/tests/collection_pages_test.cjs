// Collections: the list, the one-screen create flow, a collection's page and "Add to collection".
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { context, fire, install, load, response, routeFetch, settle } = require('./harness.cjs');

const SHA = (c) => c.repeat(64);
const LOCATIONS = { locations: [{ prefix: 'phases_v2', name: 'phases_v2 (all)' }, { prefix: 'phases_v2/a', name: 'Folder A' }] };
const SUMMARIES = { collections: [
  { collection_id: 'c1', name: 'Research', description: 'Solitude studies', member_count: 2, paper_count: 3, updated_at: '2026-10-01T10:00:00+00:00', locations: ['phases_v2/a'] },
  // A collection first stored as folders only: no description and no dates.
  { collection_id: 'c2', name: 'Old folders', description: '', member_count: 1, paper_count: 1, updated_at: null, locations: ['phases_v2'] },
] };
const DETAIL = {
  ...SUMMARIES.collections[0],
  members: [
    { member_id: 'folder-1', kind: 'folder', prefix: 'phases_v2/a', label: 'Folder A', paper_count: 2, error: null },
    { member_id: 'query-1', kind: 'pubmed_query', query_id: 'q1', label: 'solitude', paper_count: 2, error: null },
  ],
  paper_count: 3, unsupported: 0, truncated: false, status_counts: { not_ingested: 1, ingested: 1, results: 1 },
  papers: [
    { paper_id: SHA('a'), name: 'A.pdf', path: 'phases_v2/a/A.pdf', status: 'results', results: 4 },
    { paper_id: null, name: 'B.pdf', path: 'phases_v2/a/B.pdf', status: 'not_ingested', results: 0 },
    { paper_id: SHA('c'), name: 'Solitude <b>paper</b>', pmid: '7', path: 'pubmed/papers/7.pdf', status: 'ingested', results: 0 },
  ],
};
const PUBMED = { available: true, queries: [{ query_id: 'q1', query: 'solitude', published_paper_count: 2 }] };

async function mount(routes = {}) {
  const dom = install();
  const { href, parse } = await load('router.js');
  const { confirmAction } = await load('ui.js');
  const runs = { collections: [], useCollection(id) { runs.collections.push(id); } };
  const ctx = context({ href, confirm: confirmAction, sections: { runs } });
  const calls = [];
  globalThis.fetch = routeFetch({
    '/phases_v2/api/locations': LOCATIONS,
    '/phases_v2/api/collections': SUMMARIES,
    '/phases_v2/api/collections/c1': DETAIL,
    '/phases_v2/api/collections/c2': { ...SUMMARIES.collections[1], members: [], papers: [], paper_count: 0, status_counts: {} },
    '/phases_v2/api/sources/pubmed': PUBMED,
    ...routes,
  }, calls);
  const { create } = await load('sections/collections.js');
  const section = create(dom.$('section-collections'), ctx);
  return { dom, ctx, section, parse, calls, runs, $: dom.$, a: section.actions };
}

const posts = (calls) => calls.filter((c) => c.method !== 'GET');
const cells = (body) => body.children.map((row) => row.innerHTML);

// ---- The list ----

test('the list shows each collection with its members, papers and last change, and the first opens by default', async () => {
  const { $, section, parse, ctx } = await mount();
  await section.show(parse('#/collections'));
  assert.equal(ctx.replaced.at(-1), '#/collections/c1');
  const [first, second] = $('col-list').children;
  assert.match(first.innerHTML, /^Research<small>2 members · 3 papers · updated /);
  assert.equal(first.attributes['aria-pressed'], 'true');
  assert.equal(second.innerHTML, 'Old folders<small>1 member · 1 paper</small>');
  assert.equal($('col-name').value, 'Research');
  assert.equal($('col-description').value, 'Solitude studies');
});

test('a collection first stored as folders opens and edits like any other', async () => {
  const { $, a, section, parse, calls } = await mount({ 'PUT /phases_v2/api/collections/c2': { collection_id: 'c2', name: 'Renamed folders' } });
  await section.show(parse('#/collections/c2'));
  assert.equal($('col-title').textContent, 'Old folders');
  $('col-name').value = 'Renamed folders';
  $('col-description').value = ' Now described ';
  await a.save();
  assert.deepEqual(posts(calls)[0].body, { name: 'Renamed folders', description: 'Now described' });
  assert.equal($('col-title').textContent, 'Renamed folders');
});

test('an unknown collection link says so and offers a new form', async () => {
  const { $, section, parse } = await mount();
  await section.show(parse('#/collections/gone'));
  assert.match($('col-message').textContent, /no longer exists/);
  assert.equal($('col-title').textContent, 'New collection');
});

// ---- A collection's page ----

test('a collection page lists its members by type and its papers with their status, escaped', async () => {
  const { $, section, parse } = await mount();
  await section.show(parse('#/collections/c1'));
  const members = cells($('col-members'));
  assert.match(members[0], /<td>Folder<\/td><td>Folder A<\/td><td>2<\/td>/);
  assert.match(members[1], /<td>PubMed search<\/td><td>solitude<\/td><td>2<\/td>/);
  const papers = cells($('col-papers'));
  assert.match(papers[0], /Has results \(4 results\)/);
  assert.match(papers[1], /Not ingested yet/);
  assert.match(papers[2], /Solitude &lt;b&gt;paper&lt;\/b&gt;<small>PMID 7/);
  assert.match(papers[2], />Ingested</);
  assert.equal($('col-papers-summary').textContent, '3 papers: 1 not ingested yet, 1 ingested, 1 with results.');
  assert.equal($('col-search').href, '#/search?collection=c1');
  assert.equal($('col-run').disabled, false);
});

test('a member that cannot be read is named on its row and in the summary', async () => {
  const unreadable = { ...DETAIL, members: [{ ...DETAIL.members[0], paper_count: 0, error: 'Could not read phases_v2/a: timeout' }], papers: [], paper_count: 0, status_counts: {} };
  const { $, section, parse } = await mount({ '/phases_v2/api/collections/c1': unreadable });
  await section.show(parse('#/collections/c1'));
  assert.match(cells($('col-members'))[0], /<small class="bad">Could not read phases_v2\/a: timeout<\/small>/);
  assert.match($('col-papers-summary').textContent, /Could not read: Folder A\./);
  assert.equal($('col-papers-summary').className, 'msg warn');
});

test('on a saved collection, a folder or a search is added straight away and the papers are read again', async () => {
  const { $, a, section, parse, calls } = await mount({ 'POST /phases_v2/api/collections/c1/members': { collection_id: 'c1', name: 'Research' } });
  await section.show(parse('#/collections/c1'));
  const reads = () => calls.filter((c) => c.method === 'GET' && c.url.endsWith('/collections/c1')).length;
  const before = reads();
  $('col-folder').value = 'phases_v2';
  await a.addFolder();
  $('col-pubmed').value = 'q1';
  await a.addPubmed();
  assert.deepEqual(posts(calls).map((c) => [c.url, c.body]), [
    ['/phases_v2/api/collections/c1/members', { members: [{ folder: { prefix: 'phases_v2' } }] }],
    ['/phases_v2/api/collections/c1/members', { members: [{ pubmed_query: { query_id: 'q1' } }] }],
  ]);
  assert.equal(reads(), before + 2);
  assert.match($('col-add-message').textContent, /solitude: added to the collection/);
});

test('uploads go into the collection, report each file and never send one over 25 MiB', async () => {
  const { $, a, section, parse, calls } = await mount({
    'POST /phases_v2/api/collections/c1/documents': (url) => (url.includes('bad.pdf') ? response({ detail: 'The file does not have a PDF header.' }, { ok: false }) : response({ key: 'ok' })),
  });
  await section.show(parse('#/collections/c1'));
  const good = { name: 'good.pdf', size: 10 };
  $('col-upload-files').files = [good, { name: 'bad.pdf', size: 10 }, { name: 'huge.pdf', size: 26 * 1024 * 1024 }];
  await a.upload();
  const sent = posts(calls);
  assert.equal(sent.length, 2, 'the oversized file is never sent');
  assert.equal(sent[0].url, '/phases_v2/api/collections/c1/documents?filename=good.pdf');
  assert.equal(sent[0].body, good);
  assert.equal(sent[0].headers['Content-Type'], 'application/pdf');
  assert.equal($('col-upload-message').textContent, 'good.pdf: uploaded\nbad.pdf: failed - The file does not have a PDF header.\nhuge.pdf: failed - larger than 25 MiB');
  assert.equal($('col-upload-message').className, 'msg warn');
});

test('removing a member asks first, says nothing is deleted, and sends nothing when cancelled', async () => {
  const { $, a, section, parse, calls } = await mount({ 'DELETE /phases_v2/api/collections/c1/members/folder-1': { collection_id: 'c1' } });
  await section.show(parse('#/collections/c1'));
  const cancelled = a.removeMember(DETAIL.members[0], 'Folder A');
  assert.match($('confirm-title').textContent, /Remove "Folder A" from this collection/);
  assert.match($('confirm-body').children.map((p) => p.textContent).join(' '), /Nothing is deleted/);
  $('confirm-cancel').onclick();
  assert.equal(await cancelled, false);
  assert.equal(posts(calls).length, 0);
  const removed = a.removeMember(DETAIL.members[0], 'Folder A');
  await $('confirm-ok').onclick();
  assert.equal(await removed, true);
  assert.deepEqual(posts(calls).map((c) => [c.method, c.url]), [['DELETE', '/phases_v2/api/collections/c1/members/folder-1']]);
});

test('archiving asks first, and cancelling keeps the collection', async () => {
  const { $, a, section, parse, calls } = await mount({ 'DELETE /phases_v2/api/collections/c1': { archived: true } });
  await section.show(parse('#/collections/c1'));
  const cancelled = a.archive();
  assert.match($('confirm-title').textContent, /Archive "Research"/);
  assert.equal($('confirm-ok').className, 'danger-solid');
  $('confirm-cancel').onclick();
  assert.equal(await cancelled, false);
  assert.equal(posts(calls).length, 0);
  const confirmed = a.archive();
  await $('confirm-ok').onclick();
  assert.equal(await confirmed, true);
  assert.equal(posts(calls).filter((c) => c.method === 'DELETE').length, 1);
  assert.match($('col-message').textContent, /archived/);
});

test('run on this collection hands it to Runs and opens the new-run form', async () => {
  const { a, section, parse, runs, ctx } = await mount();
  await section.show(parse('#/collections/c1'));
  a.runOnCollection();
  assert.deepEqual(runs.collections, ['c1']);
  assert.equal(ctx.navigated.at(-1), '#/runs/new');
});

// ---- The create flow ----

const LIBRARY = {
  '/pubmed/api/papers': { papers: [
    { paper: { pmid: '7', title: 'Solitude paper', journal: 'J' }, artifacts: [{ content_sha256: SHA('c') }] },
    { paper: { pmid: '8', title: 'Not downloaded' }, artifacts: [] },
  ] },
  '/phases_v2/api/papers': { papers: [
    { paper_id: SHA('c'), file_name: 'same-as-pmid-7.pdf', path: 'pubmed/papers/7.pdf' },
    { paper_id: SHA('d'), file_name: 'mine.pdf', path: 'phases_v2/x/mine.pdf' },
  ] },
};

test('a new collection gathers papers in all four ways on one screen, then sends them with its name and uploads its PDFs', async () => {
  const { $, a, section, parse, calls, ctx } = await mount({
    ...LIBRARY,
    'POST /phases_v2/api/collections': { collection_id: 'c3', name: 'Mixed' },
    'POST /phases_v2/api/collections/c3/documents': { key: 'ok' },
    '/phases_v2/api/collections/c3': { collection_id: 'c3', name: 'Mixed', members: [], papers: [], paper_count: 0, status_counts: {} },
  });
  await section.show(parse('#/collections/new'));
  assert.equal($('col-save').textContent, 'Create collection');
  $('col-folder').value = 'phases_v2/a';
  await a.addFolder();
  $('col-pubmed').value = 'q1';
  await a.addPubmed();
  $('col-library-q').value = 'solitude';
  await a.findLibrary();
  const results = $('col-library-results').children;
  // Only downloaded PubMed papers, and an ingested PubMed PDF once, as its PubMed paper.
  assert.deepEqual(results.map((r) => r.innerHTML.match(/<span>([^<]+)/)[1]), ['Solitude paper', 'mine.pdf']);
  for (const row of results) await fire(row.children[0], 'click');
  $('col-upload-files').files = [{ name: 'own.pdf', size: 10 }, { name: 'huge.pdf', size: 26 * 1024 * 1024 }];
  await a.upload();
  assert.match($('col-upload-message').textContent, /1 PDF ready to upload when you create the collection\.\nhuge\.pdf: larger than 25 MiB/);
  assert.equal(posts(calls).length, 0, 'nothing is saved before the collection is created');
  assert.equal($('col-members').children.length, 5);

  $('col-name').value = ' Mixed ';
  await a.save();
  const [created, uploaded] = posts(calls);
  assert.deepEqual(created.body, {
    name: 'Mixed', description: '',
    members: [
      { folder: { prefix: 'phases_v2/a' } },
      { pubmed_query: { query_id: 'q1' } },
      { paper: { pmid: '7' } },
      { paper: { paper_id: SHA('d') } },
    ],
  });
  assert.equal(uploaded.url, '/phases_v2/api/collections/c3/documents?filename=own.pdf');
  assert.equal(ctx.replaced.at(-1), '#/collections/c3');
  assert.equal($('col-save').textContent, 'Save name and description');
  assert.equal(ctx.toasts.at(-1), 'Collection "Mixed" created.');
});

test('the create form drops a paper added twice, and a staged member can be taken off', async () => {
  const { $, a, section, parse } = await mount();
  await section.show(parse('#/collections/new'));
  $('col-folder').value = 'phases_v2/a';
  await a.addFolder();
  await a.addFolder();
  assert.equal($('col-members').children.length, 1);
  await fire($('col-members').children[0].lastElementChild.children[0], 'click');
  assert.match($('col-members').innerHTML, /Nothing added yet/);
});

test('when part of the library cannot be searched, the rest is still offered and the failure is said', async () => {
  const { $, a, section, parse } = await mount({ ...LIBRARY, '/pubmed/api/papers': response({ detail: 'PubMed is down.' }, { ok: false, status: 503 }) });
  await section.show(parse('#/collections/new'));
  await a.findLibrary();
  assert.equal($('col-library-results').children.length, 2);
  assert.match($('col-library-message').textContent, /could not be searched: PubMed is down\./);
});

test('coming back from the sidebar keeps an unsaved collection draft, and New always starts blank', async () => {
  const { $, a, section, parse, ctx } = await mount();
  await section.show(parse('#/collections/new'));
  $('col-name').value = 'Draft in progress';
  $('col-folder').value = 'phases_v2/a';
  await a.addFolder();
  await section.show(parse('#/collections'));
  assert.equal($('col-name').value, 'Draft in progress');
  assert.equal(ctx.replaced.at(-1), '#/collections/new');
  await section.show(parse('#/collections/new'));
  assert.equal($('col-name').value, '');
  assert.match($('col-members').innerHTML, /Nothing added yet/);
});

test('coming back to Collections lists one created elsewhere and keeps an open edit', async () => {
  const { $, section, parse } = await mount();
  await section.show(parse('#/collections/c1'));
  $('col-name').value = 'Edited but not saved';
  globalThis.fetch = routeFetch({
    '/phases_v2/api/locations': LOCATIONS, '/phases_v2/api/sources/pubmed': PUBMED, '/phases_v2/api/collections/c1': DETAIL,
    '/phases_v2/api/collections': { collections: [...SUMMARIES.collections, { collection_id: 'c9', name: 'Made in Library', member_count: 1 }] },
  });
  await section.show(parse('#/collections/c1'), { entering: true });
  assert.equal($('col-name').value, 'Edited but not saved');
  assert.ok($('col-list').children.some((b) => /Made in Library/.test(b.innerHTML)));
});

test('without PubMed in this deployment, the other ways of adding papers still work', async () => {
  const { $, section, parse } = await mount({ '/phases_v2/api/sources/pubmed': response({ detail: 'missing' }, { ok: false, status: 404 }) });
  await section.show(parse('#/collections/new'));
  assert.equal($('col-add-pubmed').disabled, true);
  assert.match($('col-pubmed').options[0].textContent, /No saved PubMed searches/);
  assert.equal($('col-folder').options.length, 2);
});

// ---- Storage folders ----

test('a new storage folder joins the collection being edited', async () => {
  const { $, a, section, parse, calls } = await mount({
    'POST /phases_v2/api/locations': { prefix: 'phases_v2/new', name: 'New one' },
    'POST /phases_v2/api/collections/c1/members': { collection_id: 'c1', name: 'Research' },
  });
  await section.show(parse('#/collections/c1'));
  $('col-location-name').value = 'New one';
  await a.createLocation();
  assert.deepEqual(posts(calls).map((c) => c.body), [{ name: 'New one' }, { members: [{ folder: { prefix: 'phases_v2/new' } }] }]);
});

test('PDFs can still be uploaded into any storage folder', async () => {
  const { $, a, section, parse, calls } = await mount({ 'POST /phases_v2/api/documents': { key: 'ok' } });
  await section.show(parse('#/collections/c1'));
  $('col-folder-upload-location').value = 'phases_v2/a';
  $('col-folder-upload-files').files = [{ name: 'good.pdf', size: 10 }];
  await a.uploadToFolder();
  assert.equal(posts(calls)[0].url, '/phases_v2/api/documents?location=phases_v2%2Fa&filename=good.pdf');
  $('col-folder-upload-files').files = [];
  await assert.rejects(a.uploadToFolder(), /Choose a storage folder and at least one PDF/);
});

// ---- Add to collection, from other sections ----

test('add to collection adds to the chosen collection, or creates a new one, and says where', async () => {
  const { $, section, calls, ctx } = await mount({
    'POST /phases_v2/api/collections/c1/members': { collection_id: 'c1', name: 'Research' },
    'POST /phases_v2/api/collections': { collection_id: 'c4', name: 'Fresh' },
  });
  const commands = [{ paper: { pmid: '7' } }];
  const first = section.addToCollection(commands, '"Solitude paper"');
  await settle();
  assert.equal($('col-pick-dialog').open, true);
  assert.match($('col-pick-body').textContent, /Add "Solitude paper" to one of your collections/);
  assert.deepEqual($('col-pick-select').options.map((o) => o.value), ['c1', 'c2', '__new__']);
  assert.equal($('col-pick-new').hidden, true);
  await $('col-pick-ok').onclick();
  assert.equal((await first).collection_id, 'c1');
  assert.equal(ctx.toasts.at(-1), 'Added to "Research".');

  const second = section.addToCollection(commands, '"Solitude paper"');
  await settle();
  assert.equal($('col-pick-select').value, 'c1', 'the last collection used is offered first');
  $('col-pick-select').value = '__new__';
  $('col-pick-select').onchange();
  assert.equal($('col-pick-new').hidden, false);
  await $('col-pick-ok').onclick();
  assert.equal($('col-pick-error').textContent, 'Name the new collection.');
  assert.equal($('col-pick-dialog').open, true);
  $('col-pick-name').value = 'Fresh';
  await $('col-pick-ok').onclick();
  assert.equal((await second).collection_id, 'c4');
  assert.deepEqual(posts(calls).map((c) => [c.url, c.body]), [
    ['/phases_v2/api/collections/c1/members', { members: commands }],
    ['/phases_v2/api/collections', { name: 'Fresh', members: commands }],
  ]);
});

test('cancelling add to collection sends nothing, and a refused addition keeps the dialog open', async () => {
  const { $, section, calls } = await mount({
    'POST /phases_v2/api/collections/c1/members': response({ detail: 'PMID 7 has no downloaded PDF yet.' }, { ok: false }),
  });
  const cancelled = section.addToCollection([{ paper: { pmid: '7' } }], 'this paper');
  await settle();
  $('col-pick-cancel').onclick();
  assert.equal(await cancelled, null);
  assert.equal(posts(calls).length, 0);
  const refused = section.addToCollection([{ paper: { pmid: '7' } }], 'this paper');
  await settle();
  await $('col-pick-ok').onclick();
  assert.equal($('col-pick-error').textContent, 'PMID 7 has no downloaded PDF yet.');
  assert.equal($('col-pick-dialog').open, true);
  $('col-pick-cancel').onclick();
  assert.equal(await refused, null);
});
