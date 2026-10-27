// Prompts: Try it, version history and the line diff.
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { context, install, load, response, routeFetch, settle } = require('./harness.cjs');

const PROMPTS = { prompts: [
  { prompt_id: 'effects-aaaaaaaa', name: 'Effects', template: 'A {chunk_text}', output_key: 'effects' },
  { prompt_id: 'effects-bbbbbbbb', name: 'Effects', template: 'B {chunk_text}', output_key: 'effects' },
] };
const VERSIONS = { name: 'Effects', versions: [
  {
    prompt_id: 'effects-bbbbbbbb', name: 'Effects', template: 'B {chunk_text}\nsecond line', output_key: 'effects', registered_at: '2026-02-01T00:00:00+00:00',
    declared: false, runs: [], run_count: 0, requests: [], request_count: 0, item_count: 0, by_model: {},
  },
  {
    prompt_id: 'effects-aaaaaaaa', name: 'Effects', template: 'A {chunk_text}\nsecond line', output_key: 'effects', registered_at: '2026-01-01T00:00:00+00:00',
    declared: false, run_count: 2, request_count: 4, item_count: 12,
    runs: [{ run_id: 'r1:effects-aaaaaaaa', request_id: 'r1' }],
    requests: [1, 2, 3, 4].map((n) => ({ request_id: `req-${n}`, requested_at: '2026-03-01T00:00:00+00:00' })),
    by_model: { 'openai/gpt-4.1-mini': { items: 12, succeeded: 5, failed: 1 } },
  },
] };
const MODELS = { models: [
  { model_id: 'openai/gpt-4.1-mini', display_name: 'GPT-4.1 mini', available: true },
  { model_id: 'google/x', display_name: 'Unavailable one', available: false },
] };
const CHUNKERS = { chunkers: [{ chunker_id: 'window_512_128', name: 'window', version: '1' }] };
const PAPERS = { papers: [{ paper_id: 'p1', file_name: 'Sleep.pdf', chunks: { window_512_128: 12 } }], total: 1 };
const CHUNKS = { chunks: Array.from({ length: 12 }, (_, seq) => ({ seq, chunk_id: `c${seq}`, preview: `Chunk ${seq} text` })) };
const REPORT = {
  prompt_id: 'effects-zzzzzzzz', model_id: 'openai/gpt-4.1-mini', baseline_prompt_id: 'effects-bbbbbbbb', elapsed_ms: 2100, timed_out: false,
  chunks: [
    { seq: 0, chunk_id: 'c0', text: 'First <chunk>', status: 'succeeded', items: ['<b>new</b> claim'], error: null, raw_output: null, elapsed_ms: 900,
      baseline: { status: 'succeeded', items: ['stored claim'], error: null } },
    { seq: 1, chunk_id: 'c1', text: 'Second', status: 'failed', items: [], error: 'response was not JSON', raw_output: '<script>x</script>', elapsed_ms: 1000,
      baseline: { status: 'not_run', items: [], error: null } },
  ],
};

async function mount(routes = {}) {
  const dom = install();
  const { href, parse } = await load('router.js');
  const runs = { prompts: [], selectPrompts(a, r = []) { runs.prompts.push([a, r]); } };
  const ctx = context({ href, sections: { runs } });
  const calls = [];
  globalThis.fetch = routeFetch({
    '/phases_v2/api/prompts': PROMPTS, '/phases_v2/api/prompts/versions': VERSIONS, '/phases_v2/api/models': MODELS,
    '/phases_v2/api/chunkers': CHUNKERS, '/phases_v2/api/papers': PAPERS, '/phases_v2/api/papers/p1/chunks': CHUNKS,
    'POST /phases_v2/api/prompts/try': REPORT, ...routes,
  }, calls);
  const { create } = await load('sections/prompts.js');
  const section = create(dom.$('section-prompts'), ctx);
  return { dom, ctx, section, parse, calls, runs, $: dom.$, a: section.actions };
}

async function opened(routes) {
  const mounted = await mount(routes);
  await mounted.section.show(mounted.parse('#/prompts/effects-bbbbbbbb'));
  await settle(10);
  return mounted;
}

const tries = (calls) => calls.filter((c) => c.method === 'POST' && c.url.endsWith('/prompts/try'));

// ---- The line diff ----

test('the diff aligns unchanged lines and marks what was added and removed', async () => {
  install();
  const { lineDiff, diffSummary } = await load('diff.js');
  const ops = lineDiff('keep\nold\nshared\nend', 'keep\nnew\nshared\nmore\nend');
  assert.deepEqual(ops.map((op) => `${op.type}:${op.text}`), ['same:keep', 'del:old', 'add:new', 'same:shared', 'add:more', 'same:end']);
  assert.equal(diffSummary(ops), '2 lines added, 1 line removed.');
  assert.equal(diffSummary(lineDiff('a\r\nb', 'a\nb')), 'The two texts are identical.');
});

