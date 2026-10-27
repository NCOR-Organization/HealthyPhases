// Collections: named groups of storage folders, the folders themselves and PDF uploads.
//
// #/collections opens the first collection, #/collections/<id> a given one and
// #/collections/new an empty form.

import { phases } from '../api.js';
import { documentPreview } from '../documents.js';
import { $, action, emptyState, esc, fill, message, plural, selected, selectValues, tableHtml } from '../ui.js';

export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

const template = () => `
  <header class="page-head"><p class="eyebrow">Step 1 · Collect papers</p><h1 tabindex="-1">Collections</h1>
    <p class="lede">Group storage folders into reusable collections, add folders and upload your own PDFs.</p></header>
  <div class="split">
    <section class="card">
      <div class="card-head"><h2>Your collections</h2><button id="col-new" type="button">New collection</button></div>
      <div id="col-list" class="resource-list" aria-label="Collections"></div>
    </section>
    <div class="stack">
      <section class="card">
        <h2 id="col-title">New collection</h2>
        <form id="col-form">
          <div class="stack">
            <div><label for="col-name">Collection name</label><input id="col-name" required maxlength="120" placeholder="e.g. Solitude research"></div>
            <div><label for="col-locations">Storage folders</label><select id="col-locations" multiple required></select>
              <p class="hint">A collection includes the documents in each folder and its subfolders. Use Ctrl or Command to select several.</p></div>
          </div>
          <div class="row actions"><button class="primary" id="col-save">Save collection</button><button type="button" id="col-use" disabled>Use in a new run</button><button type="button" id="col-archive" class="danger" hidden>Archive collection</button></div>
          <p id="col-message" class="msg" role="status"></p>
        </form>
      </section>
      <section class="card">
        <h2>Collection contents</h2>
        <p id="col-documents-summary" class="msg" role="status">Choose storage folders to see the collection contents.</p>
        ${tableHtml('col-documents', ['Document', 'Folder', 'Path', 'State'], 'Collection contents', true)}
      </section>
    </div>
  </div>
  <section class="card">
    <h2>Storage folders and uploads</h2>
    <div class="grid">
      <div><label for="col-location-name">New storage folder</label>
        <div class="row"><input id="col-location-name" class="grow" maxlength="100" placeholder="e.g. Solitude papers"><button id="col-create-location" type="button">Create folder</button></div>
        <p class="hint">A new folder is added to the collection you are editing.</p>
        <p id="col-location-message" class="msg" role="status"></p></div>
      <div><label for="col-upload-location">Upload PDFs to</label><select id="col-upload-location"></select>
        <label for="col-upload-files" class="spaced">PDF documents (up to 25 MiB each)</label><input id="col-upload-files" type="file" accept="application/pdf,.pdf" multiple>
        <div class="row actions"><button id="col-upload" type="button" class="primary">Upload PDFs</button></div>
        <p class="hint">Uploading does not start a run. Retrying the same file is safe.</p>
        <p id="col-upload-message" class="msg pre" role="status"></p></div>
    </div>
  </section>`;

