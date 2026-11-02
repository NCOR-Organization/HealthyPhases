// Runs: queue pipeline runs, keep saved configurations and follow requests.
//
// #/runs lists requests, #/runs/<request_id> opens one and #/runs/new is the
// new-run form. The form is kept between visits, so a draft is never lost.

import { phases } from '../api.js';
import { documentPreview } from '../documents.js';
import {
  $, action, emptyRow, esc, fill, formatDate, message, plural, selected, selectValues, statusPill, tableHtml,
} from '../ui.js';
import { promptLabel } from './prompts.js';

const STATUSES = ['pending', 'running', 'succeeded', 'failed'];
const PUBMED_LOCATION = 'dataset:pubmed:';
const COLLECTION_LOCATION = 'dataset:collection:';

export function pubmedQueryLabel(q) {
  if (!q.query_id) return q.query;
  const count = q.published_paper_count ?? 0;
  const ingestion = q.last_ingested_at ? `Last ingestion: ${formatDate(q.last_ingested_at)}` : 'No completed ingestion';
  return `${q.query} | ${plural(count, 'published paper')} | ${ingestion}`;
}

export function resultSummary(request) {
  if (!request.counts) return request.error || 'No result counts available yet.';
  const c = request.counts;
  return `${c.succeeded} succeeded, ${c.failed} failed, ${c.skipped} skipped across ${plural(c.prompts_run, 'prompt')}.`;
}

