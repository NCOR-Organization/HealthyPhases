const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const html = readFileSync(resolve(__dirname, '../index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

function app() {
  const element = () => ({
    innerHTML: '', style: {}, value: '', children: [], options: [], dataset: {},
    classList: { toggle() {} }, addEventListener() {},
    querySelector() { return element(); },
    appendChild(child) { this.children.push(child); },
  });
  const elements = new Map();
  const document = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, element());
      return elements.get(id);
    },
    querySelectorAll() { return []; },
    createElement: element,
  };
  const context = vm.createContext({ document, URLSearchParams, window: {}, AbortController, IntersectionObserver: class { observe() {} },
    fetch: async () => ({ ok: true, text: async () => JSON.stringify({ prompts: [], models: [], paths: [] }) }),
  });
  vm.runInContext(script, context);
  return { context, document };
}

const relation = {
  subject_process: 'Practicing meditation', subject_participant: 'Meditation practitioner',
  target_process: 'Experiencing stress', direction: 'decreases',
  evidence_text: 'Meditation decreased stress.',
};

test('single relations, arrays, and extraction envelopes render typed directed graphs', () => {
  const { context } = app();
  for (const payload of [relation, [relation], { relations: [relation, relation] }]) {
    const rendered = context.renderExtraction(JSON.stringify(payload), '');
    assert.match(rendered, /Independent continuant/);
    assert.match(rendered, /From \/ subject/);
    assert.match(rendered, /To \/ target/);
    assert.match(rendered, /Meditation practitioner/);
    assert.match(rendered, /Practicing meditation/);
    assert.match(rendered, /Experiencing stress/);
    assert.match(rendered, /Meditation decreased stress/);
    assert.match(rendered, /Decreases/);
  }
});

test('all three directions are explicit without relying on color', () => {
  const { context } = app();
  for (const [direction, label] of [['increases', 'Increases'], ['decreases', 'Decreases'], ['no-effect', 'Neutral (no effect)']]) {
    const rendered = context.renderExtraction(JSON.stringify({ ...relation, direction }), '');
    assert.ok(rendered.includes(label));
    assert.ok(rendered.includes(`relation-edge ${direction}`));
  }
});

test('unknown, incomplete and mixed payloads retain their full JSON instead of inventing a graph', () => {
  const { context } = app();
  for (const payload of [null, [], {}, { other: 'value' }, { ...relation, direction: 'unknown' },
    { ...relation, subject_process: '' }, { relations: [relation, { other: 'value' }] }]) {
    const rendered = context.renderExtraction(JSON.stringify(payload), '');
    assert.match(rendered, /json-payload/);
    assert.doesNotMatch(rendered, /relation-flow/);
  }
  assert.match(context.renderExtraction('{broken JSON', ''), /\{broken JSON/);
  assert.match(context.renderExtraction('Ordinary claim', ''), /Ordinary claim/);
});

test('untrusted node text and evidence remain escaped in keyword mode', () => {
  const { context } = app();
  vm.runInContext("state.mode = 'keyword'", context);
  const malicious = '<img src=x onerror=alert(1)> & mark';
  const rendered = context.renderExtraction(JSON.stringify({ ...relation,
    subject_process: malicious, evidence_text: malicious }), 'mark img amp lt', 'keyword');
  assert.doesNotMatch(rendered, /<img/);
  assert.match(rendered, /&lt;<mark>img<\/mark>/);
  assert.match(rendered, /&amp; <mark>mark<\/mark>/);
});

test('source chunk precedes stored prompt, followed by the original JSON', () => {
  const { context, document } = app();
  context.renderHits({ query: '', hits: [{ item_id: 'id',
    extracted_text: JSON.stringify(relation), chunk_text: 'Exact source chunk',
    prompt_template: 'Stored prompt {chunk_text}', paper_id: 'paper-id',
  }] });
  const rendered = document.getElementById('results').children[0].innerHTML;
  assert.ok(rendered.indexOf('Show source chunk') < rendered.indexOf('View extraction prompt'));
  assert.ok(rendered.indexOf('View extraction prompt') < rendered.indexOf('Show original JSON'));
  assert.match(rendered, /Exact source chunk/);
  assert.match(rendered, /Stored prompt \{chunk_text\}/);
  assert.match(rendered, /Download paper/);
});

test('failed downloads explain availability and restore the button', async () => {
  const { context } = app();
  let requested;
  context.fetch = async (url) => { requested = url; return { ok: false, status: 404 }; };
  const button = {};
  const status = {};
  await context.downloadPaper({ item_id: 'id & /?' }, button, status);
  assert.equal(new URL(requested, 'http://localhost').searchParams.get('item_id'), 'id & /?');
  assert.equal(button.disabled, false);
  assert.equal(button.textContent, 'Download paper');
  assert.match(status.textContent, /Source PDF is unavailable/);
});
