// Rendering of one extracted finding: probability relations as small graphs,
// other JSON as formatted JSON, plain text as text. Keyword matches are marked.

import { esc } from '../ui.js';

export function keywordTerms(query) {
  const terms = [];
  for (const match of String(query || '').toLowerCase().replace(/[“”]/g, '"').matchAll(/"([^"]*)"|([\p{L}\p{N}_]+)/gu)) {
    const text = (match[1] === undefined ? match[2] : match[1]).trim();
    if (text) terms.push({ text, exact: match[1] !== undefined });
  }
  return terms;
}

// Quoted words match whole words; quoted phrases match across any whitespace.
export function highlight(text, query, mode) {
  if (mode !== 'keyword' || !text) return esc(text);
  const terms = keywordTerms(query).sort((a, b) => b.text.length - a.text.length);
  if (!terms.length) return esc(text);
  const escapeRegex = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const patterns = terms.map((term) => (term.exact
    ? `(?<![\\p{L}\\p{N}_])${term.text.split(/\s+/).map(escapeRegex).join('\\s+')}(?![\\p{L}\\p{N}_])`
    : escapeRegex(term.text)));
  const re = new RegExp(`(${patterns.join('|')})`, 'giu');
  return String(text).split(re).map((part, i) => (i % 2 ? `<mark>${esc(part)}</mark>` : esc(part))).join('');
}

export function parsePayload(text) {
  try { return JSON.parse(text); } catch { return undefined; }
}

// Only a payload made entirely of valid relations is drawn as relations.
export function probabilisticRelations(payload) {
  const relations = Array.isArray(payload) ? payload
    : payload && Array.isArray(payload.relations) ? payload.relations : [payload];
  const valid = (r) => r && typeof r === 'object'
    && ['subject_process', 'subject_participant', 'target_process'].every((key) => typeof r[key] === 'string' && r[key].trim())
    && ['increases', 'decreases', 'no-effect'].includes(r.direction)
    && (r.evidence_text == null || typeof r.evidence_text === 'string');
  return relations.length && relations.every(valid) ? relations : [];
}

const DIRECTIONS = { increases: 'Increases', decreases: 'Decreases', 'no-effect': 'Neutral (no effect)' };

export function renderRelation(r, query, index, total, mode) {
  const node = (role, type, text) => `<div class="graph-node">
    <span class="node-role">${role}</span><span class="node-type">${type}</span>
    <div class="node-text">${highlight(text, query, mode)}</div></div>`;
  return `<figure class="relation">
    <figcaption>Probability-modulating claim${total > 1 ? ` ${index + 1} of ${total}` : ''}</figcaption>
    <div class="participant-branch">
      ${node('Participant / disposition bearer', 'Independent continuant', r.subject_participant)}
      <span class="participant-link">participates in</span>
    </div>
    <div class="relation-flow">
      ${node('From / subject', 'Process', r.subject_process)}
      <div class="relation-edge ${r.direction}"><strong>${DIRECTIONS[r.direction]}</strong>
        ${r.direction === 'no-effect' ? 'on the probability of' : 'the probability of'}
        <span class="edge-arrow" aria-hidden="true"></span></div>
      ${node('To / target', 'Process', r.target_process)}
    </div>
    ${r.evidence_text ? `<blockquote class="evidence"><span class="evidence-label">Evidence from the paper</span>${highlight(r.evidence_text, query, mode)}</blockquote>` : ''}
  </figure>`;
}

export function renderExtraction(text, query, mode) {
  const payload = parsePayload(text);
  const relations = probabilisticRelations(payload);
  if (relations.length) return `<div class="relations">${relations.map((r, i) => renderRelation(r, query, i, relations.length, mode)).join('')}</div>`;
  if (payload !== undefined) return `<pre class="json-payload">${highlight(JSON.stringify(payload, null, 2), query, mode)}</pre>`;
  return `<div class="hit-text">${highlight(text, query, mode)}</div>`;
}
