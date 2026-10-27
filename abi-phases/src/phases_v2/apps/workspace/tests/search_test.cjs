// Search: everything the phases_v2 Reverse Search app did.
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { context, install, load, response, routeFetch, settle } = require('./harness.cjs');

const relation = {
  subject_process: 'Practicing meditation', subject_participant: 'Meditation practitioner',
  target_process: 'Experiencing stress', direction: 'decreases', evidence_text: 'Meditation decreased stress.',
};
const page = (extra = {}) => ({ query: '', mode: 'semantic', hits: [], total: 0, next_offset: null, snapshot: 7, ...extra });

async function search(routes = {}) {
  const dom = install();
  const { href, parse } = await load('router.js');
  const ctx = context({ href });
  const calls = [];
  globalThis.fetch = routeFetch({
    '/phases_v2/api/search/prompts': { prompts: ['Effects', 'Causes'] },
    '/phases_v2/api/search/models': { models: ['model-a'] },
    '/phases_v2/api/search/paths': { paths: ['phases_v2', 'phases_v2/a'] },
    '/phases_v2/api/models': { models: [{ model_id: 'model-a', display_name: 'Model A' }] },
    ...routes,
  }, calls);
  const { create } = await load('sections/search.js');
  const section = create(dom.$('section-search'), ctx);
  return { dom, ctx, section, parse, calls, $: dom.$, a: section.actions, render: await load('sections/search_render.js') };
}

const lastSearch = (calls) => new URL(calls.filter((c) => /\/(semantic|keyword|effects)\?/.test(c.url)).at(-1).url, 'http://local');

// ---- Rendering ----

test('single relations, arrays and extraction envelopes render typed directed graphs', async () => {
  const { render } = await search();
  for (const payload of [relation, [relation], { relations: [relation, relation] }]) {
    const rendered = render.renderExtraction(JSON.stringify(payload), '');
    for (const text of [/Independent continuant/, /From \/ subject/, /To \/ target/, /Meditation practitioner/, /Practicing meditation/, /Experiencing stress/, /Meditation decreased stress/, /Decreases/]) {
      assert.match(rendered, text);
    }
  }
});

test('all three directions are explicit without relying on colour', async () => {
  const { render } = await search();
  for (const [direction, label] of [['increases', 'Increases'], ['decreases', 'Decreases'], ['no-effect', 'Neutral (no effect)']]) {
    const rendered = render.renderExtraction(JSON.stringify({ ...relation, direction }), '');
    assert.ok(rendered.includes(label));
    assert.ok(rendered.includes(`relation-edge ${direction}`));
  }
});

