// Overview: the workflow in four steps, each with live counts and a way in.

import { phases, pubmed, search } from '../api.js';
import { $, esc, formatDate, formatNumber, message, plural, statusPill } from '../ui.js';

const STEPS = [
  {
    title: 'Collect papers',
    text: 'Search PubMed and download papers into the library, or upload your own PDFs into a collection.',
    stats: [['ov-papers', 'Papers in the library'], ['ov-queries', 'Saved PubMed searches'], ['ov-collections', 'Collections']],
    links: [['#/library/search', 'Search PubMed', true], ['#/library', 'Browse the library'], ['#/collections', 'Manage collections']],
  },
  {
    title: 'Prepare prompts',
    text: 'Write the instructions that extract findings from each part of a paper. Every saved edit becomes a new version.',
    stats: [['ov-prompts', 'Prompts'], ['ov-versions', 'Prompt versions']],
    links: [['#/prompts', 'Open the prompt library', true], ['#/prompts/new', 'Write a new prompt']],
  },
  {
    title: 'Run the pipeline',
    text: 'Choose papers, prompts and a model, then queue a run. Runs start as soon as the orchestrator is free.',
    stats: [['ov-active', 'Queued or running'], ['ov-succeeded', 'Succeeded recently'], ['ov-failed', 'Failed recently']],
    links: [['#/runs/new', 'Start a run', true], ['#/runs', 'Follow runs']],
    extra: '<p id="ov-latest" class="hint"></p>',
  },
  {
    title: 'Explore results',
    text: 'Search every extracted finding by meaning, by keyword or by effect, and trace it back to its paper.',
    stats: [['ov-result-prompts', 'Prompts with results'], ['ov-result-models', 'Models with results'], ['ov-result-paths', 'Source folders']],
    links: [],
    extra: `<form id="ov-search" class="search-row" role="search"><label class="sr-only" for="ov-q">Search findings</label><input id="ov-q" type="search" placeholder="e.g. solitude reduces stress" autocomplete="off"><button class="primary">Search</button></form>`,
  },
];

const template = () => `
  <header class="page-head"><p class="eyebrow">HealthyPhases</p><h1 tabindex="-1">Overview</h1>
    <p class="lede">Turn research papers into structured, searchable findings in four steps.</p></header>
  <p id="ov-message" class="msg" role="status"></p>
  <ol class="steps">${STEPS.map((step, index) => `
    <li class="card step">
      <div class="step-head"><span class="step-number" aria-hidden="true">${index + 1}</span><h2><span class="sr-only">Step ${index + 1}: </span>${esc(step.title)}</h2></div>
      <p class="muted">${esc(step.text)}</p>
      <dl class="stats">${step.stats.map(([id, label]) => `<div><dt>${esc(label)}</dt><dd id="${id}">…</dd></div>`).join('')}</dl>
      ${step.extra || ''}
      ${step.links.length ? `<div class="row">${step.links.map(([target, label, primary]) => `<a class="button${primary ? ' primary' : ''}" href="${target}">${esc(label)}</a>`).join('')}</div>` : ''}
    </li>`).join('')}
  </ol>`;

const ACTIVE = new Set(['pending', 'running']);

// Pure summaries of each endpoint, kept separate so they are easy to test.
export function summarize({ papers, queries, collections, prompts, requests, resultPrompts, resultModels, resultPaths }) {
  const out = {};
  if (papers) out['ov-papers'] = formatNumber(papers.total);
  if (queries) out['ov-queries'] = formatNumber(queries.queries.length);
  if (collections) out['ov-collections'] = formatNumber(collections.collections.length);
  if (prompts) {
    out['ov-prompts'] = formatNumber(new Set(prompts.prompts.map((p) => p.name)).size);
    out['ov-versions'] = formatNumber(prompts.prompts.length);
  }
  if (requests) {
    const rows = requests.requests;
    out['ov-active'] = formatNumber(rows.filter((r) => ACTIVE.has(r.status)).length);
    out['ov-succeeded'] = formatNumber(rows.filter((r) => r.status === 'succeeded').length);
    out['ov-failed'] = formatNumber(rows.filter((r) => r.status === 'failed').length);
  }
  if (resultPrompts) out['ov-result-prompts'] = formatNumber(resultPrompts.prompts.length);
  if (resultModels) out['ov-result-models'] = formatNumber(resultModels.models.length);
  if (resultPaths) out['ov-result-paths'] = formatNumber(resultPaths.paths.length);
  return out;
}

const SOURCES = {
  papers: [() => pubmed('/papers?status=published&page_size=1&page=1'), ['ov-papers']],
  queries: [() => pubmed('/queries'), ['ov-queries']],
  collections: [() => phases('/collections'), ['ov-collections']],
  prompts: [() => phases('/prompts'), ['ov-prompts', 'ov-versions']],
  requests: [() => phases('/requests?limit=100'), ['ov-active', 'ov-succeeded', 'ov-failed']],
  resultPrompts: [() => search('/prompts'), ['ov-result-prompts']],
  resultModels: [() => search('/models'), ['ov-result-models']],
  resultPaths: [() => search('/paths'), ['ov-result-paths']],
};

export function create(root, ctx) {
  root.innerHTML = template();
  let loading = false;

  $('ov-search').addEventListener('submit', (event) => {
    event.preventDefault();
    const q = $('ov-q').value.trim();
    ctx.navigate(ctx.href('search', [], q ? { q, mode: 'semantic' } : {}));
  });

  async function refresh() {
    if (loading) return;
    loading = true;
    try {
      const names = Object.keys(SOURCES);
      const settled = await Promise.allSettled(names.map((name) => SOURCES[name][0]()));
      const data = {};
      const failures = [];
      settled.forEach((result, index) => {
        const name = names[index];
        if (result.status === 'fulfilled') data[name] = result.value;
        else {
          failures.push(result.reason?.message || String(result.reason));
          for (const id of SOURCES[name][1]) { $(id).textContent = '—'; $(id).title = 'Could not be loaded'; }
        }
      });
      for (const [id, value] of Object.entries(summarize(data))) { $(id).textContent = value; $(id).title = ''; }
      const latestRun = data.requests?.requests?.[0];
      $('ov-latest').innerHTML = latestRun
        ? `Latest run: <a href="${ctx.href('runs', [latestRun.request_id])}">submitted ${esc(formatDate(latestRun.requested_at))}</a> ${statusPill(latestRun.status)}`
        : 'No runs yet. Start one once you have papers and prompts.';
      message('ov-message', failures.length
        ? `Some counts could not be loaded (${plural(failures.length, 'source')}): ${[...new Set(failures)].join('; ')}`
        : '', failures.length ? 'warn' : '');
    } finally {
      loading = false;
    }
  }

  return { show: () => refresh(), hide() {}, refresh };
}
