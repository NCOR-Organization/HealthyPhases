// Document previews shared by Collections and Runs: what a run over some
// storage folders, a PubMed search or a collection would read.

import { phases } from './api.js';
import { emptyRow, esc, latest, message, plural } from './ui.js';

const COLLECTION_STATES = {
  not_ingested: '<span class="pill progress">new</span>',
  ingested: '<span class="pill ok">ingested</span>',
  results: '<span class="pill ok">has results</span>',
};

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

    // A collection's papers as they resolve now: the exact selection a run would get.
    async collection(collectionId) {
      const token = start(collectionId ? 'Reading the collection...' : 'Choose a collection to preview its papers.');
      if (!collectionId) return undefined;
      try {
        const data = await phases(`/collections/${encodeURIComponent(collectionId)}`);
        if (!guard.is(token)) return undefined;
        if (!data.papers.length) body.innerHTML = emptyRow(4, 'This collection has no papers yet. Add papers from Collections.');
        for (const paper of data.papers) {
          const row = document.createElement('tr');
          const folder = paper.path.includes('/') ? paper.path.slice(0, paper.path.lastIndexOf('/')) : '';
          row.innerHTML = `<td>${esc(paper.name)}</td><td class="muted">${esc(folderName(folder))}</td><td class="muted"><code>${esc(paper.path)}</code></td><td>${COLLECTION_STATES[paper.status] || esc(paper.status)}</td>`;
          body.append(row);
        }
        const counts = data.status_counts || {};
        const failed = (data.members || []).filter((m) => m.error);
        message(summary,
          `${plural(data.paper_count, 'paper')}: ${counts.not_ingested || 0} new, ${(counts.ingested || 0) + (counts.results || 0)} already ingested.`
          + (data.truncated ? ` Showing the first ${data.papers.length}.` : '')
          + (failed.length
            ? ` Could not read: ${failed.map((m) => m.label).join('; ')}. Fix or remove these members before running.`
            : ' The run keeps exactly these papers when you submit it.'),
          failed.length ? 'warn' : '');
        return data;
      } catch (error) {
        if (guard.is(token)) message(summary, error.message, 'bad');
        return undefined;
      }
    },
  };
}