const template = () => `
  <header class="page-head"><p class="eyebrow">Step 3 · Run the pipeline</p><h1 tabindex="-1">Runs</h1>
    <p class="lede">Queue extraction runs over your papers and follow them until they finish.</p></header>
  <nav class="tabs" aria-label="Run views"><a id="run-tab-list" href="#/runs">Requests</a><a id="run-tab-new" href="#/runs/new">New run</a></nav>

  <div id="run-view-list" class="stack" hidden>
    <section class="card">
      <div class="card-head"><div><h2>Run requests</h2><p id="run-updated" class="hint">Refreshes every 10 seconds while this page is open.</p></div>
        <div class="row"><a class="button primary" href="#/runs/new">New run</a><button id="run-refresh-requests" type="button">Refresh</button></div></div>
      <div class="row"><label for="run-status" class="inline">Status</label><select id="run-status" class="auto"><option value="">All statuses</option>${STATUSES.map((s) => `<option value="${s}">${s}</option>`).join('')}</select><span class="hint">Most recent 100 requests</span></div>
      <p id="run-requests-message" class="msg" role="status"></p>
      ${tableHtml('run-requests', ['Run', 'Status', 'Prompts', 'Model'], 'Run requests')}
    </section>
    <section class="card" id="run-detail" hidden aria-labelledby="run-detail-title">
      <div class="card-head"><h2 id="run-detail-title" tabindex="-1">Run details</h2><a id="run-detail-close" class="button" href="#/runs">Close</a></div>
      <div id="run-detail-content"></div>
      <div class="row actions"><a id="run-detail-papers" class="button" href="#/results" hidden>Papers in this run</a><a id="run-detail-collection" class="button" href="#/collections" hidden>Open the collection</a><a id="run-detail-results" class="button" href="#/search" hidden>Search with this run's prompts and model</a></div>
    </section>
  </div>

  <div id="run-view-new" class="stack" hidden>
    <p id="run-app-message" class="msg" role="status"></p>
    <section class="card">
      <h2>Saved configurations</h2>
      <div class="row"><label class="sr-only" for="run-saved">Saved configuration</label><select id="run-saved" class="grow"></select><button id="run-load-saved" type="button" disabled>Load into the form</button><button id="run-run-saved" type="button" disabled>Run saved configuration</button></div>
      <p id="run-saved-message" class="msg" role="status"></p>
    </section>
    <section class="card">
      <h2>1. Choose papers</h2>
      <div class="grid">
        <div><label for="run-source">Paper source</label><select id="run-source"><option value="storage">Storage folders</option><option value="collection">Collection</option><option value="pubmed">PubMed search</option></select>
          <p class="hint">A collection holds the papers you gathered; a PubMed source contains the papers downloaded for that search.</p></div>
        <div id="run-collection-picker" hidden><label for="run-collection">Collection</label><select id="run-collection"></select>
          <p class="hint">The run covers the collection's papers as they are when you submit it. <a id="run-manage-collection" href="#/collections">Manage collections</a></p></div>
        <div id="run-pubmed-picker" hidden><label for="run-pubmed-query">Downloaded PubMed search</label><select id="run-pubmed-query"><option value="">Choose a search</option></select>
          <div class="row actions"><button id="run-refresh-pubmed" type="button">Refresh searches</button><a href="#/library/search">Search PubMed</a></div>
          <p id="run-pubmed-message" class="msg" role="status"></p></div>
        <div class="storage-only"><label for="run-locations">Storage folders</label><select id="run-locations" multiple></select><p class="hint">Use Ctrl or Command to select several folders.</p></div>
      </div>
      <div class="row actions storage-only"><label class="sr-only" for="run-quick-name">New collection name</label><input id="run-quick-name" class="grow" placeholder="Name a collection of these folders" maxlength="120"><button id="run-quick-save" type="button">Save as collection</button></div>
      <p id="run-collection-message" class="msg" role="status"></p>
    </section>
    <section class="card">
      <div class="card-head"><h2>Documents in this selection</h2><button id="run-refresh-documents" type="button">Refresh documents</button></div>
      <p id="run-documents-summary" class="msg" role="status">Choose storage folders to preview their documents.</p>
      ${tableHtml('run-documents', ['Document', 'Folder', 'Path', 'State'], 'Documents in this selection', true)}
    </section>
    <section class="card">
      <h2>2. Configure extraction</h2>
      <div class="grid">
        <div><label for="run-prompts">Prompts <span class="hint">(all selected at first)</span></label><select id="run-prompts" multiple></select><p class="hint"><a href="#/prompts">Browse or edit the prompt library</a></p></div>
        <div class="stack"><div><label for="run-model">Model</label><select id="run-model"></select></div><div><label for="run-chunker">Chunker</label><select id="run-chunker"></select></div></div>
      </div>
      <p id="run-chunker-warning" class="msg warn" role="status"></p>
      <div id="run-config-row" class="row actions"><label class="sr-only" for="run-config-name">Configuration name</label><input id="run-config-name" class="grow" maxlength="100" placeholder="Name this configuration"><button id="run-save-config" type="button">Save configuration</button></div>
      <p class="note">Each run processes the chosen papers with every selected prompt and the chosen model. A run on a collection or a PubMed search keeps exactly the papers available when you submit it.</p>
      <div class="row actions"><button id="run-submit" class="primary" type="button" disabled>Request run</button><span class="hint">Queued requests start when the orchestrator is available.</span></div>
      <p id="run-message" class="msg" role="status"></p><a id="run-view-request" href="#/runs" hidden>Follow this run</a>
    </section>
  </div>`;