test('a very large difference is shown removed then added instead of aligned', async () => {
  install();
  const { lineDiff } = await load('diff.js');
  const before = Array.from({ length: 3000 }, (_, i) => `a${i}`).join('\n');
  const after = Array.from({ length: 3000 }, (_, i) => `b${i}`).join('\n');
  const ops = lineDiff(before, after);
  assert.equal(ops.length, 6000);
  assert.equal(ops[0].type, 'del');
  assert.equal(ops.at(-1).type, 'add');
});

test('diff lines are escaped and say what changed for screen readers', async () => {
  install();
  const { lineDiff, diffHtml } = await load('diff.js');
  const html = diffHtml(lineDiff('<a>', '<b>'));
  assert.match(html, /diff-del.*removed: <\/span>&lt;a&gt;/);
  assert.match(html, /diff-add.*added: <\/span>&lt;b&gt;/);
  assert.doesNotMatch(html, /<a>|<b>/);
});

// ---- Rendering a try ----

test('a try body names either chunk positions or the first N, and the baseline when chosen', async () => {
  install();
  const { tryBody } = await load('sections/prompt_try.js');
  const common = { source: { prompt_id: 'p' }, modelId: 'm', paperId: 'x', chunkerId: 'c' };
  assert.deepEqual(tryBody({ ...common, seqs: [3, 5], baselineId: 'old' }), { prompt_id: 'p', model_id: 'm', paper_id: 'x', chunker_id: 'c', seqs: [3, 5], baseline_prompt_id: 'old' });
  assert.deepEqual(tryBody({ ...common, first: 4 }), { prompt_id: 'p', model_id: 'm', paper_id: 'x', chunker_id: 'c', first: 4 });
});

test('items show claims as escaped text and relations as subject, direction and target', async () => {
  install();
  const { renderItems } = await load('sections/prompt_try.js');
  const relation = { subject_process: 'isolation', subject_participant: 'older adults', target_process: '<sleep>', direction: 'decreases', evidence_text: 'reduced sleep' };
  assert.match(renderItems(['<i>x</i>']), /<li>&lt;i&gt;x&lt;\/i&gt;<\/li>/);
  const html = renderItems([relation]);
  assert.match(html, /<strong>isolation<\/strong> <span class="relation-edge decreases">decreases<\/span> <strong>&lt;sleep&gt;<\/strong>/);
  assert.match(html, /Participant: older adults/);
  assert.match(html, /reduced sleep/);
  assert.match(renderItems([{ other: '<x>' }]), /json-payload[^]*&lt;x&gt;/);
  assert.match(renderItems([]), /No items/);
});

test('a chunk shows its error and raw output, escaped, and the baseline beside it', async () => {
  install();
  const { renderChunk } = await load('sections/prompt_try.js');
  const html = renderChunk(REPORT.chunks[1], { draftLabel: 'Text in the editor, now', baselineLabel: 'Version bbbbbbbb, stored', modelLabel: 'GPT-4.1 mini' });
  assert.match(html, /Chunk 1/);
  assert.match(html, /response was not JSON/);
  assert.match(html, /Raw output[^]*&lt;script&gt;x&lt;\/script&gt;/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /class="compare"/);
  assert.match(html, /Not run yet with GPT-4.1 mini/);
  const alone = renderChunk(REPORT.chunks[0], { draftLabel: 'Draft' });
  assert.doesNotMatch(alone, /class="compare"/);
  assert.match(alone, /&lt;b&gt;new&lt;\/b&gt; claim/);
});

// ---- The Try it panel ----

test('opening a prompt loads models, chunkers, papers and chunks, and offers its versions as the baseline', async () => {
  const { $ } = await opened();
  assert.deepEqual($('pr-try-model').options.map((o) => [o.value, o.disabled]), [['openai/gpt-4.1-mini', false], ['google/x', true]]);
  assert.equal($('pr-try-paper').value, 'p1');
  assert.match($('pr-try-paper').options[0].textContent, /Sleep.pdf \(12 chunks\)/);
  assert.equal($('pr-try-chunks').options.length, 12);
  assert.match($('pr-try-chunks').options[3].textContent, /^3 · Chunk 3 text/);
  assert.deepEqual($('pr-try-baseline').options.map((o) => o.value), ['', 'effects-bbbbbbbb', 'effects-aaaaaaaa']);
  assert.equal($('pr-try-baseline').value, 'effects-bbbbbbbb');
});

