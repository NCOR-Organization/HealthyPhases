const assert = require('node:assert/strict');
const { test } = require('node:test');
const { install, load } = require('./harness.cjs');

const SECTIONS = ['overview', 'library', 'collections', 'prompts', 'runs', 'search'];

// Stand-in sections that record how the shell drives them.
function recorders() {
  const log = [];
  const modules = Object.fromEntries(SECTIONS.map((name) => [name, {
    create(root, ctx) {
      log.push(['create', name]);
      return {
        show: (route, options = {}) => log.push(['show', name, ...route.parts, ...(options.entering ? ['entering'] : [])]),
        hide: () => log.push(['hide', name]),
        refresh: () => log.push(['refresh', name]),
        ctx,
      };
    },
  }]));
  return { log, modules };
}

test('one section is visible at a time, with the matching link marked as current', async () => {
  const dom = install({ hash: '#/runs/r1' });
  const { boot } = await load('shell.js');
  const { log, modules } = recorders();
  boot({ modules, every() {} });
  for (const name of SECTIONS) assert.equal(dom.$(`section-${name}`).hidden, name !== 'runs');
  assert.equal(dom.navLinks.find((l) => l.dataset.nav === 'runs').attributes['aria-current'], 'page');
  assert.equal(dom.navLinks.filter((l) => l.attributes['aria-current']).length, 1);
  assert.equal(dom.document.title, 'Runs · HealthyPhases');
  assert.deepEqual(log, [['create', 'runs'], ['show', 'runs', 'r1']]);

  dom.location.hash = '#/search?q=x';
  dom.hashchange();
  assert.equal(dom.$('section-search').hidden, false);
  assert.equal(dom.$('section-runs').hidden, true);
  assert.equal(dom.navLinks.find((l) => l.dataset.nav === 'runs').attributes['aria-current'], undefined);
  assert.deepEqual(log.slice(2), [['hide', 'runs'], ['create', 'search'], ['show', 'search']]);
});

test('sections are created once and kept, and focus moves to the new heading', async () => {
  const dom = install({ hash: '#/runs' });
  const { boot } = await load('shell.js');
  const { log, modules } = recorders();
  const heading = { focus() { heading.focused = (heading.focused || 0) + 1; } };
  dom.$('section-prompts').querySelector = () => heading;
  boot({ modules, every() {} });
  for (const hash of ['#/prompts', '#/runs', '#/prompts/p1']) { dom.location.hash = hash; dom.hashchange(); }
  assert.equal(log.filter(([kind, name]) => kind === 'create' && name === 'prompts').length, 1);
  assert.equal(heading.focused, 2, 'entering a section focuses its heading');
  dom.location.hash = '#/prompts/p2';
  dom.hashchange();
  assert.equal(heading.focused, 2, 'changing route within a section keeps focus where it is');
});

test('a hidden page that becomes visible, or a window that regains focus, refreshes the open section', async () => {
  const dom = install({ hash: '#/library' });
  const { boot } = await load('shell.js');
  const { log, modules } = recorders();
  const realNow = Date.now;
  let now = 1_000_000;
  Date.now = () => now;
  try {
    boot({ modules, every() {} });
    now += 5000;
    dom.document.hidden = true;
    dom.dispatchDocument('visibilitychange');
    assert.equal(log.filter(([kind]) => kind === 'refresh').length, 0, 'hidden pages do not refresh');
    dom.document.hidden = false;
    dom.dispatchDocument('visibilitychange');
    dom.dispatchWindow('focus');
    assert.deepEqual(log.filter(([kind]) => kind === 'refresh'), [['refresh', 'library']], 'focus right after visibility is one refresh');
    now += 5000;
    dom.dispatchWindow('focus');
    assert.equal(log.filter(([kind]) => kind === 'refresh').length, 2);
  } finally {
    Date.now = realNow;
  }
});

test('every real section mounts, and a run draft survives visits to other sections', async () => {
  const dom = install({ hash: '#/runs/new' });
  const { boot } = await load('shell.js');
  const shell = boot({ every() {} });
  dom.$('run-model').value = 'chosen-model';
  for (const hash of ['#/overview', '#/library', '#/library/search', '#/library/downloads', '#/library/schedules',
    '#/collections', '#/prompts', '#/search?q=stress', '#/runs', '#/runs/new']) {
    dom.location.hash = hash;
    dom.hashchange();
  }
  assert.deepEqual(Object.keys(shell.instances).sort(), [...SECTIONS].sort());
  assert.equal(dom.$('run-model').value, 'chosen-model');
  assert.equal(dom.$('section-runs').hidden, false);
});

test('the theme follows the Nexus page when it is readable', async () => {
  const dom = install();
  const classes = new Set(['dark']);
  dom.window.parent = { document: { documentElement: { classList: { contains: (c) => classes.has(c) } } } };
  globalThis.MutationObserver = class { constructor(fn) { this.fn = fn; } observe() {} };
  const { boot } = await load('shell.js');
  const { modules } = recorders();
  boot({ modules, every() {} });
  assert.equal(dom.document.documentElement.dataset.theme, 'dark');
  delete globalThis.MutationObserver;
});

test('a section re-entered from another one is told so, and only then', async () => {
  const dom = install({ hash: '#/collections' });
  const { boot } = await load('shell.js');
  const { log, modules } = recorders();
  boot({ modules, every() {} });
  for (const hash of ['#/runs/new', '#/collections/c9', '#/collections/new']) { dom.location.hash = hash; dom.hashchange(); }
  assert.deepEqual(log.filter(([kind]) => kind === 'show'), [
    ['show', 'collections'], ['show', 'runs', 'new'], ['show', 'collections', 'c9', 'entering'], ['show', 'collections', 'new'],
  ]);
});
