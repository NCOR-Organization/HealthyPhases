// Results: the papers table and one paper's page, with its comparison.
const assert = require('node:assert/strict');
const { test } = require('node:test');
const { context, fire, install, load, response, routeFetch, settle } = require('./harness.cjs');

const SHA = (c) => c.repeat(64);
const V1 = 'claims_1111111aaaaa';
const V2 = 'claims_2222222bbbbb';
const EFFECTS = 'effects_3333333ccccc';
const RELATION = {
  relation_id: 'rel-1', subject_process: 'spending time alone', subject_participant: 'older adults',
  target_process: 'stress', direction: 'decreases', evidence_text: 'Time alone lowered stress.',
};

const PAPERS = {
  total: 2, limit: 50, offset: 0,
  papers: [
    {
      paper_id: SHA('a'), title: 'Solitude <b>and</b> stress', file_name: 'a.pdf', pmid: '111', source: 'pubmed',
      path: 'pubmed/papers/PMC1/a.pdf', discovered_at: '2026-01-01T00:00:00', chunks: { window: 3 },
      extractions: { succeeded: 4, failed: 1 }, items: { claims: 4, effects: 1 }, item_count: 5,
    },
    {
      paper_id: SHA('b'), title: 'Being alone.pdf', file_name: 'Being alone.pdf', pmid: null, source: 'file',
      path: 'phases_v2/solitude/Being alone.pdf', discovered_at: '2026-02-01T00:00:00', chunks: { window: 2 },
      extractions: { succeeded: 1, failed: 0 }, items: {}, item_count: 0,
    },
  ],
};

const group = (promptId, name, model, extra = {}) => ({
  prompt_id: promptId, prompt_name: name, template: `${name} {chunk_text}`, model_id: model,
  prompt_registered_at: '2026-01-01T00:00:00', chunker_ids: ['window'], succeeded: 1, failed: 0,
  item_count: 0, relation_count: 0, run_ids: [], request_ids: [], last_completed_at: '2026-04-01T00:00:00',
  items: [], failures: [], ...extra,
});
const item = (id, chunk, text, extra = {}) => ({ item_id: id, extraction_id: `e-${id}`, chunk_id: chunk, chunk_seq: null, seq: 0, text, relations: [], ...extra });

const RESULTS = [
  group(V2, 'claims', 'model-a', { item_count: 1, items: [item('i3', 'c0', 'Solitude lowers stress')] }),
  group(V1, 'claims', 'model-a', {
    item_count: 2, failed: 1, request_ids: ['r-pubmed-1234'],
    items: [item('i1', 'c0', 'Solitude lowers stress'), item('i2', 'c0', 'Older adults <i>seek</i> time alone')],
    failures: [{ extraction_id: 'e-f', chunk_id: 'c1', seq: 1, status: 'failed', error: 'Not <valid> JSON', raw_excerpt: '{not json' }],
  }),
  group(EFFECTS, 'effects', 'model-a', { item_count: 1, relation_count: 1, items: [item('i4', 'c2', '{"relations": []}', { relations: [RELATION] })] }),
];
const DETAIL = {
  paper: {
    paper_id: SHA('a'), title: 'Solitude <b>and</b> stress', file_name: 'a.pdf', path: 'pubmed/papers/PMC1/a.pdf',
    discovered_at: '2026-01-01T00:00:00', ingested: true, source: 'pubmed', pmid: '111', paths: [],
  },
  pubmed: { pmid: '111', pmcid: 'PMC1', doi: '10.1000/solitude', title: 'Solitude <b>and</b> stress', journal: 'Ageing', publication_date: '2024 Mar', authors: ['Ada <Byron>', 'Alan Turing'] },
  openalex: {
    enrichment: { status: 'enriched', work_id: 'W1', citation_count: 42, topics: ['Ageing'], institutions: ['Buffalo'] },
    work: { work_id: 'W1', citation_count: 42, is_oa: true, oa_status: 'gold', topics: [{ name: 'Ageing' }], locations: [{ source_name: 'Repository', landing_page_url: 'https://example.org/a' }, { source_name: 'Bad', landing_page_url: 'javascript:alert(1)' }] },
  },
  chunkers: [{ chunker_id: 'window', chunks: 3 }],
  ran: RESULTS.map(({ items, failures, template, ...summary }) => summary),
  requests: [{ request_id: 'r-pubmed-1234', status: 'succeeded', model_id: 'model-a', requested_by: 'member@example.org', requested_at: '2026-04-01T00:00:00' }],
  results: RESULTS,
  chunks: {
    c0: { chunk_id: 'c0', seq: 0, chunker_id: 'window', text: 'First chunk <text>' },
    c1: { chunk_id: 'c1', seq: 1, chunker_id: 'window', text: 'Second chunk' },
    c2: { chunk_id: 'c2', seq: 2, chunker_id: 'window', text: 'Third chunk' },
  },
};

