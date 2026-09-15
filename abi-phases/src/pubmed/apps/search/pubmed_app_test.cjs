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
      addEventListener() {}, focus() {},
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
  const context = vm.createContext({ document, location: { hash: '' },
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

test('search history cannot replace newer results with a late response', async () => {
  const { context, $ } = app(); let resolveOld;
  $('history').value = 'old'; context.fetch = () => new Promise((resolve) => { resolveOld = resolve; });
  const old = context.chooseQuery();
  $('history').value = 'new'; context.fetch = async () => response({papers:[{pmid:'2',title:'Current'}]});
  await context.chooseQuery(); resolveOld(response({papers:[{pmid:'1',title:'Stale'}]})); await old;
  assert.match($('papers').children[0].innerHTML, /Current/);
});
