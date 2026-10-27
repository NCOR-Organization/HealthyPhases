// The workspace shell: one section visible at a time, chosen by the hash route.
//
// Each section module exports create(root, ctx) returning { show(route), hide(),
// refresh() }. Sections are created on first visit and then kept, so a draft in
// one section survives a visit to another.

import { createRouter, href, SECTIONS } from './router.js';
import { $, confirmAction, toast } from './ui.js';
import * as overview from './sections/overview.js';
import * as library from './sections/library.js';
import * as collections from './sections/collections.js';
import * as prompts from './sections/prompts.js';
import * as runs from './sections/runs.js';
import * as search from './sections/search.js';

export const MODULES = { overview, library, collections, prompts, runs, search };
export const TITLES = {
  overview: 'Overview', library: 'Library', collections: 'Collections',
  prompts: 'Prompts', runs: 'Runs', search: 'Search',
};

// Focus and visibility often fire together; one refresh covers both.
const REFRESH_GAP_MS = 2000;

// Follow the Nexus light/dark choice when the embedding page exposes it.
function syncTheme() {
  try {
    if (window.parent === window) return;
    const root = window.parent.document.documentElement;
    const apply = () => {
      const theme = root.classList.contains('dark') ? 'dark' : root.classList.contains('light') ? 'light' : '';
      if (theme) document.documentElement.dataset.theme = theme;
      else delete document.documentElement.dataset.theme;
    };
    apply();
    new MutationObserver(apply).observe(root, { attributes: true, attributeFilter: ['class'] });
  } catch (_crossOrigin) {
    // Served on its own: the system colour scheme applies.
  }
}

export function boot({ modules = MODULES, every = (ms, work) => setInterval(work, ms) } = {}) {
  const instances = {};
  let active = '';
  let lastRefresh = 0;

  const ctx = {
    href,
    navigate: (target) => router.navigate(target),
    replace: (target) => router.replace(target),
    section,
    toast,
    confirm: confirmAction,
    every,
  };

  function section(name) {
    if (!instances[name]) instances[name] = modules[name].create($(`section-${name}`), ctx);
    return instances[name];
  }

  function show(route) {
    const entering = route.section !== active;
    if (entering && active) instances[active]?.hide?.();
    for (const name of SECTIONS) $(`section-${name}`).hidden = name !== route.section;
    for (const link of document.querySelectorAll('[data-nav]')) {
      if (link.dataset.nav === route.section) link.setAttribute('aria-current', 'page');
      else link.removeAttribute('aria-current');
    }
    document.title = `${TITLES[route.section]} · HealthyPhases`;
    const first = !active;
    const existed = Boolean(instances[route.section]);
    active = route.section;
    // A section created earlier is told it is being re-entered, so it re-reads its lists.
    section(route.section).show(route, { entering: entering && existed });
    if (entering && !first) $(`section-${route.section}`).querySelector('h1')?.focus();
  }

  function refresh() {
    const now = Date.now();
    if (!active || document.hidden || now - lastRefresh < REFRESH_GAP_MS) return;
    lastRefresh = now;
    instances[active]?.refresh();
  }

  const router = createRouter(show);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  window.addEventListener('focus', refresh);
  $('skip-link')?.addEventListener('click', () => $('main').focus());
  syncTheme();
  lastRefresh = Date.now();
  router.start();
  return { ctx, section, refresh, instances, router };
}