async function mount(routes = {}) {
  const dom = install();
  const { href, parse } = await load('router.js');
  const ctx = context({ href });
  const calls = [];
  globalThis.fetch = routeFetch({
    '/phases_v2/api/collections': { collections: [{ collection_id: 'c1', name: 'Research' }] },
    '/phases_v2/api/prompts': { prompts: [{ prompt_id: V1, name: 'claims' }, { prompt_id: V2, name: 'claims' }, { prompt_id: EFFECTS, name: 'effects' }] },
    '/phases_v2/api/models': { models: [{ model_id: 'model-a', display_name: 'Model A' }, { model_id: 'model-b', display_name: 'Model B' }] },
    '/phases_v2/api/papers?': PAPERS,
    [`/phases_v2/api/papers/${SHA('a')}`]: DETAIL,
    ...routes,
  }, calls);
  const { create } = await load('sections/results.js');
  const section = create(dom.$('section-results'), ctx);
  return { dom, ctx, section, parse, calls, $: dom.$, a: section.actions, view: await load('sections/paper_view.js') };
}

const lastList = (calls) => new URL(calls.filter((c) => c.url.includes('/phases_v2/api/papers?')).at(-1).url, 'http://local').searchParams;
const cells = (body) => body.children.map((row) => row.innerHTML);

// ---- The papers table ----

test('the table lists each paper by title with where it came from and what was found', async () => {
  const { $, section, parse, calls, ctx } = await mount();
  await section.show(parse('#/results'));
  const asked = lastList(calls);
  assert.equal(asked.get('sort'), 'title');
  assert.equal(asked.get('limit'), '50');
  assert.equal(asked.get('offset'), '0');
  const [first, second] = cells($('res-papers'));
  assert.match(first, new RegExp(`<a class="row-link" href="#/results/${SHA('a')}">Solitude &lt;b&gt;and&lt;/b&gt; stress</a>`));
  assert.match(first, /PMID 111 · pubmed\/papers\/PMC1\/a.pdf/);
  assert.match(first, /<td>3<\/td>/);
  assert.match(first, /4<small class="bad">1 failed<\/small>/);
  assert.match(first, /5<small>claims: 4 · effects: 1<\/small>/);
  assert.match(second, /None/);
  assert.equal($('res-summary').textContent, 'Showing 1-2 of 2 papers.');
  assert.equal(ctx.replaced.at(-1), '#/results');
  assert.equal($('res-view-paper').hidden, true);
});

test('filters from a link reach the API, fill the form, and the request filter says which run', async () => {
  const { $, section, parse, calls } = await mount();
  await section.show(parse('#/results?collection=c1&prompt=claims&model=model-b&has_results=false&sort=newest&request=r-folder-5678&q=alone'));
  const asked = lastList(calls);
  assert.deepEqual(Object.fromEntries(asked), {
    q: 'alone', collection: 'c1', prompt: 'claims', model: 'model-b', has_results: 'false', request_id: 'r-folder-5678',
    sort: 'newest', limit: '50', offset: '0',
  });
  assert.equal($('res-collection').value, 'c1');
  assert.equal($('res-prompt').value, 'claims');
  assert.equal($('res-model').value, 'model-b');
  assert.equal($('res-has').value, 'false');
  assert.equal($('res-q').value, 'alone');
  assert.equal($('res-request').hidden, false);
  assert.match($('res-request').innerHTML, /href="#\/runs\/r-folder-5678">r-folder<\/a>/);
  assert.match($('res-request').innerHTML, /Show every paper/);
  assert.doesNotMatch($('res-request').innerHTML, /request=/);
});