test('unknown, incomplete and mixed payloads keep their full JSON instead of inventing a graph', async () => {
  const { render } = await search();
  for (const payload of [null, [], {}, { other: 'value' }, { ...relation, direction: 'unknown' },
    { ...relation, subject_process: '' }, { relations: [relation, { other: 'value' }] }]) {
    const rendered = render.renderExtraction(JSON.stringify(payload), '');
    assert.match(rendered, /json-payload/);
    assert.doesNotMatch(rendered, /relation-flow/);
  }
  assert.match(render.renderExtraction('{broken JSON', ''), /\{broken JSON/);
  assert.match(render.renderExtraction('Ordinary claim', ''), /Ordinary claim/);
});

test('untrusted node text and evidence stay escaped in keyword mode', async () => {
  const { render } = await search();
  const malicious = '<img src=x onerror=alert(1)> & mark';
  const rendered = render.renderExtraction(JSON.stringify({ ...relation, subject_process: malicious, evidence_text: malicious }), 'mark img amp lt', 'keyword');
  assert.doesNotMatch(rendered, /<img/);
  assert.match(rendered, /&lt;<mark>img<\/mark>/);
  assert.match(rendered, /&amp; <mark>mark<\/mark>/);
});

test('quoted words highlight whole words and quoted phrases stay together', async () => {
  const { render } = await search();
  const { highlight } = render;
  assert.equal(highlight('like likely dislike LIKE élike', '"like"', 'keyword'), '<mark>like</mark> likely dislike <mark>LIKE</mark> élike');
  assert.equal(highlight('being alone; being happily alone; being\nalone stress', '"being alone" stress', 'keyword'),
    '<mark>being alone</mark>; being happily alone; <mark>being\nalone</mark> <mark>stress</mark>');
  assert.equal(highlight('100% 1000', '"100%"', 'keyword'), '<mark>100%</mark> 1000');
  assert.equal(highlight('around (x+y) around xxy', '"around (x+y)"', 'keyword'), '<mark>around (x+y)</mark> around xxy');
  assert.equal(highlight('around surround', '“around”', 'keyword'), '<mark>around</mark> surround');
  assert.equal(highlight('likely', 'like', 'keyword'), '<mark>like</mark>ly');
  assert.equal(highlight('<b>', 'b', 'semantic'), '&lt;b&gt;');
});

test('source chunk comes before the stored prompt, followed by the original JSON', async () => {
  const { $, a } = await search();
  a.renderHits({ query: '', hits: [{ item_id: 'id', extracted_text: JSON.stringify(relation), chunk_text: 'Exact source chunk', prompt_template: 'Stored prompt {chunk_text}', prompt_id: 'p-1', prompt_name: 'Effects', model_id: 'model-a', paper_id: 'paper-id', paper_name: 'a.pdf' }] });
  const rendered = $('sr-results').children[0].innerHTML;
  assert.ok(rendered.indexOf('Show source chunk') < rendered.indexOf('View extraction prompt'));
  assert.ok(rendered.indexOf('View extraction prompt') < rendered.indexOf('Show original JSON'));
  assert.match(rendered, /Exact source chunk/);
  assert.match(rendered, /Stored prompt \{chunk_text\}/);
  assert.match(rendered, /Download paper/);
  assert.match(rendered, /href="#\/prompts\/p-1"/, 'the stored prompt links to its version');
});

test('model badges use the model name when it is known', async () => {
  const { $, a, section, parse } = await search();
  await section.show(parse('#/search'));
  await settle();
  a.renderHits({ query: '', hits: [{ item_id: 'x', extracted_text: 'Claim', model_id: 'model-a' }, { item_id: 'y', extracted_text: 'Claim', model_id: 'unknown-model' }] });
  assert.match($('sr-results').children[0].innerHTML, /Model: Model A/);
  assert.match($('sr-results').children[1].innerHTML, /Model: unknown-model/);
  assert.deepEqual($('sr-model-facets').children.slice(1).map((b) => b.textContent), ['All models', 'Model A']);
});

test('failed downloads explain availability and restore the button', async () => {
  const { a } = await search();
  let requested;
  globalThis.fetch = async (url) => { requested = url; return { ok: false, status: 404 }; };
  const button = {};
  const status = {};
  await a.downloadPaper({ item_id: 'id & /?' }, button, status);
  assert.equal(new URL(requested, 'http://localhost').searchParams.get('item_id'), 'id & /?');
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, 'Download paper');
  assert.match(status.textContent, /Source PDF is unavailable/);
  globalThis.fetch = async () => ({ ok: false, status: 500, text: async () => '{}' });
  await a.downloadPaper({ item_id: 'id' }, button, status);
  assert.match(status.textContent, /Download failed \(500\)/);
});

test('the keyword quote hint shows only in keyword mode', async () => {
  const { $, a } = await search();
  a.setMode('keyword');
  assert.equal($('sr-keyword-help').hidden, false);
  assert.equal($('sr-mode-keyword').attributes['aria-pressed'], 'true');
  assert.equal($('sr-size').value, 25);
  a.setMode('semantic');
  assert.equal($('sr-keyword-help').hidden, true);
  assert.equal($('sr-threshold-wrap').hidden, false);
  assert.equal($('sr-size').value, 10);
});

// ---- Searching ----

