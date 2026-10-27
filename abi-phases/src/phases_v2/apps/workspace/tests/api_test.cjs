const assert = require('node:assert/strict');
const { test } = require('node:test');
const { install, load, response } = require('./harness.cjs');

test('the API base comes from the Nexus runtime config of this window, its parent or the top window', async () => {
  const dom = install();
  const { apiBase } = await load('api.js');
  assert.equal(apiBase(), '');
  dom.window.top = { __NEXUS_RUNTIME_CONFIG__: { apiUrl: 'https://top.example/' } };
  assert.equal(apiBase(), 'https://top.example');
  dom.window.parent = { __NEXUS_RUNTIME_CONFIG__: { apiUrl: 'https://parent.example' } };
  assert.equal(apiBase(), 'https://parent.example');
  dom.window.__NEXUS_RUNTIME_CONFIG__ = { apiUrl: 'https://self.example/' };
  assert.equal(apiBase(), 'https://self.example');
});

test('a cross-origin parent does not break resolution', async () => {
  const dom = install();
  const { apiBase } = await load('api.js');
  dom.window.parent = new Proxy({}, { get() { throw new Error('SecurityError'); } });
  dom.window.top = { __NEXUS_RUNTIME_CONFIG__: { apiUrl: 'https://top.example' } };
  assert.equal(apiBase(), 'https://top.example');
});

test('every module client calls its own prefix with the session bearer token and cookies', async () => {
  const dom = install({ storage: { 'nexus-auth': JSON.stringify({ state: { token: 'test-token' } }) } });
  dom.window.__NEXUS_RUNTIME_CONFIG__ = { apiUrl: 'https://abi.example' };
  const api = await load('api.js');
  const seen = [];
  globalThis.fetch = async (url, options) => { seen.push({ url, options }); return response({}); };
  await api.phases('/collections', { method: 'POST', body: { name: 'Research', locations: ['phases_v2'] } });
  await api.search('/prompts');
  await api.pubmed('/queries');
  await api.openalex('/status');
  assert.deepEqual(seen.map((s) => s.url), [
    'https://abi.example/phases_v2/api/collections',
    'https://abi.example/phases_v2/api/search/prompts',
    'https://abi.example/pubmed/api/queries',
    'https://abi.example/openalex/api/status',
  ]);
  for (const { options } of seen) {
    assert.equal(options.credentials, 'include');
    assert.equal(options.headers.Authorization, 'Bearer test-token');
  }
  assert.equal(seen[0].options.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(seen[0].options.body), { name: 'Research', locations: ['phases_v2'] });
  assert.equal(seen[1].options.headers['Content-Type'], undefined);
});

test('a missing or unreadable session sends no Authorization header', async () => {
  install({ storage: { 'nexus-auth': 'not json' } });
  const { authHeaders } = await load('api.js');
  assert.deepEqual(authHeaders(), {});
  globalThis.localStorage = { getItem() { throw new Error('denied'); } };
  assert.deepEqual(authHeaders(), {});
});

test('raw uploads keep their bytes and content type', async () => {
  install();
  const { phases } = await load('api.js');
  let sent;
  globalThis.fetch = async (_url, options) => { sent = options; return response({ key: 'a.pdf' }, { status: 201 }); };
  const file = { name: 'a.pdf' };
  await phases('/documents?location=x&filename=a.pdf', { method: 'POST', body: file, raw: true, contentType: 'application/pdf' });
  assert.equal(sent.body, file);
  assert.equal(sent.headers['Content-Type'], 'application/pdf');
});

test('a non-JSON response gives an actionable error without exposing its HTML', async () => {
  install();
  const { phases, readJson } = await load('api.js');
  await assert.rejects(readJson({ status: 404, text: async () => '<html>secret diagnostic</html>' }, '/api'), (error) => {
    assert.match(error.message, /Expected JSON from \/api/);
    assert.doesNotMatch(error.message, /secret diagnostic/);
    return true;
  });
  globalThis.fetch = async () => response('<html>Next.js 404</html>', { ok: false, status: 404, type: 'text/html' });
  await assert.rejects(phases('/prompts'), /Expected JSON/);
});

test('API errors surface the server detail, field errors or a plain status message', async () => {
  install();
  const { phases } = await load('api.js');
  globalThis.fetch = async () => response({ detail: 'Name is required.' }, { ok: false, status: 422 });
  await assert.rejects(phases('/collections', { method: 'POST', body: {} }), (error) => error.message === 'Name is required.' && error.status === 422);
  globalThis.fetch = async () => response({ detail: [{ loc: ['query', 'page_size'], msg: 'must be at most 100' }] }, { ok: false, status: 422 });
  await assert.rejects(phases('/x'), /page_size: must be at most 100/);
  globalThis.fetch = async () => response({}, { ok: false, status: 401 });
  await assert.rejects(phases('/x'), /session has expired/);
  globalThis.fetch = async () => response({}, { ok: false, status: 503 });
  await assert.rejects(phases('/x'), /temporarily unavailable/);
  globalThis.fetch = async () => response({}, { ok: false, status: 418 });
  await assert.rejects(phases('/x'), /request failed \(418\)/);
});

test('an empty 204 response succeeds', async () => {
  install();
  const { pubmed } = await load('api.js');
  globalThis.fetch = async () => ({ ok: true, status: 204 });
  assert.deepEqual(await pubmed('/schedules/s', { method: 'DELETE' }), {});
});

test('network failures say the server could not be reached, while aborts pass through', async () => {
  install();
  const { phases } = await load('api.js');
  globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
  await assert.rejects(phases('/x'), /Could not reach the server: Failed to fetch/);
  globalThis.fetch = async () => { const e = new Error('aborted'); e.name = 'AbortError'; throw e; };
  await assert.rejects(phases('/x'), (error) => error.name === 'AbortError');
});

test('binary downloads check the content type and explain a missing file', async () => {
  install();
  const { fetchBlob } = await load('api.js');
  globalThis.fetch = async () => response('a,b', { type: 'text/csv; charset=utf-8' });
  assert.equal(await (await fetchBlob('/export', { accept: 'text/csv' })).text(), 'a,b');
  globalThis.fetch = async () => response({ detail: 'Search storage is unavailable. Please retry.' }, { ok: false, status: 503 });
  await assert.rejects(fetchBlob('/export', { accept: 'text/csv' }), /Search storage is unavailable/);
  globalThis.fetch = async () => ({ ok: false, status: 404 });
  await assert.rejects(fetchBlob('/paper', { notFound: 'Source PDF is unavailable.' }), /Source PDF is unavailable/);
});

test('a download answered with HTML by the wrong server keeps the connection diagnostic', async () => {
  install();
  const { fetchBlob } = await load('api.js');
  globalThis.fetch = async () => response('<html>Next.js</html>', { type: 'text/html' });
  await assert.rejects(fetchBlob('/export', { accept: 'text/csv' }), /Expected JSON from \/export but got 200/);
});