test('applying the form navigates to its filters, keeping the run filter; Clear drops them all', async () => {
  const { $, section, parse, ctx } = await mount();
  await section.show(parse('#/results?request=r1'));
  $('res-q').value = ' stress ';
  $('res-collection').value = 'c1';
  $('res-has').value = 'true';
  $('res-sort').value = 'title';
  await fire($('res-filters'), 'submit');
  assert.equal(ctx.navigated.at(-1), '#/results?q=stress&collection=c1&has_results=true&request=r1');
  await fire($('res-clear'), 'click');
  assert.equal(ctx.navigated.at(-1), '#/results');
});

test('pages move by fifty and the page goes in the URL', async () => {
  const { $, section, parse, calls, ctx } = await mount({
    '/phases_v2/api/papers?': (url) => ({ ...PAPERS, total: 120, offset: Number(new URL(url, 'http://local').searchParams.get('offset')) }),
  });
  await section.show(parse('#/results?collection=c1'));
  assert.equal($('res-prev').disabled, true);
  assert.equal($('res-next').disabled, false);
  assert.equal($('res-page-label').textContent, 'Page 1 of 3');
  await fire($('res-next'), 'click');
  assert.equal(lastList(calls).get('offset'), '50');
  assert.equal(lastList(calls).get('collection'), 'c1');
  assert.equal(ctx.replaced.at(-1), '#/results?collection=c1&page=2');
  assert.equal($('res-summary').textContent, 'Showing 51-52 of 120 papers.');
});

test('an empty corpus and an empty filter each say what to do next', async () => {
  const empty = { papers: [], total: 0, limit: 50, offset: 0 };
  const { $, section, parse } = await mount({ '/phases_v2/api/papers?': empty });
  await section.show(parse('#/results'));
  assert.match($('res-papers').innerHTML, /No papers have been ingested yet/);
  await section.show(parse('#/results?q=zzz'));
  assert.match($('res-papers').innerHTML, /No papers match these filters/);
});

test('a list that cannot load says why', async () => {
  const { $, section, parse } = await mount({ '/phases_v2/api/papers?': () => response({ detail: 'That run request does not exist.' }, { ok: false, status: 404 }) });
  await section.show(parse('#/results?request=gone'));
  assert.equal($('res-summary').textContent, 'Could not load the papers: That run request does not exist.');
});

// ---- One paper ----

test('a paper page shows its PubMed and OpenAlex records, escaped, with safe links only', async () => {
  const { $, section, parse } = await mount();
  await section.show(parse(`#/results/${SHA('a')}`));
  const head = $('res-paper-head').innerHTML;
  assert.match(head, /Solitude &lt;b&gt;and&lt;\/b&gt; stress/);
  assert.match(head, /Ada &lt;Byron&gt;, Alan Turing/);
  assert.match(head, /href="https:\/\/pubmed.ncbi.nlm.nih.gov\/111\/"/);
  assert.match(head, /href="https:\/\/doi.org\/10.1000\/solitude"/);
  assert.match(head, /42 citations · Open access \(gold\)/);
  assert.match(head, /href="https:\/\/example.org\/a"/);
  assert.doesNotMatch(head, /javascript:/);
  assert.match(head, /3 with window/);
  assert.equal($('res-view-list').hidden, true);
  assert.equal($('res-view-paper').hidden, false);
  assert.equal($('res-paper-title').focused, true);
});

test('what ran lists each version and model with its counts and the runs behind it', async () => {
  const { $, section, parse } = await mount();
  await section.show(parse(`#/results/${SHA('a')}`));
  const rows = $('res-ran').innerHTML;
  assert.match(rows, /claims<small>version 2222222/);
  assert.match(rows, /claims<small>version 1111111/);
  assert.match(rows, /Model A/);
  assert.match(rows, /<span class="bad">· 1 failed<\/span>/);
  assert.match(rows, /href="#\/runs\/r-pubmed-1234">r-pubmed<\/a>/);
  assert.match($('res-requests').innerHTML, /href="#\/runs\/r-pubmed-1234"/);
  assert.match($('res-requests').innerHTML, /member@example.org/);
});