test('papers are searched with the chosen chunker, and an empty result says what to do', async () => {
  const { $, section, calls } = await opened({ '/phases_v2/api/papers': { papers: [], total: 0 } });
  $('pr-try-paper-q').value = 'sleep';
  await section.tryPanel.searchPapers();
  const url = calls.filter((c) => c.url.includes('/papers?')).at(-1).url;
  assert.match(url, /q=sleep/);
  assert.match(url, /chunker_id=window_512_128/);
  assert.match($('pr-try-papers-hint').textContent, /No ingested paper is chunked with this chunker/);
});

test('an unedited saved version is tried by its id, beside its stored results', async () => {
  const { $, a, calls } = await opened();
  $('pr-try-chunks').options[0].selected = true;
  $('pr-try-chunks').options[1].selected = true;
  await a.tryIt();
  assert.deepEqual(tries(calls)[0].body, {
    prompt_id: 'effects-bbbbbbbb', model_id: 'openai/gpt-4.1-mini', paper_id: 'p1', chunker_id: 'window_512_128', seqs: [0, 1], baseline_prompt_id: 'effects-bbbbbbbb',
  });
  const html = $('pr-try-results').innerHTML;
  assert.match(html, /Version bbbbbbbb, now/);
  assert.match(html, /Version bbbbbbbb, stored/);
  assert.match(html, /stored claim/);
  assert.match($('pr-try-message').textContent, /Tried on 2 chunks in 2.1 s. 1 chunk failed/);
  assert.equal($('pr-try-message').className, 'msg warn');
});

test('an edited prompt is tried as a draft, on the first N chunks when none is picked', async () => {
  const { $, a, calls } = await opened();
  $('pr-template').value = 'Changed {chunk_text}';
  $('pr-try-first').value = '4';
  $('pr-try-baseline').value = 'effects-aaaaaaaa';
  await a.tryIt();
  const body = tries(calls)[0].body;
  assert.deepEqual(body.draft, { name: 'Effects', template: 'Changed {chunk_text}', output_key: 'effects' });
  assert.equal(body.prompt_id, undefined);
  assert.equal(body.first, 4);
  assert.equal(body.seqs, undefined);
  assert.equal(body.baseline_prompt_id, 'effects-aaaaaaaa');
  assert.match($('pr-try-results').innerHTML, /Text in the editor, now/);
});

test('the Try button is disabled while a try runs, and a second click sends nothing', async () => {
  let finish;
  const { $, a, calls } = await opened({ 'POST /phases_v2/api/prompts/try': () => new Promise((resolve) => { finish = resolve; }) });
  const first = a.tryIt();
  await settle(2);
  assert.equal($('pr-try-run').disabled, true);
  assert.equal($('pr-try-run').textContent, 'Trying…');
  assert.match($('pr-try-message').textContent, /Trying on 3 chunks with GPT-4.1 mini/);
  await a.tryIt();
  assert.equal(tries(calls).length, 1);
  finish(response(REPORT));
  await first;
  assert.equal($('pr-try-run').disabled, false);
  assert.equal($('pr-try-run').textContent, 'Try it');
});

test('a refused try shows the reason and the button comes back', async () => {
  const refused = response({ detail: 'This paper has not been chunked with window_512_128.' }, { ok: false, status: 422 });
  const { $, a } = await opened({ 'POST /phases_v2/api/prompts/try': refused });
  await a.tryIt();
  assert.match($('pr-try-message').textContent, /The try failed: This paper has not been chunked/);
  assert.equal($('pr-try-message').className, 'msg bad');
  assert.equal($('pr-try-run').disabled, false);
});

test('a try that never answers is stopped with a clear message', async () => {
  const abort = () => { const error = new Error('aborted'); error.name = 'AbortError'; throw error; };
  const { $, a } = await opened({ 'POST /phases_v2/api/prompts/try': abort });
  await a.tryIt();
  assert.match($('pr-try-message').textContent, /No answer after 2 minutes, so the try was stopped/);
  assert.equal($('pr-try-run').disabled, false);
});

test('chunks the server reports as timed out are flagged in the summary', async () => {
  const late = { ...REPORT, timed_out: true, chunks: [{ ...REPORT.chunks[0], status: 'timed_out', error: 'No answer within 90 seconds.' }] };
  const { $, a } = await opened({ 'POST /phases_v2/api/prompts/try': late });
  await a.tryIt();
  assert.match($('pr-try-message').textContent, /1 chunk did not answer in time/);
  assert.match($('pr-try-results').innerHTML, /Timed out/);
});

