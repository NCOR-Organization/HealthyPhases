// Versions: every text saved under the open prompt's name, what each was used
// for, and a line diff between any two of them or the editor's draft.

import { phases } from '../api.js';
import { diffHtml, diffSummary, lineDiff } from '../diff.js';
import { $, emptyRow, esc, fill, formatDate, formatNumber, latest, message, plural, tableHtml } from '../ui.js';

export const DRAFT = 'draft';
const LINKED_REQUESTS = 3;

export const template = () => `
  <section class="card" aria-labelledby="pr-ver-title">
    <div class="card-head"><div><h2 id="pr-ver-title">Versions</h2>
      <p class="hint">Every text saved under this name, newest first. Open one to edit from it, or use it in a run.</p></div></div>
    <div class="versions-table">${tableHtml('pr-ver-rows', ['Version', 'First seen', 'Used by', 'Items', ''], 'Prompt versions')}</div>
    <p id="pr-ver-message" class="msg" role="status"></p>
    <h3>Compare</h3>
    <div class="row end"><div class="grow"><label for="pr-ver-a">From</label><select id="pr-ver-a"></select></div>
      <div class="grow"><label for="pr-ver-b">To</label><select id="pr-ver-b"></select></div></div>
    <p id="pr-ver-summary" class="hint" role="status"></p>
    <pre id="pr-ver-diff" class="diff" aria-label="Line differences"></pre>
  </section>`;

// The day only: the full time is in the cell's title.
export function savedOn(value) {
  const date = new Date(value || '');
  return value && !Number.isNaN(date.getTime()) ? date.toLocaleDateString() : 'Built in';
}

// When the version first appeared: saved, or first run, whichever came first.
export const firstSeen = (version) => version.first_seen || version.registered_at;

export const versionLabel = (version) => `Version ${String(version.prompt_id).slice(-8)}`;

export function usage(version, href) {
  const links = (version.requests || []).slice(0, LINKED_REQUESTS)
    .map((r) => `<a href="${esc(href('runs', [r.request_id]))}" title="${esc(formatDate(r.requested_at))}">${esc(savedOn(r.requested_at))}</a>`);
  const more = version.request_count > links.length ? ` and ${version.request_count - links.length} more` : '';
  const requests = version.request_count ? `<small>${plural(Number(version.request_count), 'run request')}: ${links.join(', ')}${more}</small>` : '';
  return `${plural(Number(version.run_count) || 0, 'extraction run')}${requests}`;
}

export function itemsCell(version) {
  const models = Object.entries(version.by_model || {})
    .map(([model, n]) => `${esc(model)}: ${formatNumber(n.items)} items from ${plural(Number(n.succeeded) || 0, 'chunk')}${n.failed ? `, ${formatNumber(n.failed)} failed` : ''}`);
  return `${formatNumber(version.item_count || 0)}${models.length ? `<small>${models.join('<br>')}</small>` : ''}`;
}

// `draft()` returns the editor's current text; `open(id)` and `use(id)` act on a version.
export function createVersions(ctx, { draft, open, use }) {
  const state = { name: '', versions: [], current: '', guard: latest() };

  function renderRows() {
    const body = $('pr-ver-rows');
    body.replaceChildren();
    if (!state.versions.length) {
      body.innerHTML = emptyRow(5, state.name ? 'No saved version yet.' : 'Save this prompt to start its history.');
      return;
    }
    for (const version of state.versions) {
      const row = document.createElement('tr');
      const tags = [
        version.prompt_id === state.current ? '<span class="pill ok">In the editor</span>' : '',
        version.declared ? '<span class="pill">Built in</span>' : '',
      ].join(' ');
      row.innerHTML = `<td><code>${esc(version.prompt_id.slice(-8))}</code> ${tags}<small>${esc(version.output_key)}</small></td>`
        + `<td title="${esc(formatDate(firstSeen(version), ''))}">${esc(savedOn(firstSeen(version)))}</td><td>${usage(version, ctx.href)}</td><td>${itemsCell(version)}</td><td></td>`;
      const actions = row.lastElementChild;
      const button = (text, handler, label) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'small';
        b.textContent = text;
        if (label) { b.title = label; b.setAttribute('aria-label', label); }
        b.addEventListener('click', handler);
        actions.append(b);
      };
      if (version.prompt_id !== state.current) button('Open', () => open(version.prompt_id));
      button('Use in new run', () => use(version.prompt_id));
      button('Compare', () => compareWith(version.prompt_id), `Compare ${versionLabel(version)} with the text in the editor`);
      body.append(row);
    }
  }

  function fillCompare(from, to) {
    const options = [{ id: DRAFT, label: 'Text in the editor' }, ...state.versions.map((v) => ({ id: v.prompt_id, label: `${versionLabel(v)} · ${savedOn(firstSeen(v))}` }))];
    fill($('pr-ver-a'), options, 'id', (o) => o.label, [from]);
    fill($('pr-ver-b'), options, 'id', (o) => o.label, [to]);
  }

  const textOf = (id) => (id === DRAFT ? draft() : state.versions.find((v) => v.prompt_id === id)?.template ?? '');

  function compare() {
    const ops = lineDiff(textOf($('pr-ver-a').value), textOf($('pr-ver-b').value));
    $('pr-ver-summary').textContent = diffSummary(ops);
    $('pr-ver-diff').innerHTML = diffHtml(ops);
    return ops;
  }

  function compareWith(id) {
    fillCompare(id, DRAFT);
    return compare();
  }

  // The versions of `name`; `current` is the version open in the editor.
  // Resolves null when a later load has superseded this one.
  async function load(name, current = '') {
    const token = state.guard.next();
    state.current = current;
    message('pr-ver-message');
    if (!name) {
      state.name = '';
      state.versions = [];
    } else {
      try {
        const body = await phases(`/prompts/versions?name=${encodeURIComponent(name)}`);
        if (!state.guard.is(token)) return null;
        state.name = name;
        state.versions = body.versions || [];
      } catch (error) {
        if (!state.guard.is(token)) return null;
        state.name = name;
        state.versions = [];
        if (error.status !== 404) message('pr-ver-message', `Could not load versions: ${error.message}`, 'bad');
      }
    }
    renderRows();
    // By default: the previous version against the one in the editor.
    const index = state.versions.findIndex((v) => v.prompt_id === current);
    const from = state.versions[index + 1]?.prompt_id || state.versions[0]?.prompt_id || DRAFT;
    fillCompare(from, DRAFT);
    compare();
    return state.versions;
  }

  $('pr-ver-a').addEventListener('change', compare);
  $('pr-ver-b').addEventListener('change', compare);

  return { load, compare, compareWith, state };
}