test('results show by chunk with the chunk itself, failures with their error, and relations as graphs', async () => {
  const { $, section, parse, ctx } = await mount();
  await section.show(parse(`#/results/${SHA('a')}?group=${V1}|model-a`));
  assert.equal($('res-group').value, `${V1}|model-a`);
  const body = $('res-group-body').innerHTML;
  assert.match(body, /Chunk #0/);
  assert.match(body, /First chunk &lt;text&gt;/);
  assert.match(body, /Older adults &lt;i&gt;seek&lt;\/i&gt; time alone/);
  assert.match(body, /Chunk #1[\s\S]*Not &lt;valid&gt; JSON/);
  assert.match(body, /\{not json/);
  assert.equal(ctx.replaced.at(-1), `#/results/${SHA('a')}?group=${encodeURIComponent(`${V1}|model-a`)}&a=${encodeURIComponent(`${V2}|model-a`)}&b=${encodeURIComponent(`${V1}|model-a`)}`);
  $('res-group').value = `${EFFECTS}|model-a`;
  await fire($('res-group'), 'change');
  assert.match($('res-group-body').innerHTML, /Chunk #2/);
  assert.match($('res-group-body').innerHTML, /relation-flow/);
  assert.match($('res-group-body').innerHTML, /spending time alone/);
  assert.match(ctx.replaced.at(-1), new RegExp(`group=${encodeURIComponent(`${EFFECTS}|model-a`).replace(/[|]/g, '\\|')}`));
});

test('two versions compare side by side, chunk by chunk, with shared findings marked', async () => {
  const { $, section, parse } = await mount();
  await section.show(parse(`#/results/${SHA('a')}`));
  // The first two groups are compared by default.
  assert.equal($('res-compare-a').value, `${V2}|model-a`);
  assert.equal($('res-compare-b').value, `${V1}|model-a`);
  const body = $('res-compare-body').innerHTML;
  assert.match(body, /1 item\. claims · version 1111111 · Model A: 2 items\. 1 found by both, 0 only by the first, 1 only by the second\./);
  assert.match(body, /<li class="same">/);
  assert.match(body, /Also found by the other/);
  assert.match(body, /Chunk #1[\s\S]*Nothing found here/);
  $('res-compare-b').value = `${V2}|model-a`;
  await fire($('res-compare-b'), 'change');
  assert.match($('res-compare-body').innerHTML, /Choose two different versions or models/);
});

test('a deep link chooses what to compare', async () => {
  const { $, section, parse } = await mount();
  await section.show(parse(`#/results/${SHA('a')}?a=${EFFECTS}|model-a&b=${V1}|model-a`));
  assert.equal($('res-compare-a').value, `${EFFECTS}|model-a`);
  assert.equal($('res-compare-b').value, `${V1}|model-a`);
});

test('a long result list draws the first items and offers the rest', async () => {
  const many = Array.from({ length: 250 }, (_, i) => item(`m${i}`, 'c0', `Claim ${i}`));
  const detail = { ...DETAIL, results: [group(V1, 'claims', 'model-a', { item_count: 250, items: many })] };
  const { $, section, parse } = await mount({ [`/phases_v2/api/papers/${SHA('a')}`]: detail });
  await section.show(parse(`#/results/${SHA('a')}`));
  assert.equal(($('res-group-body').innerHTML.match(/<li>/g) || []).length, 200);
  assert.equal($('res-group-more').hidden, false);
  assert.equal($('res-group-more').textContent, 'Show all 250 items');
  await fire($('res-group-more'), 'click');
  assert.equal(($('res-group-body').innerHTML.match(/<li>/g) || []).length, 250);
  assert.equal($('res-group-more').hidden, true);
});

test('with exactly the items drawn at once, a failure in a later chunk still shows', async () => {
  const many = Array.from({ length: 200 }, (_, i) => item(`m${i}`, 'c0', `Claim ${i}`));
  const failure = { extraction_id: 'e-late', chunk_id: 'c2', seq: 2, status: 'failed', error: 'Late failure', raw_excerpt: '' };
  const detail = { ...DETAIL, results: [group(V1, 'claims', 'model-a', { item_count: 200, failed: 1, items: many, failures: [failure] })] };
  const { $, section, parse } = await mount({ [`/phases_v2/api/papers/${SHA('a')}`]: detail });
  await section.show(parse(`#/results/${SHA('a')}`));
  assert.equal(($('res-group-body').innerHTML.match(/<li>/g) || []).length, 200);
  assert.match($('res-group-body').innerHTML, /Chunk #2[\s\S]*Late failure/);
  assert.equal($('res-group-more').hidden, true);
});

test('past the items drawn at once, later failures show and the rest of the items wait', async () => {
  const many = Array.from({ length: 201 }, (_, i) => item(`m${i}`, i < 200 ? 'c0' : 'c1', `Claim ${i}`));
  const failure = { extraction_id: 'e-late', chunk_id: 'c2', seq: 2, status: 'failed', error: 'Late failure', raw_excerpt: '' };
  const detail = { ...DETAIL, results: [group(V1, 'claims', 'model-a', { item_count: 201, failed: 1, items: many, failures: [failure] })] };
  const { $, section, parse } = await mount({ [`/phases_v2/api/papers/${SHA('a')}`]: detail });
  await section.show(parse(`#/results/${SHA('a')}`));
  const body = $('res-group-body').innerHTML;
  assert.doesNotMatch(body, /Chunk #1/);
  assert.match(body, /Chunk #2[\s\S]*Late failure/);
  assert.equal($('res-group-more').hidden, false);
});

test('a paper nothing ran on still opens, says so, and offers only its PDF', async () => {
  const detail = { ...DETAIL, pubmed: null, openalex: null, ran: [], requests: [], results: [], chunks: {}, paper: { ...DETAIL.paper, pmid: null, source: 'file', title: 'Zebra.pdf' } };
  const { $, section, parse } = await mount({ [`/phases_v2/api/papers/${SHA('a')}`]: detail });
  await section.show(parse(`#/results/${SHA('a')}`));
  assert.match($('res-paper-head').innerHTML, /Uploaded or stored file/);
  assert.match($('res-ran').innerHTML, /Nothing has been run on this paper yet/);
  assert.match($('res-requests').innerHTML, /No recorded run included this paper/);
  assert.match($('res-group-body').innerHTML, /Nothing has been run on this paper yet/);
  assert.match($('res-compare-body').innerHTML, /Two versions or models must have run/);
  assert.equal($('res-csv').disabled, true);
  assert.equal($('res-pdf').disabled, false);
});

test('a paper opens without waiting for the filter lists, and names its models once they come', async () => {
  let models;
  const { $, section, parse } = await mount({ '/phases_v2/api/models': () => new Promise((resolve) => { models = resolve; }) });
  const shown = section.show(parse(`#/results/${SHA('a')}`));
  await settle();
  assert.match($('res-paper-head').innerHTML, /Solitude &lt;b&gt;and&lt;\/b&gt; stress/);
  assert.match($('res-ran').innerHTML, /model-a/);
  models(response({ models: [{ model_id: 'model-a', display_name: 'Model A' }] }));
  await shown;
  assert.match($('res-ran').innerHTML, /Model A/);
});

test('the CSV of results whose model is unknown asks for exactly those', async () => {
  const detail = { ...DETAIL, results: [group(V1, 'claims', null, { item_count: 1, items: [item('i9', 'c0', 'Orphan')] })] };
  const { $, section, parse, calls } = await mount({
    [`/phases_v2/api/papers/${SHA('a')}`]: detail,
    [`/phases_v2/api/papers/${SHA('a')}/export`]: () => response('query,mode\n', { type: 'text/csv; charset=utf-8' }),
  });
  globalThis.URL.createObjectURL = () => 'blob:x';
  globalThis.URL.revokeObjectURL = () => {};
  await section.show(parse(`#/results/${SHA('a')}`));
  await fire($('res-group-csv'), 'click');
  await settle();
  const exported = new URL(calls.at(-1).url, 'http://local').searchParams;
  assert.equal(exported.get('prompt_id'), V1);
  // Present and empty: the results without a model, not every model's.
  assert.equal(exported.has('model_id'), true);
  assert.equal(exported.get('model_id'), '');
});

test('a paper that is not in the corpus says so', async () => {
  const { $, section, parse } = await mount({ '/phases_v2/api/papers/missing': () => response({ detail: 'That paper is not in the corpus.' }, { ok: false, status: 404 }) });
  await section.show(parse('#/results/missing'));
  assert.match($('res-paper-message').textContent, /not in the corpus/);
});

test('the PDF and the CSV download for the paper, and for one group', async () => {
  const saved = [];
  const { $, section, parse, calls, a } = await mount({
    '/phases_v2/api/search/paper': () => response('%PDF-', { type: 'application/pdf' }),
    [`/phases_v2/api/papers/${SHA('a')}/export`]: () => response('query,mode\n', { type: 'text/csv; charset=utf-8' }),
  });
  globalThis.URL.createObjectURL = () => 'blob:x';
  globalThis.URL.revokeObjectURL = () => {};
  globalThis.document.createElement = ((original) => (tag) => { const el = original(tag); if (tag === 'a') saved.push(el); return el; })(globalThis.document.createElement);
  await section.show(parse(`#/results/${SHA('a')}?group=${EFFECTS}|model-a`));
  await a.downloadPdf();
  assert.equal(new URL(calls.at(-1).url, 'http://local').searchParams.get('paper_id'), SHA('a'));
  assert.equal(saved.at(-1).download, 'PMID-111.pdf');
  await fire($('res-group-csv'), 'click');
  await settle();
  const exported = new URL(calls.at(-1).url, 'http://local');
  assert.equal(exported.pathname, `/phases_v2/api/papers/${SHA('a')}/export`);
  assert.equal(exported.searchParams.get('prompt_id'), EFFECTS);
  assert.equal(exported.searchParams.get('model_id'), 'model-a');
  assert.equal(saved.at(-1).download, 'healthyphases-PMID-111.csv');
  await fire($('res-csv'), 'click');
  await settle();
  assert.equal(new URL(calls.at(-1).url, 'http://local').search, '');
  assert.match($('res-paper-message').textContent, /Every result of this paper downloaded/);
});

test('a missing PDF is reported next to the buttons', async () => {
  const { $, section, parse } = await mount({ '/phases_v2/api/search/paper': () => response({ detail: 'Source PDF is unavailable.' }, { ok: false, status: 404 }) });
  await section.show(parse(`#/results/${SHA('a')}`));
  await fire($('res-pdf'), 'click');
  await settle();
  assert.equal($('res-paper-message').textContent, 'The PDF of this paper is unavailable.');
});

test('the back link returns to the filtered list the paper was opened from', async () => {
  const { $, section, parse } = await mount();
  await section.show(parse('#/results?collection=c1'));
  await section.show(parse(`#/results/${SHA('a')}`));
  assert.equal($('res-back').href, '#/results?collection=c1');
});

test('refreshing an open paper re-reads it in place', async () => {
  const { $, section, parse, calls } = await mount();
  await section.show(parse(`#/results/${SHA('a')}?group=${EFFECTS}|model-a`));
  const before = calls.length;
  await section.refresh();
  assert.equal(calls.length, before + 1);
  assert.equal($('res-group').value, `${EFFECTS}|model-a`);
});

// ---- The comparison, without a page ----

test('compared groups are aligned by chunk in reading order', async () => {
  const { view } = await mount();
  const [v2, v1] = RESULTS;
  const { rows, summary } = view.compareRows(v2, v1, DETAIL.chunks);
  assert.deepEqual(rows.map((r) => [r.seq, r.a.items.length, r.b.items.length, r.b.failures.length]), [[0, 1, 2, 0], [1, 0, 0, 1]]);
  assert.deepEqual(summary, { a: 1, b: 2, shared: 1, onlyA: 0, onlyB: 1, chunks: 2 });
  assert.equal(view.versionTag(V1), '1111111');
  assert.equal(view.versionTag('custom'), 'custom');
});

test('an answer that arrives after leaving Results does not rewrite the URL', async () => {
  let answer;
  const { section, parse, ctx } = await mount({ '/phases_v2/api/papers?': () => new Promise((resolve) => { answer = resolve; }) });
  const shown = section.show(parse('#/results?q=late'));
  await settle();
  section.hide();
  answer(response(PAPERS));
  await shown;
  assert.equal(ctx.replaced.length, 0);
});