export function create(root, ctx) {
  root.innerHTML = template();
  const state = {
    active: false, view: 'list', ready: false, loading: null,
    prompts: [], models: [], chunkers: [], locations: [], collections: [], pipelines: [], pubmedQueries: [],
    requests: [], requestId: '', requestsLoading: false, warningVersion: 0,
    pending: { collectionId: '', addPrompts: [], removePrompts: [] },
  };
  const source = () => $('run-source').value || 'storage';
  const folderName = (prefix) => state.locations.find((l) => l.prefix === prefix)?.name || prefix;
  const preview = documentPreview($('run-documents'), $('run-documents-summary'), folderName);
  const isPubmed = () => source() === 'pubmed';

  const promptName = (id) => {
    const prompt = state.prompts.find((p) => p.prompt_id === id);
    return prompt ? promptLabel(prompt, state.prompts) : 'Unknown prompt version';
  };
  const modelName = (id) => state.models.find((m) => m.model_id === id)?.display_name || id;
  const chunkerName = (id) => {
    const chunker = state.chunkers.find((c) => c.chunker_id === id);
    return chunker ? `${chunker.name} v${chunker.version}` : id;
  };
  const collectionName = (id, request) => request?.collection?.name
    || state.collections.find((c) => c.collection_id === id)?.name;
  // `request` carries the collection's name, which outlives an archived collection.
  const sourceName = (location, request) => {
    if (location.startsWith(COLLECTION_LOCATION)) {
      const name = collectionName(location.slice(COLLECTION_LOCATION.length), request);
      return `Collection: ${name || 'archived collection'}`;
    }
    if (!location.startsWith(PUBMED_LOCATION)) return folderName(location);
    const query = state.pubmedQueries.find((q) => q.query_id === location.slice(PUBMED_LOCATION.length));
    return `PubMed: ${query ? query.query : 'saved search'}`;
  };
  function sourcesLabel(locations = [], request) {
    const names = locations.map((location) => sourceName(location, request));
    if (names.length <= 2) return names.join(', ') || 'No source recorded';
    return `${names.slice(0, 2).join(', ')} and ${names.length - 2} more`;
  }

  // ---- Choices ----

  // Every way of choosing a collection goes through here, so its link follows.
  function chooseCollection(id) {
    const collection = state.collections.find((c) => c.collection_id === id);
    $('run-collection').value = collection ? id : '';
    $('run-manage-collection').href = ctx.href('collections', collection ? [collection.collection_id] : []);
    return collection;
  }

  function useSource(value) {
    $('run-source').value = value;
    sourceChanged(false);
  }

  function applyPending() {
    const { collectionId, addPrompts, removePrompts } = state.pending;
    if (collectionId) {
      useSource('collection');
      chooseCollection(collectionId);
    }
    for (const option of $('run-prompts').options) {
      if (addPrompts.includes(option.value)) option.selected = true;
      if (removePrompts.includes(option.value)) option.selected = false;
    }
    state.pending = { collectionId: '', addPrompts: [], removePrompts: [] };
    if (collectionId) refreshDocuments();
  }

  function renderCollections() {
    const current = $('run-collection').value;
    const choices = state.collections.length
      ? state.collections
      : [{ collection_id: '', name: 'No collections yet. Create one in Collections.' }];
    fill($('run-collection'), choices, 'collection_id', (c) => (c.collection_id ? `${c.name} · ${plural(c.member_count ?? 0, 'member')}` : c.name), [current]);
    chooseCollection($('run-collection').value);
  }

  function renderPipelines(pick) {
    const chosen = pick || $('run-saved').value;
    if (!state.pipelines.length) {
      fill($('run-saved'), [{ pipeline_id: '', name: 'No saved configurations yet. Save one below.' }], 'pipeline_id', (p) => p.name);
    } else {
      fill($('run-saved'), state.pipelines, 'pipeline_id', (p) => `${p.name} (${formatDate(p.created_at)})`, chosen ? [chosen] : undefined);
    }
    $('run-load-saved').disabled = $('run-run-saved').disabled = !state.pipelines.length;
  }

  // Reads every list the form offers, keeping whatever is already chosen.
  async function loadChoices() {
    const [locations, chunkers, prompts, models, collections] = await Promise.all([
      phases('/locations'), phases('/chunkers'), phases('/prompts'), phases('/models'), phases('/collections?counts=false'),
    ]);
    const first = !state.ready;
    const keep = {
      locations: selected($('run-locations')), prompts: selected($('run-prompts')),
      model: $('run-model').value, chunker: $('run-chunker').value,
    };
    state.locations = locations.locations;
    state.chunkers = chunkers.chunkers;
    state.prompts = prompts.prompts;
    state.models = models.models;
    state.collections = collections.collections;
    fill($('run-locations'), state.locations, 'prefix', (l) => l.name, keep.locations);
    selectValues($('run-locations'), keep.locations, folderName);
    fill($('run-chunker'), state.chunkers, 'chunker_id', (c) => `${c.name} v${c.version}`, keep.chunker ? [keep.chunker] : undefined);
    fill($('run-model'), state.models, 'model_id', (m) => m.display_name, keep.model ? [keep.model] : undefined);
    fill($('run-prompts'), state.prompts, 'prompt_id', (p) => promptLabel(p, state.prompts), keep.prompts);
    if (first) for (const option of $('run-prompts').options) option.selected = true;
    renderCollections();
    state.ready = true;
    $('run-submit').disabled = false;
    applyPending();
    if (first) refreshWarning();
    await refreshPipelines().catch((error) => message('run-saved-message', error.message, 'bad'));
  }

  // Loads the choices once, or again when `reload` asks for lists changed elsewhere.
  function ensureChoices(reload = false) {
    if (state.loading && !reload) return state.loading;
    if (!state.ready) message('run-app-message', 'Loading the run options...');
    state.loading = (state.loading || Promise.resolve())
      .then(loadChoices)
      .then(() => message('run-app-message'))
      .catch((error) => {
        state.loading = null;
        message('run-app-message', `Could not load the run options: ${error.message}. Use Refresh, or reload the app.`, 'bad');
      });
    return state.loading;
  }

  async function refreshPipelines(pick) {
    state.pipelines = (await phases('/pipelines')).pipelines;
    renderPipelines(pick);
  }

  async function loadPubmed() {
    try {
      const data = await phases('/sources/pubmed');
      state.pubmedQueries = data.queries;
      const chosen = $('run-pubmed-query').value;
      fill($('run-pubmed-query'), [{ query_id: '', query: 'Choose a search' }, ...data.queries], 'query_id', pubmedQueryLabel, [chosen]);
      message('run-pubmed-message', data.available
        ? 'Counts are distinct papers with downloaded PDFs. Dates are the last completed ingestion, in your timezone.'
        : 'No PubMed papers are published in this deployment yet. Download papers from the Library first.', data.available ? '' : 'warn');
    } catch (error) {
      message('run-pubmed-message', error.message, 'bad');
    }
  }

  function sourceChanged(preview = true) {
    const chosen = source();
    $('run-pubmed-picker').hidden = chosen !== 'pubmed';
    $('run-collection-picker').hidden = chosen !== 'collection';
    // A PubMed run is queued from the search itself, so it is not saved as a configuration.
    $('run-config-row').hidden = chosen === 'pubmed';
    for (const el of root.querySelectorAll('.storage-only')) el.hidden = chosen !== 'storage';
    for (const id of ['run-locations', 'run-quick-save', 'run-quick-name']) $(id).disabled = chosen !== 'storage';
    $('run-collection').disabled = chosen !== 'collection';
    for (const id of ['run-save-config', 'run-config-name']) $(id).disabled = chosen === 'pubmed';
    if (chosen === 'pubmed') loadPubmed();
    if (preview) refreshDocuments();
  }

  function refreshDocuments() {
    if (isPubmed()) return preview.pubmed($('run-pubmed-query').value);
    if (source() === 'collection') return preview.collection($('run-collection').value);
    return preview.storage(selected($('run-locations')));
  }

  async function refreshWarning() {
    const version = ++state.warningVersion;
    message('run-chunker-warning');
    const chunker = $('run-chunker').value;
    if (!chunker) return;
    try {
      const { warning } = await phases(`/chunker-warning?chunker_id=${encodeURIComponent(chunker)}`);
      if (version === state.warningVersion) message('run-chunker-warning', warning || '', 'warn');
    } catch (error) {
      if (version === state.warningVersion) message('run-chunker-warning', `Could not check chunker compatibility: ${error.message}`, 'warn');
    }
  }

  // ---- Submitting ----

  // Papers come from storage folders or from one collection, never both.
  function runInputs() {
    const papers = source() === 'collection' ? { collection_id: $('run-collection').value } : { locations: selected($('run-locations')) };
    return { ...papers, chunker_id: $('run-chunker').value, prompt_ids: selected($('run-prompts')), model_id: $('run-model').value };
  }

  function queued(request, text) {
    state.requestId = request.request_id;
    $('run-view-request').href = ctx.href('runs', [request.request_id]);
    $('run-view-request').hidden = false;
    ctx.toast(text);
  }

  async function submit() {
    $('run-view-request').hidden = true;
    const inputs = runInputs();
    const pubmed = isPubmed();
    const papers = pubmed ? $('run-pubmed-query').value : inputs.collection_id ?? inputs.locations.length;
    if (!papers || !inputs.prompt_ids.length || !inputs.chunker_id || !inputs.model_id) {
      const what = { pubmed: 'a PubMed search', collection: 'a collection', storage: 'at least one storage folder' }[source()];
      throw new Error(`Choose ${what}, at least one prompt, a chunker and an available model.`);
    }
    const request = pubmed
      ? await phases('/sources/pubmed/requests', { method: 'POST', body: { query_id: $('run-pubmed-query').value, chunker_id: inputs.chunker_id, prompt_ids: inputs.prompt_ids, model_id: inputs.model_id } })
      : await phases('/requests', { method: 'POST', body: inputs });
    message('run-message', 'Run queued. It starts when the orchestrator picks it up.', 'ok');
    queued(request, 'Run queued.');
    return request;
  }

  async function saveConfiguration() {
    const saved = await phases('/pipelines', { method: 'POST', body: { name: $('run-config-name').value.trim(), inputs: runInputs() } });
    await refreshPipelines(saved.pipeline_id);
    message('run-saved-message', 'Configuration saved.', 'ok');
  }

  async function loadConfiguration() {
    const pipeline = state.pipelines.find((p) => p.pipeline_id === $('run-saved').value);
    if (!pipeline) throw new Error('Choose a saved configuration.');
    const { collection_id: collectionId, locations = [] } = pipeline.inputs;
    useSource(collectionId ? 'collection' : 'storage');
    await loadChoices();
    if (collectionId) {
      if (!chooseCollection(collectionId)) throw new Error('This configuration runs on a collection that has been archived. Choose another collection.');
    } else {
      selectValues($('run-locations'), locations, folderName);
    }
    for (const option of $('run-prompts').options) option.selected = pipeline.inputs.prompt_ids.includes(option.value);
    $('run-model').value = pipeline.inputs.model_id;
    $('run-chunker').value = pipeline.inputs.chunker_id;
    $('run-config-name').value = pipeline.name;
    await refreshDocuments();
    await refreshWarning();
    message('run-saved-message', 'Configuration loaded into the form below.', 'ok');
  }

  async function runConfiguration() {
    const pipeline = state.pipelines.find((p) => p.pipeline_id === $('run-saved').value);
    if (!pipeline) throw new Error('Choose a saved configuration.');
    const { inputs } = pipeline;
    let request;
    const confirmed = await ctx.confirm({
      title: `Run "${pipeline.name}"?`,
      body: [
        `Papers: ${inputs.collection_id ? `collection "${collectionName(inputs.collection_id) || 'archived collection'}", as it is now` : sourcesLabel(inputs.locations)}.`,
        `Prompts: ${inputs.prompt_ids.map(promptName).join(', ')}.`,
        `Model: ${modelName(inputs.model_id)}. Chunker: ${chunkerName(inputs.chunker_id)}.`,
        'The run is queued and starts when the orchestrator is available.',
      ],
      confirmLabel: 'Queue run',
      run: async () => { request = await phases(`/pipelines/${encodeURIComponent(pipeline.pipeline_id)}/requests`, { method: 'POST', body: {} }); },
    });
    if (!confirmed) return undefined;
    message('run-saved-message', 'Saved configuration queued. Follow it from Requests.', 'ok');
    queued(request, `"${pipeline.name}" queued.`);
    return request;
  }

  // The folders become a collection, and the run is on that collection from then on.
  async function quickSave() {
    const saved = await phases('/collections', { method: 'POST', body: { name: $('run-quick-name').value.trim(), locations: selected($('run-locations')) } });
    state.collections = (await phases('/collections?counts=false')).collections;
    renderCollections();
    useSource('collection');
    chooseCollection(saved.collection_id);
    $('run-quick-name').value = '';
    message('run-collection-message', `Collection "${saved.name}" saved. The run now uses it.`, 'ok');
    refreshDocuments();
  }

  // ---- Requests ----

  function renderRequests() {
    $('run-requests').replaceChildren();
    const status = $('run-status').value;
    const requests = state.requests.filter((r) => !status || r.status === status);
    if (!requests.length) {
      $('run-requests').innerHTML = emptyRow(4, state.requests.length ? 'No runs have this status. Choose All statuses.' : 'No runs yet. Start one from New run.');
    }
    for (const request of requests) {
      const row = document.createElement('tr');
      if (request.request_id === state.requestId) row.className = 'current';
      row.innerHTML = `<td><a class="row-link" href="${esc(ctx.href('runs', [request.request_id]))}">${esc(sourcesLabel(request.locations, request))}</a><small>Submitted ${esc(formatDate(request.requested_at))}</small></td><td>${statusPill(request.status)}</td><td>${esc((request.prompt_ids || []).map(promptName).join(', '))}</td><td>${esc(modelName(request.model_id))}</td>`;
      $('run-requests').append(row);
    }
  }

  async function loadRequestDetail() {
    const id = state.requestId;
    $('run-detail').hidden = !id;
    $('run-detail-papers').hidden = true;
    if (!id) return;
    try {
      const request = await phases(`/requests/${encodeURIComponent(id)}`);
      if (id !== state.requestId) return;
      const fields = {
        Source: (request.locations || []).map((location) => sourceName(location, request)).join('\n'),
        Status: request.status,
        Submitted: formatDate(request.requested_at), Started: formatDate(request.started_at), Finished: formatDate(request.finished_at),
        Prompts: (request.prompt_ids || []).map(promptName).join('\n'),
        Model: modelName(request.model_id), Chunker: chunkerName(request.chunker_id),
        Result: resultSummary(request), Error: request.error || '—',
        'Request ID': request.request_id, 'Run ID': request.run_id || '—',
      };
      $('run-detail-content').innerHTML = `<dl class="details">${Object.entries(fields).map(([key, value]) => `<dt>${esc(key)}</dt><dd>${key === 'Status' ? statusPill(value) : esc(value)}</dd>`).join('')}</dl>`;
      const names = (request.prompt_ids || []).map((pid) => state.prompts.find((p) => p.prompt_id === pid)?.name).filter(Boolean);
      $('run-detail-results').href = ctx.href('search', [], { mode: 'semantic', prompt: [...new Set(names)], model: request.model_id });
      $('run-detail-results').hidden = request.status !== 'succeeded';
      $('run-detail-papers').href = ctx.href('results', [], { request: request.request_id });
      $('run-detail-papers').hidden = false;
      const collection = request.collection;
      $('run-detail-collection').hidden = !collection || collection.archived !== false;
      if (collection) $('run-detail-collection').href = ctx.href('collections', [collection.collection_id]);
    } catch (error) {
      if (id === state.requestId) $('run-detail-content').textContent = `Could not load this run: ${error.message}`;
    }
  }

  // Never overlaps: a slow refresh is not stacked behind another.
  async function loadRequests() {
    if (state.requestsLoading) return;
    state.requestsLoading = true;
    try {
      state.requests = (await phases('/requests?limit=100')).requests;
      renderRequests();
      message('run-requests-message');
      $('run-updated').textContent = `Updated ${new Date().toLocaleTimeString()}. Refreshes every 10 seconds.`;
      await loadRequestDetail();
    } catch (error) {
      message('run-requests-message', `Could not refresh runs: ${error.message}`, 'bad');
    } finally {
      state.requestsLoading = false;
    }
  }

  // ---- Wiring ----

  $('run-source').addEventListener('change', () => sourceChanged());
  $('run-pubmed-query').addEventListener('change', refreshDocuments);
  $('run-refresh-pubmed').addEventListener('click', loadPubmed);
  $('run-locations').addEventListener('change', refreshDocuments);
  $('run-chunker').addEventListener('change', refreshWarning);
  $('run-refresh-documents').addEventListener('click', refreshDocuments);
  $('run-collection').addEventListener('change', () => { chooseCollection($('run-collection').value); refreshDocuments(); });
  $('run-quick-save').addEventListener('click', () => action($('run-quick-save'), 'run-collection-message', quickSave));
  $('run-save-config').addEventListener('click', () => action($('run-save-config'), 'run-saved-message', saveConfiguration));
  $('run-load-saved').addEventListener('click', () => action($('run-load-saved'), 'run-saved-message', loadConfiguration));
  $('run-run-saved').addEventListener('click', () => action($('run-run-saved'), 'run-saved-message', runConfiguration));
  $('run-submit').addEventListener('click', () => action($('run-submit'), 'run-message', submit));
  $('run-status').addEventListener('change', renderRequests);
  $('run-refresh-requests').addEventListener('click', () => action($('run-refresh-requests'), 'run-requests-message', loadRequests));

  ctx.every(10000, () => { if (state.active && state.view === 'list' && !document.hidden) loadRequests(); });

  // Coming back from another section re-reads the lists, so a collection, folder or
  // prompt created there is offered here; the draft is kept.
  async function show(route, { entering = false } = {}) {
    state.active = true;
    const part = route.parts[0] || '';
    state.view = part === 'new' ? 'new' : 'list';
    $('run-view-list').hidden = state.view !== 'list';
    $('run-view-new').hidden = state.view !== 'new';
    for (const [id, view] of [['run-tab-list', 'list'], ['run-tab-new', 'new']]) {
      if (view === state.view) $(id).setAttribute('aria-current', 'page'); else $(id).removeAttribute('aria-current');
    }
    if (state.view === 'new') return ensureChoices(entering);
    const opened = part !== state.requestId;
    state.requestId = part;
    // Names for prompts, models and sources come with the choices.
    ensureChoices(entering);
    if (!state.pubmedQueries.length || entering) loadPubmed();
    await state.loading;
    await loadRequests();
    if (part && opened) $('run-detail-title').focus();
    return undefined;
  }

  async function refresh() {
    await loadChoices().catch((error) => message('run-app-message', `Could not refresh the run options: ${error.message}`, 'bad'));
    if (isPubmed() || state.view === 'list') await loadPubmed();
    if (state.view === 'list') return loadRequests();
    return refreshDocuments();
  }

  return {
    show,
    hide() { state.active = false; },
    refresh,
    state,
    // Hand-offs wait for the next load of the choices, which entering Runs triggers.
    // Called from Collections ("Run on this collection").
    useCollection(collectionId) {
      state.pending.collectionId = collectionId;
      return state.active ? ensureChoices(true) : undefined;
    },
    // Called from Prompts ("Add to a new run", and after saving a new version).
    selectPrompts(add = [], remove = []) {
      state.pending.addPrompts.push(...add);
      state.pending.removePrompts.push(...remove);
      return state.active ? ensureChoices(true) : undefined;
    },
    actions: {
      submit, saveConfiguration, loadConfiguration, runConfiguration, quickSave, loadRequests, loadRequestDetail,
      loadPubmed, refreshDocuments, loadChoices, sourceChanged, renderRequests,
    },
  };
}