test('effects search can browse every target and submits field filters', async () => {
  const { $, a, calls } = await search({ '/search/effects': page({ mode: 'effects' }) });
  a.setMode('effects');
  assert.equal($('sr-effects').hidden, false);
  assert.equal($('sr-q-label').textContent, 'Target process (optional)');
  $('sr-direction').value = 'increases';
  $('sr-subject').value = 'solitude';
  $('sr-participant').value = 'adults';
  await a.search();
  const requested = lastSearch(calls);
  assert.match(requested.pathname, /effects$/);
  assert.equal(requested.searchParams.get('q'), '');
  assert.equal(requested.searchParams.get('direction'), 'increases');
  assert.equal(requested.searchParams.get('subject'), 'solitude');
  assert.equal(requested.searchParams.get('participant'), 'adults');
  assert.match($('sr-status').textContent, /Showing 0 of 0/);
  a.setMode('keyword');
  assert.equal($('sr-effects').hidden, true);
});

test('an empty query outside effects mode asks for words instead of searching', async () => {
  const { $, a, calls } = await search();
  $('sr-q').value = '  ';
  await a.search();
  assert.equal(calls.length, 0);
  assert.match($('sr-status').textContent, /Type what you are looking for/);
});

test('semantic searches send prompts, models, folders, batch size and minimum score, and record them in the URL', async () => {
  const { $, a, section, calls, ctx, parse } = await search({ '/search/semantic': page({ total: 1, hits: [{ item_id: 'i1', extracted_text: 'Claim' }] }) });
  await section.show(parse('#/search'));
  $('sr-q').value = 'stress';
  section.state.selected.add('Effects');
  section.state.selectedModels.add('model-a');
  section.state.selectedPaths.add('phases_v2/a');
  $('sr-threshold').value = '0.4';
  await a.search();
  const sent = lastSearch(calls).searchParams;
  assert.equal(sent.get('q'), 'stress');
  assert.deepEqual(sent.getAll('prompt'), ['Effects']);
  assert.deepEqual(sent.getAll('model'), ['model-a']);
  assert.deepEqual(sent.getAll('path'), ['phases_v2/a']);
  assert.equal(sent.get('k'), '10');
  assert.equal(sent.get('score_threshold'), '0.4');
  assert.equal(sent.get('offset'), '0');
  assert.equal(ctx.replaced.at(-1), '#/search?q=stress&prompt=Effects&model=model-a&path=phases_v2%2Fa&k=10&score_threshold=0.4&mode=semantic');
});

test('a search link fills the form and runs the search; reloading the same link does not repeat it', async () => {
  const { $, section, calls, parse } = await search({ '/search/keyword': page({ mode: 'keyword', total: 0 }) });
  const route = parse('#/search?q=%22being+alone%22&mode=keyword&prompt=Causes&limit=5');
  await section.show(route);
  assert.equal($('sr-q').value, '"being alone"');
  assert.equal($('sr-mode-keyword').attributes['aria-pressed'], 'true');
  assert.equal($('sr-size').value, '5');
  assert.ok(section.state.selected.has('Causes'));
  assert.equal($('sr-filters').open, true);
  const sent = lastSearch(calls).searchParams;
  assert.equal(sent.get('q'), '"being alone"');
  assert.equal(sent.get('limit'), '5');
  assert.deepEqual(sent.getAll('prompt'), ['Causes']);
  const searches = calls.filter((c) => c.url.includes('/keyword?')).length;
  await section.show(route);
  assert.equal(calls.filter((c) => c.url.includes('/keyword?')).length, searches);
});

