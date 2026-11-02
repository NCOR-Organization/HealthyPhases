// Shared UI helpers. Every value from the API reaches markup through esc().

export const $ = (id) => document.getElementById(id);

export const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
}[c]));

export function plural(count, one, many = `${one}s`) {
  return `${count} ${count === 1 ? one : many}`;
}

export function formatNumber(value) {
  return Number(value ?? 0).toLocaleString();
}

export function formatDate(value, fallback = '—') {
  if (!value) return fallback;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

const node = (target) => (typeof target === 'string' ? $(target) : target);

export function message(target, text = '', kind = '') {
  const el = node(target);
  if (!el) return;
  el.textContent = text;
  el.className = `msg ${kind}`.trim();
}

// Runs one user action: the button is disabled while it runs and any failure is
// shown next to it, so a retry is always possible.
export async function action(button, target, work) {
  if (button) button.disabled = true;
  message(target);
  try {
    return await work();
  } catch (error) {
    message(target, error?.message || String(error), 'bad');
    return undefined;
  } finally {
    if (button) button.disabled = false;
  }
}

// A counter that lets a late response notice it has been superseded.
export function latest() {
  let version = 0;
  return { next: () => ++version, is: (token) => token === version };
}

const TONES = {
  pending: 'neutral', queued: 'neutral', idle: 'neutral', not_enriched: 'neutral',
  running: 'progress', waiting: 'progress',
  succeeded: 'ok', completed: 'ok', ready: 'ok', enriched: 'ok', published: 'ok', enabled: 'ok',
  partial: 'warn', ambiguous: 'warn', no_match: 'warn', unavailable: 'warn', disabled: 'neutral',
  failed: 'bad',
};

export function tone(status) {
  return TONES[String(status || '').toLowerCase()] || 'neutral';
}

export function statusPill(status, label = status) {
  return `<span class="pill ${tone(status)}">${esc(label || 'unknown')}</span>`;
}

export function emptyRow(columns, text) {
  return `<tr><td colspan="${columns}" class="empty">${esc(text)}</td></tr>`;
}

// An empty state names the next step; `link` is an optional [href, label].
export function emptyState(text, link) {
  const next = link ? ` <a href="${esc(link[0])}">${esc(link[1])}</a>` : '';
  return `<p class="empty">${esc(text)}${next}</p>`;
}

// `scroll` caps the height for long secondary lists, such as document previews.
export function tableHtml(bodyId, headers, caption = '', scroll = false) {
  return `<div class="table-wrap${scroll ? ' scroll' : ''}"><table>${caption ? `<caption class="sr-only">${esc(caption)}</caption>` : ''}<thead><tr>${headers.map((h) => `<th scope="col">${esc(h)}</th>`).join('')}</tr></thead><tbody id="${bodyId}"></tbody></table></div>`;
}

export function selected(select) {
  return [...(select?.selectedOptions || [])].map((option) => option.value);
}

// Options for a <select>. Items marked available: false stay visible but cannot be chosen.
export function fill(select, items, value, label, chosen) {
  select.replaceChildren();
  for (const item of items) {
    const option = document.createElement('option');
    option.value = item[value];
    option.textContent = label(item);
    if (item.available === false) {
      option.disabled = true;
      option.textContent += ' - unavailable here';
    }
    option.selected = chosen ? chosen.includes(option.value) : false;
    select.append(option);
  }
  if (!select.multiple) {
    const pick = chosen && [...select.options].find((option) => chosen.includes(option.value) && !option.disabled);
    const first = pick || [...select.options].find((option) => !option.disabled);
    if (first) select.value = first.value; else select.selectedIndex = -1;
  }
}

// Selects exactly `values`, adding options for any the list does not offer yet.
export function selectValues(select, values, label = (value) => value) {
  for (const value of values) {
    if (![...select.options].some((option) => option.value === value)) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = label(value);
      select.append(option);
    }
  }
  for (const option of select.options) option.selected = values.includes(option.value);
}

// Previous/next/go state for a page of `pages`.
export function pagination(page, pages, loading = false) {
  return {
    prev: loading || pages === 0 || page <= 1,
    next: loading || page >= pages,
    go: loading || pages <= 1,
    label: pages > 0 ? `Page ${page} of ${pages}` : 'Page 1 of 1',
  };
}

export function toast(text, kind = 'ok') {
  const region = $('toasts');
  if (!region) return;
  const item = document.createElement('div');
  item.className = `toast ${kind}`;
  item.textContent = text;
  region.append(item);
  setTimeout(() => item.remove(), 6000);
}

// A confirmation dialog for destructive or costly actions. `run` does the work
// once confirmed; if it fails the dialog stays open with the error, ready to retry.
// While it is sending, Cancel and Escape do nothing: the outcome is not known yet,
// and reporting "cancelled" for work that then happens invites a duplicate.
// Resolves true once the work succeeded, false when the user cancels.
export function confirmAction({ title, body = [], confirmLabel, danger = false, option, run = async () => {} }) {
  const dialog = $('confirm-dialog');
  const confirm = $('confirm-ok');
  const optionRow = $('confirm-option');
  const optionInput = $('confirm-option-input');
  $('confirm-title').textContent = title;
  const text = $('confirm-body');
  text.replaceChildren();
  for (const paragraph of [].concat(body)) {
    const p = document.createElement('p');
    p.textContent = paragraph;
    text.append(p);
  }
  optionRow.hidden = !option;
  optionInput.checked = Boolean(option?.checked);
  $('confirm-option-label').textContent = option?.label || '';
  confirm.textContent = confirmLabel;
  confirm.className = danger ? 'danger-solid' : 'primary';
  confirm.disabled = false;
  message('confirm-error');

  const cancel = $('confirm-cancel');
  cancel.disabled = false;

  return new Promise((resolve) => {
    let settled = false;
    let sending = false;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      dialog.onclose = null;
      dialog.oncancel = null;
      if (dialog.open) dialog.close();
      resolve(result);
    };
    dialog.oncancel = (event) => { if (sending) event.preventDefault(); };
    dialog.onclose = () => { if (!sending) finish(false); };
    cancel.onclick = () => { if (!sending) finish(false); };
    confirm.onclick = async () => {
      if (sending) return;
      sending = true;
      confirm.disabled = true;
      cancel.disabled = true;
      message('confirm-error');
      try {
        await run(optionInput.checked);
        sending = false;
        finish(true);
      } catch (error) {
        sending = false;
        message('confirm-error', error?.message || String(error), 'bad');
        // Closed some other way while sending: the work failed, so this is a cancel.
        if (!dialog.open) finish(false);
      } finally {
        confirm.disabled = false;
        cancel.disabled = false;
      }
    };
    dialog.showModal();
    cancel.focus();
  });
}
