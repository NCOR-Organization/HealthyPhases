// Rendering of one paper's page in Results: its records, what ran on it, one
// prompt version × model's results by chunk, and two of them side by side.
//
// Pure functions of the /phases_v2/api/papers/<paper_id> payload, so they can
// be tested without a page.

import { esc, formatDate, formatNumber, plural, statusPill } from '../ui.js';
import { safeLink } from './library.js';
import { renderExtraction, renderRelation } from './search_render.js';

// A version is named by its prompt and the start of its template's hash.
export function versionTag(promptId) {
  const hash = String(promptId || '').split('_').pop();
  return /^[0-9a-f]{6,}$/.test(hash) ? hash.slice(0, 7) : String(promptId || '');
}

export const groupKey = (group) => `${group.prompt_id}|${group.model_id || ''}`;

export function groupLabel(group, modelName = (id) => id) {
  return `${group.prompt_name} · version ${versionTag(group.prompt_id)} · ${modelName(group.model_id) || 'unknown model'}`;
}

const list = (values) => (Array.isArray(values) ? values : []).filter(Boolean);

export function headerHtml(detail) {
  const { paper, pubmed, openalex } = detail;
  const work = openalex?.work;
  const enrichment = openalex?.enrichment;
  const facts = [];
  if (pubmed) {
    facts.push(['Authors', list(pubmed.authors).join(', ') || '—']);
    facts.push(['Journal', [pubmed.journal, pubmed.publication_date].filter(Boolean).join(' · ') || '—']);
  }
  const ids = [];
  if (paper.pmid) ids.push(safeLink(`https://pubmed.ncbi.nlm.nih.gov/${encodeURIComponent(paper.pmid)}/`, `PMID ${paper.pmid}`));
  if (pubmed?.pmcid) ids.push(esc(pubmed.pmcid));
  if (pubmed?.doi) ids.push(safeLink(`https://doi.org/${pubmed.doi}`, `DOI ${pubmed.doi}`));
  const rows = facts.map(([key, value]) => `<dt>${esc(key)}</dt><dd>${esc(value)}</dd>`);
  if (ids.length) rows.push(`<dt>Identifiers</dt><dd>${ids.join(' · ')}</dd>`);
  rows.push(`<dt>Source file</dt><dd><code>${esc(paper.path || paper.file_name || paper.paper_id)}</code></dd>`);
  rows.push(`<dt>Ingested</dt><dd>${paper.ingested ? esc(formatDate(paper.discovered_at)) : statusPill('failed', 'Text could not be read')}</dd>`);
  rows.push(`<dt>Chunks</dt><dd>${esc(detail.chunkers.map((c) => `${formatNumber(c.chunks)} with ${c.chunker_id}`).join('\n') || 'Not chunked yet')}</dd>`);
  if (enrichment) {
    const topics = work ? list(work.topics).map((t) => t?.name).filter(Boolean) : list(enrichment.topics);
    const access = work ? `${work.is_oa ? 'Open access' : 'Not open access'}${work.oa_status ? ` (${work.oa_status})` : ''}` : '';
    rows.push(`<dt>OpenAlex</dt><dd>${enrichment.work_id
      ? `${safeLink(`https://openalex.org/${encodeURIComponent(enrichment.work_id)}`, enrichment.work_id)} · ${esc(plural(enrichment.citation_count ?? work?.citation_count ?? 0, 'citation'))}${access ? ` · ${esc(access)}` : ''}`
      : esc(`Not matched (${enrichment.status})`)}</dd>`);
    if (topics.length) rows.push(`<dt>Topics</dt><dd>${esc(topics.join(', '))}</dd>`);
    if (list(enrichment.institutions).length) rows.push(`<dt>Institutions</dt><dd>${esc(list(enrichment.institutions).join(', '))}</dd>`);
    const where = work ? list(work.locations).filter((l) => l.landing_page_url || l.pdf_url) : [];
    if (where.length) {
      rows.push(`<dt>Open access copies</dt><dd>${where.map((l) => [
        l.landing_page_url ? safeLink(l.landing_page_url, l.source_name || 'Landing page') : '',
        l.pdf_url ? safeLink(l.pdf_url, 'PDF') : '',
      ].filter(Boolean).join(' · ')).join('<br>')}</dd>`);
    }
  }
  const source = paper.source === 'pubmed' ? 'From PubMed' : 'Uploaded or stored file';
  return `<p class="eyebrow">${esc(source)}</p><h2 id="res-paper-title" tabindex="-1">${esc(paper.title)}</h2>
    <dl class="details">${rows.join('')}</dl>`;
}

export function ranRows(detail, { modelName = (id) => id, href }) {
  return detail.ran.map((g) => {
    const requests = g.request_ids.length
      ? g.request_ids.map((id) => `<a href="${esc(href('runs', [id]))}">${esc(id.slice(0, 8))}</a>`).join(', ')
      : '<span class="muted">—</span>';
    return `<tr><td>${esc(g.prompt_name)}<small>version ${esc(versionTag(g.prompt_id))}${g.prompt_registered_at ? ` · saved ${esc(formatDate(g.prompt_registered_at))}` : ''}</small></td>`
      + `<td>${esc(modelName(g.model_id) || 'unknown')}</td>`
      + `<td>${formatNumber(g.succeeded)}${g.failed ? ` <span class="bad">· ${formatNumber(g.failed)} failed</span>` : ''}</td>`
      + `<td>${formatNumber(g.item_count)}${g.relation_count ? `<small>${esc(plural(g.relation_count, 'relation'))}</small>` : ''}</td>`
      + `<td>${requests}<small>${esc(formatDate(g.last_completed_at, ''))}</small></td></tr>`;
  });
}

