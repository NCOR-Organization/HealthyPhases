// Collections: sets of papers gathered from uploads, PubMed searches, storage folders and the library.
//
// #/collections opens the first collection, #/collections/<id> a given one and
// #/collections/new the create form. On the create form, added papers and PDFs
// wait on the page and are sent when the collection is created; on a saved
// collection every addition is sent straight away.

import { phases, pubmed } from '../api.js';
import {
  $, action, emptyRow, emptyState, esc, fill, formatDate, message, plural, statusPill, tableHtml,
} from '../ui.js';

export const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;
const NEW = '__new__';

export const KINDS = { folder: 'Folder', pubmed_query: 'PubMed search', paper: 'Paper', upload: 'PDF to upload' };
export const STATUSES = {
  not_ingested: ['idle', 'Not ingested yet'],
  ingested: ['ready', 'Ingested'],
  results: ['succeeded', 'Has results'],
};

const commandKind = (command) => Object.keys(command)[0];
const commandKey = (command) => JSON.stringify(command);

export function collectionSummary(c) {
  const parts = [plural(c.member_count ?? c.members?.length ?? 0, 'member')];
  if (c.paper_count != null) parts.push(plural(c.paper_count, 'paper'));
  if (c.updated_at) parts.push(`updated ${formatDate(c.updated_at)}`);
  return parts.join(' · ');
}

const template = () => `
  <header class="page-head"><p class="eyebrow">Step 1 · Collect papers</p><h1 tabindex="-1">Collections</h1>
    <p class="lede">Gather papers from PubMed searches, your own PDFs, storage folders and the library into one collection, then run the pipeline or search within it.</p></header>
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
            <div><label for="col-description">Description <span class="hint">(optional)</span></label><textarea id="col-description" class="short" rows="2" maxlength="2000" placeholder="What these papers have in common"></textarea></div>
          </div>
          <div class="row actions"><button class="primary" id="col-save">Create collection</button><button type="button" id="col-run" disabled>Run on this collection</button><a id="col-search" class="button" href="#/search" hidden>Search this collection</a><button type="button" id="col-archive" class="danger" hidden>Archive collection</button></div>
          <p id="col-message" class="msg" role="status"></p>
        </form>
      </section>
      <section class="card">
        <h2>Add papers</h2>
        <p id="col-add-hint" class="hint"></p>
        <div class="grid">
          <div><label for="col-upload-files">Upload PDFs (up to 25 MiB each)</label><input id="col-upload-files" type="file" accept="application/pdf,.pdf" multiple>
            <div class="row actions"><button id="col-upload" type="button">Upload PDFs</button></div>
            <p id="col-upload-message" class="msg pre" role="status"></p></div>
          <div><label for="col-pubmed">PubMed search</label><select id="col-pubmed"></select>
            <div class="row actions"><button id="col-add-pubmed" type="button">Add search</button><a href="#/library/search">Search PubMed</a></div>
            <p class="hint">Papers the search downloads later join the collection by themselves.</p></div>
          <div><label for="col-folder">Storage folder</label><select id="col-folder"></select>
            <div class="row actions"><button id="col-add-folder" type="button">Add folder</button></div>
            <p class="hint">A folder includes its subfolders.</p></div>
          <div><label for="col-library-q">From the library</label>
            <form id="col-library-form" class="row"><input id="col-library-q" class="grow" maxlength="300" placeholder="Title, PMID or file name"><button id="col-library-find">Find</button></form>
            <div id="col-library-results" class="resource-list" aria-label="Library papers"></div>
            <p id="col-library-message" class="msg" role="status"></p></div>
        </div>
        <p id="col-add-message" class="msg" role="status"></p>
      </section>
      <section class="card">
        <h2>Members</h2>
        ${tableHtml('col-members', ['Type', 'Member', 'Papers', 'Actions'], 'Collection members')}
      </section>
      <section class="card">
        <div class="card-head"><h2>Papers</h2><button id="col-refresh" type="button">Refresh</button></div>
        <p id="col-papers-summary" class="msg" role="status"></p>
        ${tableHtml('col-papers', ['Paper', 'Stored at', 'Status'], 'Papers in this collection', true)}
      </section>
    </div>
  </div>
  <details class="card folders-panel">
    <summary>Storage folders: create one, or upload PDFs into one</summary>
    <div class="grid">
      <div><label for="col-location-name">New storage folder</label>
        <div class="row"><input id="col-location-name" class="grow" maxlength="100" placeholder="e.g. Solitude papers"><button id="col-create-location" type="button">Create folder</button></div>
        <p class="hint">A new folder is added to the collection you are editing.</p>
        <p id="col-location-message" class="msg" role="status"></p></div>
      <div><label for="col-folder-upload-location">Upload PDFs to a folder</label><select id="col-folder-upload-location"></select>
        <label for="col-folder-upload-files" class="spaced">PDF documents (up to 25 MiB each)</label><input id="col-folder-upload-files" type="file" accept="application/pdf,.pdf" multiple>
        <div class="row actions"><button id="col-folder-upload" type="button">Upload to folder</button></div>
        <p class="hint">Uploading does not start a run. Retrying the same file is safe.</p>
        <p id="col-folder-upload-message" class="msg pre" role="status"></p></div>
    </div>
  </details>`;

