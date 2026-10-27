// Document previews shared by Collections and Runs: what a run over some
// storage folders, or over a PubMed search, would read.

import { phases } from './api.js';
import { emptyRow, esc, latest, message, plural } from './ui.js';

const stateOf = (doc) => (!doc.supported
  ? '<span class="pill neutral">not a document</span>'
  : doc.already_ingested
    ? '<span class="pill ok">ingested</span>'
    : '<span class="pill progress">new</span>');

export function documentPreview(body, summary, folderName = (prefix) => prefix) {
  const guard = latest();

  function start(text) {
    const token = guard.next();
    body.replaceChildren();
    message(summary, text);
    return token;
  }

  return {
    clear(text) { start(text); },

    async storage(locations) {
      const token = start(locations.length ? 'Reading documents...' : 'Choose storage folders to preview their documents.');
      if (!locations.length) return;
      try {
        const query = locations.map((l) => `location=${encodeURIComponent(l)}`).join('&');
        const preview = await phases(`/documents?${query}`);
        if (!guard.is(token)) return;
        const fresh = preview.ingestable - preview.already_ingested;
        const failed = preview.failed_locations || [];
        message(summary,
          `${plural(preview.total, 'object')}: ${fresh} new, ${preview.already_ingested} already ingested, ${preview.unsupported} unsupported.`
          + (preview.truncated ? ` Showing the first ${preview.documents.length}.` : '')
          + (failed.length ? ` Could not read: ${failed.map(folderName).join('; ')}` : ''),
          failed.length ? 'warn' : '');
        if (!preview.documents.length) body.innerHTML = emptyRow(4, 'No documents in these folders yet. Upload PDFs from Collections.');
        for (const doc of preview.documents) {
          const row = document.createElement('tr');
          row.innerHTML = `<td>${esc(doc.name)}</td><td class="muted">${esc(folderName(doc.location))}</td><td class="muted"><code>${esc(doc.key)}</code></td><td>${stateOf(doc)}</td>`;
          body.append(row);
        }
      } catch (error) {
        if (guard.is(token)) message(summary, error.message, 'bad');
      }
    },

    async pubmed(queryId) {
      const token = start(queryId ? 'Reading published papers...' : 'Choose a PubMed search to preview its papers.');
      if (!queryId) return;
      try {
        const data = await phases(`/sources/pubmed/${encodeURIComponent(queryId)}`);
        if (!guard.is(token)) return;
        if (!data.artifacts.length) body.innerHTML = emptyRow(4, 'No published papers for this search yet. Download papers from the Library first.');
        for (const artifact of data.artifacts) {
          const row = document.createElement('tr');
          row.innerHTML = `<td>${esc(artifact.title)}</td><td class="muted">${esc(artifact.storage_prefix)}</td><td class="muted"><code>${esc(artifact.storage_key)}</code></td><td><span class="pill ok">published</span></td>`;
          body.append(row);
        }
        message(summary, `${plural(data.artifacts.length, 'published artifact')}. The run keeps exactly this selection when you submit it.`);
      } catch (error) {
        if (guard.is(token)) message(summary, error.message, 'bad');
      }
    },
  };
}