test('pages come from one snapshot, and distinct relations from one extraction stay visible across pages', async () => {
  const hit = { item_id: 'same-item', extracted_text: JSON.stringify(relation) };
  const { $, a, calls } = await search({
    '/search/effects': (url) => (new URL(url, 'http://local').searchParams.get('offset') === '0'
      ? page({ mode: 'effects', total: 3, next_offset: 1, snapshot: 42, hits: [{ ...hit, relation_id: 'r1' }] })
      : page({ mode: 'effects', total: 3, next_offset: null, snapshot: 42, hits: [{ ...hit, relation_id: 'r1' }, { ...hit, relation_id: 'r2' }] })),
  });
  a.setMode('effects');
  await a.search();
  assert.equal($('sr-load-more').hidden, false);
  await a.loadPage(true);
  const second = lastSearch(calls).searchParams;
  assert.equal(second.get('offset'), '1');
  assert.equal(second.get('snapshot'), '42');
  assert.equal($('sr-results').children.length, 2);
  assert.equal($('sr-load-more').hidden, true);
  assert.match($('sr-status').textContent, /Showing 2 of 3/);
});

test('a failed next batch keeps the results and offers Load more again', async () => {
  const { $, a } = await search({ '/search/semantic': page({ total: 2, next_offset: 1, hits: [{ item_id: 'a', extracted_text: 'One' }] }) });
  $('sr-q').value = 'x';
  await a.search();
  globalThis.fetch = async () => response({ detail: 'Search storage is unavailable. Please retry.' }, { ok: false, status: 503 });
  await a.loadPage(true);
  assert.equal($('sr-results').children.length, 1);
  assert.match($('sr-status').textContent, /Could not load the next batch: Search storage is unavailable/);
  assert.equal($('sr-load-more').hidden, false);
  assert.equal($('sr-load-more').disabled, false);
});

test('no matches explains what to try next and disables export', async () => {
  const { $, a } = await search({ '/search/semantic': page({ query: 'zzz' }) });
  $('sr-q').value = 'zzz';
  await a.search();
  assert.match($('sr-results').innerHTML, /No matches for “zzz”\. Try other words/);
  assert.equal($('sr-export').disabled, true);
});

test('export downloads every match of the submitted search, without paging parameters', async () => {
  const { $, a, calls } = await search({
    '/search/semantic': page({ total: 4, hits: [{ item_id: 'a', extracted_text: 'One' }] }),
    '/search/export': () => response('query,mode\n', { type: 'text/csv; charset=utf-8' }),
  });
  const saved = [];
  globalThis.URL.createObjectURL = () => 'blob:x';
  globalThis.URL.revokeObjectURL = () => {};
  globalThis.document.createElement = ((original) => (tag) => { const el = original(tag); if (tag === 'a') saved.push(el); return el; })(globalThis.document.createElement);
  $('sr-q').value = 'stress';
  await a.search();
  $('sr-q').value = 'unsubmitted edit';
  assert.equal($('sr-export').disabled, false);
  await a.exportCsv();
  const exported = new URL(calls.at(-1).url, 'http://local').searchParams;
  assert.equal(exported.get('q'), 'stress');
  assert.equal(exported.get('mode'), 'semantic');
  assert.equal(exported.get('snapshot'), '7');
  assert.equal(exported.has('k'), false);
  assert.equal(exported.has('offset'), false);
  assert.match(saved.at(-1).download, /^healthyphases-search-\d{4}-\d{2}-\d{2}\.csv$/);
  assert.equal(saved.at(-1).clicked, true);
  assert.match($('sr-export-status').textContent, /CSV downloaded/);
});

test('a failed export says why and lets the user try again', async () => {
  const { $, a } = await search({
    '/search/semantic': page({ total: 4, hits: [{ item_id: 'a', extracted_text: 'One' }] }),
    '/search/export': () => response({ detail: 'Search storage is unavailable. Please retry.' }, { ok: false, status: 503 }),
  });
  $('sr-q').value = 'stress';
  await a.search();
  await a.exportCsv();
  assert.match($('sr-export-status').textContent, /Export failed: Search storage is unavailable/);
  assert.equal($('sr-export').disabled, false);
});

test('refreshing re-reads the filter options without repeating the search', async () => {
  const { section, calls } = await search({ '/search/semantic': page() });
  await section.refresh();
  assert.equal(calls.some((c) => /\/(semantic|keyword|effects)\?/.test(c.url)), false);
  assert.ok(calls.some((c) => c.url.endsWith('/search/paths')));
});