test('more than ten chunks, a missing paper or a missing {chunk_text} are refused before sending', async () => {
  const { $, a, calls } = await opened();
  for (const option of $('pr-try-chunks').options.slice(0, 11)) option.selected = true;
  await a.tryIt();
  assert.match($('pr-try-message').textContent, /11 chunks are picked; try at most 10/);
  for (const option of $('pr-try-chunks').options) option.selected = false;
  $('pr-template').value = 'No placeholder';
  await a.tryIt();
  assert.match($('pr-try-message').textContent, /must contain \{chunk_text\}/);
  $('pr-template').value = 'B {chunk_text}';
  $('pr-try-paper').value = '';
  await a.tryIt();
  assert.match($('pr-try-message').textContent, /Choose an ingested paper/);
  assert.equal(tries(calls).length, 0);
});

test('saving from the Try panel keeps comparing with the version it was edited from', async () => {
  const saved = { prompt_id: 'effects-cccccccc', name: 'Effects', template: 'C {chunk_text}', output_key: 'effects' };
  const withSaved = { prompts: [...PROMPTS.prompts, saved] };
  const { $, a, calls, runs, dom } = await opened();
  globalThis.fetch = routeFetch({
    'POST /phases_v2/api/prompts': saved, '/phases_v2/api/prompts': withSaved,
    '/phases_v2/api/prompts/versions': { name: 'Effects', versions: [{ ...VERSIONS.versions[0], prompt_id: 'effects-cccccccc', template: 'C {chunk_text}' }, ...VERSIONS.versions] },
  }, calls);
  $('pr-template').value = 'C {chunk_text}';
  dom.$('pr-form').listeners.input[0]();
  assert.equal($('pr-try-use').disabled, true);
  await $('pr-try-save').listeners.click[0]();
  await settle(10);
  assert.equal(calls.filter((c) => c.method === 'POST' && c.url.endsWith('/prompts')).length, 1);
  assert.deepEqual(runs.prompts.at(-1), [['effects-cccccccc'], ['effects-bbbbbbbb']]);
  assert.equal($('pr-try-baseline').value, 'effects-bbbbbbbb');
  assert.equal($('pr-try-use').disabled, false);
});

// ---- Versions ----

test('versions list when each was saved, the runs that used it and its items', async () => {
  const { $ } = await opened();
  const rows = $('pr-ver-rows').children;
  assert.equal(rows.length, 2);
  assert.match(rows[0].innerHTML, /bbbbbbbb<\/code> <span class="pill ok">In the editor/);
  assert.match(rows[1].innerHTML, /2 extraction runs<small>4 run requests: <a href="#\/runs\/req-1" title=/);
  assert.match(rows[1].innerHTML, /and 1 more/);
  assert.match(rows[1].innerHTML, /12<small>openai\/gpt-4.1-mini: 12 items from 5 chunks, 1 failed/);
  // The version in the editor has no Open button; the others do.
  assert.deepEqual(rows[0].lastElementChild.children.map((b) => b.textContent), ['Use in new run', 'Compare with editor']);
  assert.deepEqual(rows[1].lastElementChild.children.map((b) => b.textContent), ['Open', 'Use in new run', 'Compare with editor']);
});

test('a version can be opened in the editor or used in a new run', async () => {
  const { $, ctx, runs } = await opened();
  const [open, use] = $('pr-ver-rows').children[1].lastElementChild.children;
  open.listeners.click[0]();
  assert.equal(ctx.navigated.at(-1), '#/prompts/effects-aaaaaaaa');
  use.listeners.click[0]();
  assert.deepEqual(runs.prompts.at(-1), [['effects-aaaaaaaa'], []]);
  assert.equal(ctx.navigated.at(-1), '#/runs/new');
});

test('the comparison starts with the previous version against the editor, and any two can be compared', async () => {
  const { $, section } = await opened();
  assert.equal($('pr-ver-a').value, 'effects-aaaaaaaa');
  assert.equal($('pr-ver-b').value, 'draft');
  assert.match($('pr-ver-diff').innerHTML, /diff-del[^]*A \{chunk_text\}[^]*diff-add[^]*B \{chunk_text\}/);
  $('pr-ver-a').value = 'effects-aaaaaaaa';
  $('pr-ver-b').value = 'effects-bbbbbbbb';
  section.versions.compare();
  assert.equal($('pr-ver-summary').textContent, '1 line added, 1 line removed.');
  assert.match($('pr-ver-diff').innerHTML, /second line/);
});

test('a new prompt has no history yet and compares nothing', async () => {
  const { $, section, parse } = await mount();
  await section.show(parse('#/prompts/new'));
  await settle(10);
  assert.match($('pr-ver-rows').innerHTML, /Save this prompt to start its history/);
  assert.deepEqual($('pr-try-baseline').options.map((o) => o.value), ['']);
});

test('a comparison with the editor follows what is typed', async () => {
  const { $ } = await opened();
  $('pr-template').value = 'A {chunk_text}\nsecond line\nthird line';
  $('pr-form').listeners.input[0]();
  assert.equal($('pr-ver-summary').textContent, '1 line added, 0 lines removed.');
});
