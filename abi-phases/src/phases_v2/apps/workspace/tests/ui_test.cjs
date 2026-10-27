const assert = require('node:assert/strict');
const { test } = require('node:test');
const { element, install, load } = require('./harness.cjs');

test('escaping covers every markup character', async () => {
  install();
  const { esc } = await load('ui.js');
  assert.equal(esc(`<img src=x onerror="a('b')"> & co`), '&lt;img src=x onerror=&quot;a(&#39;b&#39;)&quot;&gt; &amp; co');
  assert.equal(esc(null), '');
  assert.equal(esc(0), '0');
});

test('failed actions display errors and restore the button for retry', async () => {
  const dom = install();
  const { action } = await load('ui.js');
  const button = dom.$('submit');
  const result = await action(button, 'message', async () => { throw new Error('Connection lost'); });
  assert.equal(result, undefined);
  assert.equal(button.disabled, false);
  assert.equal(dom.$('message').textContent, 'Connection lost');
  assert.equal(dom.$('message').className, 'msg bad');
  assert.equal(await action(button, 'message', async () => 42), 42);
  assert.equal(dom.$('message').textContent, '');
});

test('status pills give every known status a tone and escape their label', async () => {
  install();
  const { statusPill, tone } = await load('ui.js');
  assert.equal(tone('succeeded'), 'ok');
  assert.equal(tone('running'), 'progress');
  assert.equal(tone('failed'), 'bad');
  assert.equal(tone('partial'), 'warn');
  assert.equal(tone('something new'), 'neutral');
  assert.equal(statusPill('failed', '<b>'), '<span class="pill bad">&lt;b&gt;</span>');
});

test('empty states name the next step', async () => {
  install();
  const { emptyRow, emptyState } = await load('ui.js');
  assert.equal(emptyRow(3, 'Nothing <yet>'), '<tr><td colspan="3" class="empty">Nothing &lt;yet&gt;</td></tr>');
  assert.match(emptyState('No runs yet.', ['#/runs/new', 'Start a run']), /No runs yet\. <a href="#\/runs\/new">Start a run<\/a>/);
});

test('pagination disables what cannot be reached', async () => {
  install();
  const { pagination } = await load('ui.js');
  assert.deepEqual(pagination(1, 0), { prev: true, next: true, go: true, label: 'Page 1 of 1' });
  assert.deepEqual(pagination(1, 3), { prev: true, next: false, go: false, label: 'Page 1 of 3' });
  assert.deepEqual(pagination(3, 3), { prev: false, next: true, go: false, label: 'Page 3 of 3' });
  assert.deepEqual(pagination(2, 3, true), { prev: true, next: true, go: true, label: 'Page 2 of 3' });
});

test('unavailable options stay visible but cannot be chosen, and a single select picks the first usable one', async () => {
  install();
  const { fill } = await load('ui.js');
  const select = element('select');
  fill(select, [{ id: 'a', name: 'A', available: false }, { id: 'b', name: 'B' }], 'id', (m) => m.name);
  assert.equal(select.options[0].disabled, true);
  assert.equal(select.options[0].textContent, 'A - unavailable here');
  assert.equal(select.value, 'b');
  fill(select, [{ id: 'a', name: 'A' }, { id: 'b', name: 'B' }], 'id', (m) => m.name, ['b']);
  assert.equal(select.value, 'b');
  const multi = element('select');
  multi.multiple = true;
  fill(multi, [{ id: 'a' }, { id: 'b' }], 'id', (m) => m.id, ['b']);
  assert.deepEqual(multi.selectedOptions.map((o) => o.value), ['b']);
});

test('selecting values adds options the list does not offer yet', async () => {
  install();
  const { fill, selectValues, selected } = await load('ui.js');
  const select = element('select');
  select.multiple = true;
  fill(select, [{ p: 'phases_v2/a' }], 'p', (l) => l.p);
  selectValues(select, ['phases_v2/a', 'phases_v2/new'], (v) => `name of ${v}`);
  assert.deepEqual(selected(select), ['phases_v2/a', 'phases_v2/new']);
  assert.equal(select.options[1].textContent, 'name of phases_v2/new');
});

test('a late response can tell it was superseded', async () => {
  install();
  const { latest } = await load('ui.js');
  const guard = latest();
  const first = guard.next();
  const second = guard.next();
  assert.equal(guard.is(first), false);
  assert.equal(guard.is(second), true);
});

test('confirmation: cancelling never runs the action', async () => {
  const dom = install();
  const { confirmAction } = await load('ui.js');
  let ran = false;
  const pending = confirmAction({ title: 'Delete?', body: ['One', 'Two'], confirmLabel: 'Delete', danger: true, run: async () => { ran = true; } });
  assert.equal(dom.$('confirm-dialog').open, true);
  assert.equal(dom.$('confirm-title').textContent, 'Delete?');
  assert.deepEqual(dom.$('confirm-body').children.map((p) => p.textContent), ['One', 'Two']);
  assert.equal(dom.$('confirm-ok').className, 'danger-solid');
  assert.equal(dom.$('confirm-cancel').focused, true);
  dom.$('confirm-cancel').onclick();
  assert.equal(await pending, false);
  assert.equal(ran, false);
  assert.equal(dom.$('confirm-dialog').open, false);
});

test('confirmation: a failure keeps the dialog open for retry, and success closes it', async () => {
  const dom = install();
  const { confirmAction } = await load('ui.js');
  let attempts = 0;
  let option;
  const pending = confirmAction({
    title: 'Queue?', confirmLabel: 'Queue', option: { label: 'Refresh too', checked: false },
    run: async (checked) => { attempts += 1; option = checked; if (attempts === 1) throw new Error('Storage unavailable'); },
  });
  assert.equal(dom.$('confirm-option').hidden, false);
  await dom.$('confirm-ok').onclick();
  assert.equal(dom.$('confirm-dialog').open, true);
  assert.equal(dom.$('confirm-error').textContent, 'Storage unavailable');
  assert.equal(dom.$('confirm-ok').disabled, false);
  dom.$('confirm-option-input').checked = true;
  await dom.$('confirm-ok').onclick();
  assert.equal(await pending, true);
  assert.equal(option, true);
  assert.equal(dom.$('confirm-dialog').open, false);
});

test('confirmation: closing with Escape counts as cancelling', async () => {
  const dom = install();
  const { confirmAction } = await load('ui.js');
  const pending = confirmAction({ title: 'Archive?', confirmLabel: 'Archive' });
  dom.$('confirm-dialog').close();
  assert.equal(await pending, false);
});

test('toasts appear in the live region', async () => {
  const dom = install();
  const { toast } = await load('ui.js');
  toast('Saved.');
  assert.equal(dom.$('toasts').children[0].textContent, 'Saved.');
  assert.equal(dom.$('toasts').children[0].className, 'toast ok');
});