export function create(root, ctx) {
  root.innerHTML = template();
  const state = {
    collections: [], locations: [], pubmedQueries: [], loaded: false,
    collectionId: '', current: '', detail: null, detailVersion: 0,
    // A new collection's additions, sent when it is created.
    draft: { members: [], files: [] },
  };
  const folderName = (prefix) => state.locations.find((l) => l.prefix === prefix)?.name || prefix;
  const saved = () => state.collections.find((c) => c.collection_id === state.collectionId);

  // ---- Lists ----

  function renderCollections() {
    $('col-list').replaceChildren();
    if (!state.collections.length) {
      $('col-list').innerHTML = emptyState('No collections yet. Name one and add papers to reuse them in runs and searches.');
    }
    for (const collection of state.collections) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'resource';
      button.setAttribute('aria-pressed', String(collection.collection_id === state.collectionId));
      button.innerHTML = `${esc(collection.name)}<small>${esc(collectionSummary(collection))}</small>`;
      button.addEventListener('click', () => ctx.navigate(ctx.href('collections', [collection.collection_id])));
      $('col-list').append(button);
    }
  }

  function fillChoices() {
    fill($('col-folder'), state.locations, 'prefix', (l) => l.name, [$('col-folder').value]);
    fill($('col-folder-upload-location'), state.locations, 'prefix', (l) => l.name, [$('col-folder-upload-location').value]);
    const searches = state.pubmedQueries.length ? state.pubmedQueries : [{ query_id: '', query: 'No saved PubMed searches yet' }];
    fill($('col-pubmed'), searches, 'query_id', (q) => (q.query_id ? `${q.query} · ${plural(q.published_paper_count ?? 0, 'downloaded paper')}` : q.query), [$('col-pubmed').value]);
    $('col-add-pubmed').disabled = !state.pubmedQueries.length;
  }

  async function loadCollections() {
    state.collections = (await phases('/collections')).collections;
    renderCollections();
  }

  async function reload() {
    const [locations, collections, searches] = await Promise.all([
      phases('/locations'), phases('/collections'),
      // A deployment without PubMed still manages folders and uploads.
      phases('/sources/pubmed').catch(() => ({ queries: [] })),
    ]);
    state.locations = locations.locations;
    state.collections = collections.collections;
    state.pubmedQueries = searches.queries || [];
    state.loaded = true;
    fillChoices();
    renderCollections();
  }

  // ---- Members and papers ----

  function memberRow(kind, label, count, onRemove, error) {
    const row = document.createElement('tr');
    const papers = count == null ? '<span class="muted">After creating</span>' : esc(count);
    row.innerHTML = `<td>${esc(KINDS[kind] || kind)}</td><td>${esc(label)}${error ? `<small class="bad">${esc(error)}</small>` : ''}</td><td>${papers}</td><td></td>`;
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'small';
    remove.textContent = 'Remove';
    remove.setAttribute('aria-label', `Remove ${label}`);
    remove.addEventListener('click', () => action(remove, 'col-add-message', onRemove));
    row.lastElementChild.append(remove);
    return row;
  }

  function renderMembers() {
    const body = $('col-members');
    body.replaceChildren();
    if (state.collectionId) {
      const members = state.detail?.members || [];
      if (!members.length) body.innerHTML = emptyRow(4, 'No members yet. Add papers above.');
      for (const m of members) {
        const label = m.kind === 'folder' && m.uploads ? 'PDFs uploaded into this collection' : m.label;
        body.append(memberRow(m.kind, label, m.paper_count, () => removeMember(m, label), m.error));
      }
      return;
    }
    const { members, files } = state.draft;
    if (!members.length && !files.length) body.innerHTML = emptyRow(4, 'Nothing added yet. Add papers in any of the four ways above.');
    for (const m of members) {
      body.append(memberRow(commandKind(m.command), m.label, null, () => {
        state.draft.members = state.draft.members.filter((d) => d !== m);
        renderMembers();
      }));
    }
    for (const file of files) {
      body.append(memberRow('upload', file.name, null, () => {
        state.draft.files = state.draft.files.filter((f) => f !== file);
        renderMembers();
      }));
    }
  }

  function renderPapers() {
    const body = $('col-papers');
    body.replaceChildren();
    const detail = state.detail;
    if (!state.collectionId || !detail) {
      message('col-papers-summary', state.collectionId ? 'Reading papers...' : 'Papers appear here once the collection is created.');
      return;
    }
    const counts = detail.status_counts || {};
    const failed = (detail.members || []).filter((m) => m.error);
    message('col-papers-summary',
      `${plural(detail.paper_count, 'paper')}: ${counts.not_ingested || 0} not ingested yet, ${counts.ingested || 0} ingested, ${counts.results || 0} with results.`
      + (detail.unsupported ? ` ${plural(detail.unsupported, 'file')} in its folders ${detail.unsupported === 1 ? 'is' : 'are'} not a PDF.` : '')
      + (detail.truncated ? ` Showing the first ${detail.papers.length}.` : '')
      + (failed.length ? ` Could not read: ${failed.map((m) => m.label).join('; ')}.` : ''),
      failed.length ? 'warn' : '');
    if (!detail.papers.length) body.innerHTML = emptyRow(3, 'No papers yet. Add papers above; a PubMed search counts its downloaded papers.');
    for (const paper of detail.papers) {
      const [tone, label] = STATUSES[paper.status] || ['idle', paper.status];
      const row = document.createElement('tr');
      const results = paper.status === 'results' ? ` (${plural(paper.results, 'result')})` : '';
      row.innerHTML = `<td>${esc(paper.name)}${paper.pmid ? `<small>PMID ${esc(paper.pmid)}</small>` : ''}</td><td class="muted"><code>${esc(paper.path)}</code></td><td>${statusPill(tone, label + results)}</td>`;
      body.append(row);
    }
  }

  async function loadDetail() {
    const id = state.collectionId;
    const version = ++state.detailVersion;
    if (!id) { state.detail = null; renderMembers(); renderPapers(); return; }
    renderPapers();
    try {
      const detail = await phases(`/collections/${encodeURIComponent(id)}`);
      if (version !== state.detailVersion) return;
      state.detail = detail;
    } catch (error) {
      if (version !== state.detailVersion) return;
      message('col-papers-summary', `Could not read this collection's papers: ${error.message}`, 'bad');
      return;
    }
    renderMembers();
    renderPapers();
  }

  // ---- Editing ----

  function edit(collection) {
    state.collectionId = collection?.collection_id || '';
    state.detail = null;
    if (!collection) state.draft = { members: [], files: [] };
    $('col-name').value = collection?.name || '';
    $('col-description').value = collection?.description || '';
    $('col-title').textContent = collection ? collection.name : 'New collection';
    $('col-save').textContent = collection ? 'Save name and description' : 'Create collection';
    $('col-archive').hidden = !collection;
    $('col-run').disabled = !collection;
    $('col-search').hidden = !collection;
    $('col-refresh').hidden = !collection;
    if (collection) $('col-search').href = ctx.href('search', [], { collection: collection.collection_id });
    $('col-add-hint').textContent = collection
      ? 'Everything you add here joins the collection straight away.'
      : 'Add papers in any of these ways. They are saved with the collection when you create it.';
    message('col-message');
    message('col-add-message');
    message('col-upload-message');
    renderCollections();
    return loadDetail();
  }

  // `items` are [{ command, label }]; `labels` name them in messages.
  async function addMembers(items) {
    if (!items.length) return;
    if (!state.collectionId) {
      const held = new Set(state.draft.members.map((m) => commandKey(m.command)));
      for (const item of items) if (!held.has(commandKey(item.command))) state.draft.members.push(item);
      renderMembers();
      message('col-add-message', `${items.map((i) => i.label).join(', ')}: added. Create the collection to save it.`, 'ok');
      return;
    }
    await phases(`/collections/${encodeURIComponent(state.collectionId)}/members`, { method: 'POST', body: { members: items.map((i) => i.command) } });
    message('col-add-message', `${items.map((i) => i.label).join(', ')}: added to the collection.`, 'ok');
    await Promise.all([loadCollections(), loadDetail()]);
  }

  async function removeMember(member, label) {
    const removed = await ctx.confirm({
      title: `Remove "${label}" from this collection?`,
      body: ['Its papers leave this collection unless another member includes them.', 'Nothing is deleted from storage or the library, and queued runs keep their papers.'],
      confirmLabel: 'Remove from collection',
      danger: true,
      run: () => phases(`/collections/${encodeURIComponent(state.collectionId)}/members/${encodeURIComponent(member.member_id)}`, { method: 'DELETE' }),
    });
    if (!removed) return false;
    message('col-add-message', `"${label}" removed from the collection.`, 'ok');
    await Promise.all([loadCollections(), loadDetail()]);
    return true;
  }

  function addFolder() {
    const prefix = $('col-folder').value;
    if (!prefix) throw new Error('Choose a storage folder.');
    return addMembers([{ command: { folder: { prefix } }, label: folderName(prefix) }]);
  }

  function addPubmed() {
    const query = state.pubmedQueries.find((q) => q.query_id === $('col-pubmed').value);
    if (!query) throw new Error('Choose a saved PubMed search.');
    return addMembers([{ command: { pubmed_query: { query_id: query.query_id } }, label: query.query }]);
  }

  // Each file reports its own outcome; one failure does not stop the others.
  async function sendFiles(files, path) {
    const outcomes = [];
    let failed = false;
    for (const file of files) {
      try {
        if (file.size > MAX_UPLOAD_BYTES) throw new Error('larger than 25 MiB');
        await phases(`${path}${path.includes('?') ? '&' : '?'}filename=${encodeURIComponent(file.name)}`, {
          method: 'POST', body: file, raw: true, contentType: 'application/pdf',
        });
        outcomes.push(`${file.name}: uploaded`);
      } catch (error) {
        failed = true;
        outcomes.push(`${file.name}: failed - ${error.message}`);
      }
    }
    return { outcomes, failed };
  }

  async function upload() {
    const files = [...($('col-upload-files').files || [])];
    if (!files.length) throw new Error('Choose at least one PDF.');
    const large = files.filter((f) => f.size > MAX_UPLOAD_BYTES);
    if (!state.collectionId) {
      const fits = files.filter((f) => f.size <= MAX_UPLOAD_BYTES);
      state.draft.files.push(...fits);
      renderMembers();
      message('col-upload-message', [
        fits.length ? `${plural(fits.length, 'PDF')} ready to upload when you create the collection.` : '',
        ...large.map((f) => `${f.name}: larger than 25 MiB`),
      ].filter(Boolean).join('\n'), large.length ? 'warn' : 'ok');
      return;
    }
    const { outcomes, failed } = await sendFiles(files, `/collections/${encodeURIComponent(state.collectionId)}/documents`);
    message('col-upload-message', outcomes.join('\n'), failed ? 'warn' : 'ok');
    await Promise.all([loadCollections(), loadDetail()]);
  }

  async function save() {
    const name = $('col-name').value.trim();
    const description = $('col-description').value.trim();
    if (!name) throw new Error('Name the collection.');
    if (state.collectionId) {
      const updated = await phases(`/collections/${encodeURIComponent(state.collectionId)}`, { method: 'PUT', body: { name, description } });
      await loadCollections();
      $('col-title').textContent = updated.name;
      message('col-message', 'Collection saved.', 'ok');
      return updated;
    }
    const { files } = state.draft;
    const created = await phases('/collections', { method: 'POST', body: { name, description, members: state.draft.members.map((m) => m.command) } });
    state.draft = { members: [], files: [] };
    let uploaded = { outcomes: [], failed: false };
    if (files.length) uploaded = await sendFiles(files, `/collections/${encodeURIComponent(created.collection_id)}/documents`);
    await loadCollections();
    state.current = created.collection_id;
    ctx.replace(ctx.href('collections', [created.collection_id]));
    await edit(state.collections.find((c) => c.collection_id === created.collection_id) || created);
    message('col-message', 'Collection created.', 'ok');
    if (uploaded.outcomes.length) message('col-upload-message', uploaded.outcomes.join('\n'), uploaded.failed ? 'warn' : 'ok');
    ctx.toast(`Collection "${created.name}" created.`);
    return created;
  }

  async function archive() {
    const collection = saved();
    if (!collection) return false;
    const archived = await ctx.confirm({
      title: `Archive "${collection.name}"?`,
      body: ['The collection disappears from this list, from new runs and from search filters.', 'Its papers, storage folders and any queued runs are kept.'],
      confirmLabel: 'Archive collection',
      danger: true,
      run: () => phases(`/collections/${encodeURIComponent(collection.collection_id)}`, { method: 'DELETE' }),
    });
    if (!archived) return false;
    await loadCollections();
    state.current = 'new';
    ctx.replace(ctx.href('collections', ['new']));
    await edit(null);
    message('col-message', 'Collection archived. Its papers and queued runs are kept.', 'ok');
    return true;
  }

  function runOnCollection() {
    if (!state.collectionId) return;
    ctx.section('runs').useCollection(state.collectionId);
    ctx.navigate(ctx.href('runs', ['new']));
  }

  // ---- The library picker ----

  function libraryResult(label, detail, item) {
    const row = document.createElement('div');
    row.className = 'pick';
    row.innerHTML = `<span>${esc(label)}<small>${esc(detail)}</small></span>`;
    const add = document.createElement('button');
    add.type = 'button';
    add.className = 'small';
    add.textContent = 'Add';
    add.setAttribute('aria-label', `Add ${label}`);
    add.addEventListener('click', () => action(add, 'col-library-message', () => addMembers([item])));
    row.append(add);
    $('col-library-results').append(row);
  }

  async function findLibrary() {
    const q = $('col-library-q').value.trim();
    $('col-library-results').replaceChildren();
    message('col-library-message', 'Searching the library...');
    const [published, ingested] = await Promise.allSettled([
      pubmed(`/papers?${new URLSearchParams({ search: q, status: 'published', page_size: 20 })}`),
      phases(`/papers?${new URLSearchParams({ q, limit: 20 })}`),
    ]);
    const pubmedRows = published.status === 'fulfilled' ? published.value.papers.filter((r) => r.artifacts?.length) : [];
    for (const row of pubmedRows) {
      const p = row.paper;
      libraryResult(p.title || `PMID ${p.pmid}`, `PubMed · PMID ${p.pmid}${p.journal ? ` · ${p.journal}` : ''}`, { command: { paper: { pmid: p.pmid } }, label: p.title || `PMID ${p.pmid}` });
    }
    // A PubMed PDF that was ingested shows once, as its PubMed paper.
    const known = new Set(pubmedRows.flatMap((r) => r.artifacts.map((a) => a.content_sha256)));
    const files = ingested.status === 'fulfilled' ? ingested.value.papers.filter((p) => !known.has(p.paper_id)) : [];
    for (const paper of files) {
      libraryResult(paper.file_name, `Ingested · ${paper.path}`, { command: { paper: { paper_id: paper.paper_id } }, label: paper.file_name });
    }
    const failed = [published, ingested].filter((r) => r.status === 'rejected').map((r) => r.reason.message);
    const total = pubmedRows.length + files.length;
    if (failed.length) message('col-library-message', `${plural(total, 'paper')} found. Part of the library could not be searched: ${failed.join('; ')}`, 'warn');
    else message('col-library-message', total ? `${plural(total, 'paper')} found. Only downloaded PubMed papers can be added; refine the words to see others.` : 'No downloaded or ingested papers match. Try another word, or download papers from the Library first.');
  }

  // Opens a dialog to add `commands` to an existing or a new collection.
  // Resolves with the collection added to, or null when cancelled.
  async function addToCollection(commands, what) {
    const list = (await phases('/collections?counts=false')).collections;
    const dialog = $('col-pick-dialog');
    const choose = $('col-pick-select');
    const ok = $('col-pick-ok');
    const cancel = $('col-pick-cancel');
    $('col-pick-body').textContent = `Add ${what} to one of your collections, or to a new one.`;
    fill(choose, [...list, { collection_id: NEW, name: 'New collection...' }], 'collection_id', (c) => c.name, [state.lastPicked || list[0]?.collection_id || NEW]);
    const toggle = () => { $('col-pick-new').hidden = choose.value !== NEW; };
    choose.onchange = toggle;
    toggle();
    $('col-pick-name').value = '';
    message('col-pick-error');
    ok.disabled = false;
    cancel.disabled = false;
    return new Promise((resolve) => {
      let sending = false;
      let settled = false;
      const finish = (result) => {
        if (settled) return;
        settled = true;
        dialog.onclose = null;
        dialog.oncancel = null;
        if (dialog.open) dialog.close();
        resolve(result);
      };
      dialog.oncancel = (event) => { if (sending) event.preventDefault(); };
      dialog.onclose = () => { if (!sending) finish(null); };
      cancel.onclick = () => { if (!sending) finish(null); };
      ok.onclick = async () => {
        if (sending) return;
        sending = true;
        ok.disabled = true;
        cancel.disabled = true;
        message('col-pick-error');
        try {
          let target;
          if (choose.value === NEW) {
            const name = $('col-pick-name').value.trim();
            if (!name) throw new Error('Name the new collection.');
            target = await phases('/collections', { method: 'POST', body: { name, members: commands } });
          } else {
            target = await phases(`/collections/${encodeURIComponent(choose.value)}/members`, { method: 'POST', body: { members: commands } });
          }
          state.lastPicked = target.collection_id;
          sending = false;
          ctx.toast(`Added to "${target.name}".`);
          if (state.loaded) loadCollections().catch(() => {});
          if (target.collection_id === state.collectionId) loadDetail();
          finish(target);
        } catch (error) {
          sending = false;
          message('col-pick-error', error?.message || String(error), 'bad');
        } finally {
          ok.disabled = false;
          cancel.disabled = false;
        }
      };
      dialog.showModal();
      choose.focus();
    });
  }

  // ---- Storage folders ----

  async function createLocation() {
    const location = await phases('/locations', { method: 'POST', body: { name: $('col-location-name').value.trim() } });
    state.locations = (await phases('/locations')).locations;
    fillChoices();
    $('col-location-name').value = '';
    await addMembers([{ command: { folder: { prefix: location.prefix } }, label: location.name }]);
    message('col-location-message', 'Storage folder created and added to the collection you are editing.', 'ok');
  }

  async function uploadToFolder() {
    const files = [...($('col-folder-upload-files').files || [])];
    const location = $('col-folder-upload-location').value;
    if (!files.length || !location) throw new Error('Choose a storage folder and at least one PDF.');
    const { outcomes, failed } = await sendFiles(files, `/documents?location=${encodeURIComponent(location)}`);
    message('col-folder-upload-message', outcomes.join('\n'), failed ? 'warn' : 'ok');
    if (state.collectionId) await loadDetail();
    return outcomes;
  }

  // ---- Wiring ----

  $('col-new').addEventListener('click', () => ctx.navigate(ctx.href('collections', ['new'])));
  $('col-form').addEventListener('submit', (event) => { event.preventDefault(); action($('col-save'), 'col-message', save); });
  $('col-run').addEventListener('click', runOnCollection);
  $('col-archive').addEventListener('click', () => action($('col-archive'), 'col-message', archive));
  $('col-add-folder').addEventListener('click', () => action($('col-add-folder'), 'col-add-message', addFolder));
  $('col-add-pubmed').addEventListener('click', () => action($('col-add-pubmed'), 'col-add-message', addPubmed));
  $('col-upload').addEventListener('click', () => action($('col-upload'), 'col-upload-message', upload));
  $('col-library-form').addEventListener('submit', (event) => { event.preventDefault(); action($('col-library-find'), 'col-library-message', findLibrary); });
  $('col-refresh').addEventListener('click', () => action($('col-refresh'), 'col-papers-summary', loadDetail));
  $('col-create-location').addEventListener('click', () => action($('col-create-location'), 'col-location-message', createLocation));
  $('col-folder-upload').addEventListener('click', () => action($('col-folder-upload'), 'col-folder-upload-message', uploadToFolder));

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
    if (entering && state.current && id === state.current) { if (state.collectionId) await loadDetail(); return; }
    state.current = id || '';
    await select(id);
    if (!id) state.current = state.collectionId || 'new';
  }

  // Keeps an unsaved draft: only the lists and the open collection are re-read.
  async function refresh() {
    try {
      await reload();
      if (state.collectionId) await loadDetail();
    } catch (error) {
      message('col-message', `Could not refresh collections: ${error.message}`, 'bad');
    }
  }

  return {
    show, hide() {}, refresh, state,
    // Called from Library ("Add to collection").
    addToCollection,
    actions: {
      save, archive, runOnCollection, addMembers, addFolder, addPubmed, upload, findLibrary,
      removeMember, createLocation, uploadToFolder, edit, reload, loadDetail,
    },
  };
}
