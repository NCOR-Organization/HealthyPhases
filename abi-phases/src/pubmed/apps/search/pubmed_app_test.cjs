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
      get lastElementChild() { if (!this.lastChild) this.lastChild = element(); return this.lastChild; },
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

test('scheduled queries have a separate page and show enabled and disabled states', async () => {
  const { context, $ } = app();
  context.location.hash = '#schedules';
  context.fetch = async () => response({schedules:[{schedule_id:'s',name:'Daily <query>',search:{query:'solitude',max_results:100},interval_hours:24,enabled:false,status:'idle'}]});
  context.showPage(); await context.schedules();
  assert.equal($('search-page').hidden, true);
  assert.equal($('schedules-page').hidden, false);
  assert.match($('schedules').children[0].innerHTML, /Disabled/);
  assert.match($('schedules').children[0].innerHTML, /Daily &lt;query&gt;/);
  assert.equal($('schedules').children[0].lastElementChild.children[0].textContent, 'Enable');
});

test('schedule creation preserves explicit search-only and disabled choices', async () => {
  const { context, $ } = app(); let sent;
  $('schedule-query').value='q'; $('schedule-name').value='Weekly'; $('schedule-frequency').value='168';
  $('schedule-ingest').checked=false; $('schedule-enabled').checked=false;
  context.fetch=async (url,options)=>{ if(options.method==='POST'){sent=JSON.parse(options.body);return response({enabled:false});}return response({schedules:[]});};
  await context.createSchedule();
  assert.deepEqual(sent,{query_id:'q',name:'Weekly',interval_hours:168,ingest_new:false,enabled:false});
  assert.match($('schedule-message').textContent,/created and disabled/);
});

test('enabling a schedule persists through the API and refreshes the list', async () => {
  const { context, $ } = app(); const calls=[];
  context.fetch=async (url,options)=>{calls.push([url,options.method,options.body]);return response({schedules:[]});};
  await context.toggleSchedule('s',true);
  assert.deepEqual(calls,[['/pubmed/api/schedules/s','PATCH','{"enabled":true}'],['/pubmed/api/schedules','GET',undefined]]);
  assert.match($('schedule-status').textContent,/No scheduled queries/);
});