function renderItem(item) {
  if (item.relations?.length) {
    return `<div class="relations">${item.relations.map((r, i) => renderRelation(r, '', i, item.relations.length, '')).join('')}</div>`;
  }
  return renderExtraction(item.text, '', '');
}

// The chunks a group touched, in reading order: each with its items and failures.
export function byChunk(group, chunks) {
  const rows = new Map();
  const row = (chunkId) => {
    if (!rows.has(chunkId)) {
      const chunk = chunks[chunkId] || {};
      rows.set(chunkId, { chunk_id: chunkId, seq: chunk.seq ?? null, chunker_id: chunk.chunker_id, text: chunk.text, items: [], failures: [] });
    }
    return rows.get(chunkId);
  };
  for (const item of group.items) row(item.chunk_id).items.push(item);
  for (const failure of group.failures) row(failure.chunk_id).failures.push(failure);
  return [...rows.values()].sort((a, b) => (a.seq ?? Infinity) - (b.seq ?? Infinity) || String(a.chunk_id).localeCompare(String(b.chunk_id)));
}

function chunkHead(row) {
  return `<h3>Chunk ${row.seq == null ? '(unknown position)' : `#${esc(row.seq)}`}</h3>
    ${row.text ? `<details><summary>Show the chunk</summary><div class="context">${esc(row.text)}</div></details>` : ''}`;
}

function failureHtml(failure) {
  return `<div class="failure">${statusPill('failed', 'Failed')} ${esc(failure.error || 'No error recorded.')}
    ${failure.raw_excerpt ? `<details><summary>What the model returned</summary><div class="context">${esc(failure.raw_excerpt)}</div></details>` : ''}</div>`;
}

// `limit` caps the items drawn; the rest wait for "Show all".
export function groupHtml(group, chunks, limit = Infinity) {
  if (!group.items.length && !group.failures.length) {
    return `<p class="empty">This version and model ran on ${esc(plural(group.succeeded, 'chunk'))} of the paper and found nothing.</p>`;
  }
  let left = limit;
  const parts = [];
  for (const row of byChunk(group, chunks)) {
    if (left <= 0) break;
    const items = row.items.slice(0, left);
    left -= items.length;
    parts.push(`<article class="try-chunk">${chunkHead(row)}
      ${items.length ? `<ol class="try-items">${items.map((item) => `<li>${renderItem(item)}</li>`).join('')}</ol>` : ''}
      ${row.failures.map(failureHtml).join('')}</article>`);
  }
  return parts.join('');
}

// Two groups aligned by chunk. An item found by both (same text) is marked.
export function compareRows(a, b, chunks) {
  const textsOf = (group) => new Set(group.items.map((item) => item.text));
  const inA = textsOf(a);
  const inB = textsOf(b);
  const shared = new Set([...inA].filter((text) => inB.has(text)));
  const rows = new Map();
  for (const [side, group] of [['a', a], ['b', b]]) {
    for (const row of byChunk(group, chunks)) {
      if (!rows.has(row.chunk_id)) {
        const { chunk_id: chunkId, seq, chunker_id: chunkerId, text } = row;
        rows.set(chunkId, { chunk_id: chunkId, seq, chunker_id: chunkerId, text, a: { items: [], failures: [] }, b: { items: [], failures: [] } });
      }
      rows.get(row.chunk_id)[side] = { items: row.items, failures: row.failures };
    }
  }
  const sorted = [...rows.values()].sort((x, y) => (x.seq ?? Infinity) - (y.seq ?? Infinity) || String(x.chunk_id).localeCompare(String(y.chunk_id)));
  return {
    rows: sorted,
    shared,
    summary: {
      a: a.item_count, b: b.item_count, shared: shared.size,
      onlyA: [...inA].filter((text) => !inB.has(text)).length,
      onlyB: [...inB].filter((text) => !inA.has(text)).length,
      chunks: sorted.length,
    },
  };
}

export function compareHtml(a, b, chunks, { modelName = (id) => id } = {}) {
  if (groupKey(a) === groupKey(b)) return '<p class="empty">Choose two different versions or models to compare.</p>';
  const { rows, shared, summary } = compareRows(a, b, chunks);
  const side = (found) => {
    const items = found.items.map((item) => `<li${shared.has(item.text) ? ' class="same"' : ''}>${renderItem(item)}${shared.has(item.text) ? '<small class="muted">Also found by the other</small>' : ''}</li>`);
    return `${items.length ? `<ol class="try-items">${items.join('')}</ol>` : (found.failures.length ? '' : '<p class="muted">Nothing found here.</p>')}${found.failures.map(failureHtml).join('')}`;
  };
  const head = `<p class="msg" role="status">${esc(groupLabel(a, modelName))}: ${esc(plural(summary.a, 'item'))}. ${esc(groupLabel(b, modelName))}: ${esc(plural(summary.b, 'item'))}. ${esc(summary.shared)} found by both, ${esc(summary.onlyA)} only by the first, ${esc(summary.onlyB)} only by the second.</p>`;
  if (!rows.length) return `${head}<p class="empty">Neither found anything in this paper.</p>`;
  return head + rows.map((row) => `<article class="try-chunk">${chunkHead(row)}
    <div class="compare"><div><h4>${esc(groupLabel(a, modelName))}</h4>${side(row.a)}</div><div><h4>${esc(groupLabel(b, modelName))}</h4>${side(row.b)}</div></div></article>`).join('');
}
