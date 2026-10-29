// Line diff of two prompt texts: the longest common subsequence of lines, with
// the shared start and end trimmed first so a small edit to a long template
// stays cheap.

import { esc } from './ui.js';

// Above this many line pairs the middle is shown as removed then added rather
// than aligned, which keeps a pathological pair from freezing the page.
const MAX_CELLS = 4_000_000;

const lines = (text) => String(text ?? '').replace(/\r\n?/g, '\n').split('\n');

// [{ type: 'same' | 'del' | 'add', text }], in reading order.
export function lineDiff(before, after) {
  const a = lines(before);
  const b = lines(after);
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start += 1;
  let endA = a.length;
  let endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) { endA -= 1; endB -= 1; }

  const head = a.slice(0, start).map((text) => ({ type: 'same', text }));
  const tail = a.slice(endA).map((text) => ({ type: 'same', text }));
  const x = a.slice(start, endA);
  const y = b.slice(start, endB);
  return [...head, ...middle(x, y), ...tail];
}

function middle(x, y) {
  if (!x.length || !y.length || x.length * y.length > MAX_CELLS) {
    return [...x.map((text) => ({ type: 'del', text })), ...y.map((text) => ({ type: 'add', text }))];
  }
  const width = y.length + 1;
  const table = new Uint32Array((x.length + 1) * width);
  for (let i = x.length - 1; i >= 0; i -= 1) {
    for (let j = y.length - 1; j >= 0; j -= 1) {
      table[i * width + j] = x[i] === y[j]
        ? table[(i + 1) * width + j + 1] + 1
        : Math.max(table[(i + 1) * width + j], table[i * width + j + 1]);
    }
  }
  const out = [];
  let i = 0;
  let j = 0;
  while (i < x.length && j < y.length) {
    if (x[i] === y[j]) { out.push({ type: 'same', text: x[i] }); i += 1; j += 1; }
    else if (table[(i + 1) * width + j] >= table[i * width + j + 1]) { out.push({ type: 'del', text: x[i] }); i += 1; }
    else { out.push({ type: 'add', text: y[j] }); j += 1; }
  }
  while (i < x.length) out.push({ type: 'del', text: x[i++] });
  while (j < y.length) out.push({ type: 'add', text: y[j++] });
  return out;
}

export function diffSummary(ops) {
  const added = ops.filter((op) => op.type === 'add').length;
  const removed = ops.filter((op) => op.type === 'del').length;
  if (!added && !removed) return 'The two texts are identical.';
  return `${added} line${added === 1 ? '' : 's'} added, ${removed} line${removed === 1 ? '' : 's'} removed.`;
}

const MARKS = { same: ' ', del: '-', add: '+' };

// Each line is a block, so they are joined with nothing: a newline would show twice.
export function diffHtml(ops) {
  return ops.map((op) => `<span class="diff-${op.type}"><span class="diff-mark" aria-hidden="true">${MARKS[op.type]}</span>${op.type === 'same' ? '' : `<span class="sr-only">${op.type === 'add' ? 'added: ' : 'removed: '}</span>`}${esc(op.text) || ' '}</span>`).join('');
}
