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
  const context = vm.createContext({ document, location: { hash: '#runs' },
    window: { addEventListener() {} }, setInterval() {},
    // Catalog initialization stays pending; each test controls its API responses.
    fetch: () => new Promise(() => {}),
  });
  vm.runInContext(script, context);
  return { context, document, $: document.getElementById };
}

const response = (payload, ok = true) => ({ ok, status: ok ? 200 : 422, text: async () => JSON.stringify(payload) });
const preview = (name) => ({ documents: [{ name, location: 'phases_v2', key: name, supported: true }], total: 1, ingestable: 1, already_ingested: 0, unsupported: 0 });

test('navigation shows one page and preserves the run draft across pages', () => {
  const { context, $ } = app();
  $('model').value = 'chosen-model';
  for (const page of ['prompts', 'collections', 'requests', 'runs']) {
    context.location.hash = `#${page}`; context.route();
    for (const name of ['prompts', 'collections', 'requests', 'runs']) assert.equal($(`page-${name}`).hidden, name !== page);
    assert.equal($('model').value, 'chosen-model');
  }
  context.location.hash = '#unknown'; context.route();
  assert.equal($('page-runs').hidden, false);
});

test('a run sends all chosen locations and prompt versions to the resolved API', async () => {
  const { context, $ } = app(); let sent;
  context.window.__NEXUS_RUNTIME_CONFIG__ = { apiUrl: 'https://abi.example/' };
  $('locations').selectedOptions = [{ value: 'phases_v2/a' }, { value: 'phases_v2/b' }];
  $('prompt').selectedOptions = [{ value: 'old-version' }, { value: 'new-version' }];
  $('model').value = 'model'; $('chunker').value = 'chunker';
  context.fetch = async (url, options) => { sent = { url, body: JSON.parse(options.body) }; return response({ request_id: 'request-123' }); };
  await context.submit();
  assert.equal(sent.url, 'https://abi.example/phases_v2/api/requests');
  assert.deepEqual(sent.body, { locations: ['phases_v2/a', 'phases_v2/b'], prompt_ids: ['old-version', 'new-version'], model_id: 'model', chunker_id: 'chunker' });
  assert.equal($('view-request').hidden, false);
});

test('failed actions display errors and restore the button for retry', async () => {
  const { context, $ } = app();
  await context.action($('submit'), 'message', async () => { throw new Error('Connection lost'); });
  assert.equal($('submit').disabled, false);
  assert.equal($('message').textContent, 'Connection lost');
  assert.equal($('message').className, 'msg bad');
});

test('late document responses cannot replace a newer selection', async () => {
  const { context, $ } = app(); let finishFirst;
  context.fetch = () => new Promise((resolve) => { finishFirst = resolve; });
  const first = context.preview(['phases_v2/old'], 'documents', 'documents-summary');
  context.fetch = async () => response(preview('current.pdf'));
  await context.preview(['phases_v2/new'], 'documents', 'documents-summary');
  finishFirst(response(preview('stale.pdf'))); await first;
  assert.equal($('documents').children.length, 1);
  assert.match($('documents').children[0].innerHTML, /current.pdf/);
  assert.doesNotMatch($('documents').children[0].innerHTML, /stale.pdf/);
});

test('failed previews clear old document rows and report the error', async () => {
  const { context, $ } = app();
  context.fetch = async () => response(preview('old.pdf'));
  await context.preview(['phases_v2/a'], 'documents', 'documents-summary');
  context.fetch = async () => { throw new Error('Storage unavailable'); };
  await context.preview(['phases_v2/b'], 'documents', 'documents-summary');
  assert.equal($('documents').children.length, 0);
  assert.match($('documents-summary').textContent, /Storage unavailable/);
});

test('document names and paths cannot introduce executable markup', async () => {
  const { context, $ } = app();
  context.fetch = async () => response(preview('<img src=x onerror=alert(1)>.pdf'));
  await context.preview(['phases_v2'], 'documents', 'documents-summary');
  const markup = $('documents').children[0].innerHTML;
  assert.match(markup, /&lt;img/); assert.doesNotMatch(markup, /<img/);
});

test('a non-JSON API response gives an actionable error without exposing its HTML', async () => {
  const { context } = app();
  await assert.rejects(context.readJson({ status: 404, text: async () => '<html>secret diagnostic</html>' }, '/api'), (error) => {
    assert.match(error.message, /Expected JSON/); assert.doesNotMatch(error.message, /secret diagnostic/); return true;
  });
});

test('API mutations retain Nexus bearer authentication', async () => {
  const { context } = app(); let headers;
  context.localStorage = { getItem: () => JSON.stringify({ state: { token: 'test-token' } }) };
  context.fetch = async (_url, options) => { headers = options.headers; return response({}); };
  await context.api('/collections', 'POST', { name: 'Research', locations: ['phases_v2'] });
  assert.equal(headers.Authorization, 'Bearer test-token');
  assert.equal(headers['Content-Type'], 'application/json');
});

test('slow request refreshes never overlap', async () => {
  const { context } = app(); let finish; let calls = 0;
  context.fetch = () => { calls++; return new Promise((resolve) => { finish = resolve; }); };
  const first = context.loadRequests();
  await context.loadRequests();
  assert.equal(calls, 1);
  finish(response({ requests: [] })); await first;
});