export function create(root, ctx) {
  root.innerHTML = template();
  const state = { collections: [], locations: [], collectionId: '', current: '', loaded: false };
  const folderName = (prefix) => state.locations.find((l) => l.prefix === prefix)?.name || prefix;
  const preview = documentPreview($('col-documents'), $('col-documents-summary'), folderName);

  function renderCollections() {
    $('col-list').replaceChildren();
    if (!state.collections.length) {
      $('col-list').innerHTML = emptyState('No collections yet. Name one, choose its storage folders and save it to reuse it in runs.');
    }
    for (const collection of state.collections) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'resource';
      button.setAttribute('aria-pressed', String(collection.collection_id === state.collectionId));
      button.innerHTML = `${esc(collection.name)}<small>${plural(collection.locations.length, 'storage folder')}</small>`;
      button.addEventListener('click', () => ctx.navigate(ctx.href('collections', [collection.collection_id])));
      $('col-list').append(button);
    }
  }

  function refreshDocuments() {
    return preview.storage(selected($('col-locations')));
  }

  function edit(collection) {
    state.collectionId = collection?.collection_id || '';
    $('col-name').value = collection?.name || '';
    selectValues($('col-locations'), collection?.locations || [], folderName);
    $('col-title').textContent = collection ? `Edit ${collection.name}` : 'New collection';
    $('col-archive').hidden = !collection;
    $('col-use').disabled = !collection;
    message('col-message');
    renderCollections();
    return refreshDocuments();
  }

  function fillLocations(pickUpload) {
    const chosen = selected($('col-locations'));
    fill($('col-locations'), state.locations, 'prefix', (l) => l.name, chosen);
    selectValues($('col-locations'), chosen, folderName);
    const upload = pickUpload || $('col-upload-location').value;
    fill($('col-upload-location'), state.locations, 'prefix', (l) => l.name, upload ? [upload] : undefined);
  }

  async function reload() {
    const [locations, collections] = await Promise.all([phases('/locations'), phases('/collections')]);
    state.locations = locations.locations;
    state.collections = collections.collections;
    state.loaded = true;
    fillLocations();
    renderCollections();
  }

  async function save() {
    const payload = { name: $('col-name').value.trim(), locations: selected($('col-locations')) };
    if (!payload.locations.length) throw new Error('Choose at least one storage folder.');
    const saved = await phases(state.collectionId ? `/collections/${encodeURIComponent(state.collectionId)}` : '/collections', {
      method: state.collectionId ? 'PUT' : 'POST', body: payload,
    });
    state.collections = (await phases('/collections')).collections;
    await edit(saved);
    state.current = saved.collection_id;
    ctx.replace(ctx.href('collections', [saved.collection_id]));
    message('col-message', 'Collection saved.', 'ok');
    ctx.toast(`Collection "${saved.name}" saved.`);
    return saved;
  }

  async function archive() {
    const collection = state.collections.find((c) => c.collection_id === state.collectionId);
    if (!collection) return false;
    const archived = await ctx.confirm({
      title: `Archive "${collection.name}"?`,
      body: ['The collection disappears from this list and from new runs.', 'Its storage folders, documents and any queued runs are kept.'],
      confirmLabel: 'Archive collection',
      danger: true,
      run: () => phases(`/collections/${encodeURIComponent(collection.collection_id)}`, { method: 'DELETE' }),
    });
    if (!archived) return false;
    state.collections = (await phases('/collections')).collections;
    state.current = 'new';
    ctx.replace(ctx.href('collections', ['new']));
    await edit(null);
    message('col-message', 'Collection archived. Its documents and queued runs are kept.', 'ok');
    return true;
  }

  function useInRun() {
    const locations = selected($('col-locations'));
    const saved = state.collections.find((c) => c.collection_id === state.collectionId);
    const matches = saved && saved.locations.length === locations.length && saved.locations.every((l) => locations.includes(l));
    ctx.section('runs').useLocations(locations, matches ? saved.collection_id : '');
    ctx.navigate(ctx.href('runs', ['new']));
  }

  async function createLocation() {
    const location = await phases('/locations', { method: 'POST', body: { name: $('col-location-name').value.trim() } });
    state.locations = (await phases('/locations')).locations;
    fillLocations(location.prefix);
    selectValues($('col-locations'), [...new Set([...selected($('col-locations')), location.prefix])], folderName);
    $('col-location-name').value = '';
    refreshDocuments();
    message('col-location-message', 'Storage folder created and added to the collection you are editing.', 'ok');
  }

  // Each file reports its own outcome; one failure does not stop the others.
  async function upload() {
    const files = [...($('col-upload-files').files || [])];
    const location = $('col-upload-location').value;
    if (!files.length || !location) throw new Error('Choose a storage folder and at least one PDF.');
    const outcomes = [];
    let failed = false;
    for (const file of files) {
      try {
        if (file.size > MAX_UPLOAD_BYTES) throw new Error('larger than 25 MiB');
        await phases(`/documents?location=${encodeURIComponent(location)}&filename=${encodeURIComponent(file.name)}`, {
          method: 'POST', body: file, raw: true, contentType: 'application/pdf',
        });
        outcomes.push(`${file.name}: uploaded`);
      } catch (error) {
        failed = true;
        outcomes.push(`${file.name}: failed - ${error.message}`);
      }
      message('col-upload-message', outcomes.join('\n'), failed ? 'warn' : 'ok');
    }
    state.locations = (await phases('/locations')).locations;
    fillLocations(location);
    refreshDocuments();
    return outcomes;
  }

  $('col-new').addEventListener('click', () => ctx.navigate(ctx.href('collections', ['new'])));
  $('col-locations').addEventListener('change', refreshDocuments);
  $('col-form').addEventListener('submit', (event) => { event.preventDefault(); action($('col-save'), 'col-message', save); });
  $('col-use').addEventListener('click', useInRun);
  $('col-archive').addEventListener('click', () => action($('col-archive'), 'col-message', archive));
  $('col-create-location').addEventListener('click', () => action($('col-create-location'), 'col-location-message', createLocation));
  $('col-upload').addEventListener('click', () => action($('col-upload'), 'col-upload-message', upload));

  function select(id) {
    if (id === 'new') return edit(null);
    const collection = state.collections.find((c) => c.collection_id === id) || (!id && state.collections[0]);
    if (!collection) {
      const shown = edit(null);
      if (id) message('col-message', 'That collection no longer exists. It may have been archived.', 'warn');
      return shown;
    }
    if (!id) ctx.replace(ctx.href('collections', [collection.collection_id]));
    return edit(collection);
  }

  // `entering` means coming back from another section: the lists are re-read first,
  // so anything created elsewhere is there, and an open draft is kept. Within the
  // section, following a link to what is already open (New, or a list item) re-renders it.
  async function show(route, { entering = false } = {}) {
    const id = route.parts[0] || '';
    if (!state.loaded || entering) {
      try { await reload(); } catch (error) { message('col-message', `Could not load collections: ${error.message}`, 'bad'); if (!state.loaded) return; }
    }
    // The sidebar link has no id: come back to what was open, draft included.
    if (!id && state.current) { ctx.replace(ctx.href('collections', [state.current])); return; }
    if (entering && state.current && id === state.current) return;
    state.current = id || '';
    await select(id);
    if (!id) state.current = state.collectionId || 'new';
  }

  // Keeps an unsaved draft: only the lists and the contents preview are re-read.
  async function refresh() {
    try {
      await reload();
      refreshDocuments();
    } catch (error) {
      message('col-message', `Could not refresh collections: ${error.message}`, 'bad');
    }
  }

  return { show, hide() {}, refresh, state, actions: { save, archive, useInRun, createLocation, upload, edit, reload } };
}
