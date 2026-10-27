# HealthyPhases workspace app

Nexus catalog ID: `phases_v2:workspace`. The one app of this project: collect papers,
prepare prompts, run the pipeline and explore what it found. It calls the existing
`/phases_v2/api/*`, `/phases_v2/api/search/*`, `/pubmed/api/*` and `/openalex/api/*`
endpoints with the user's Nexus session.

## Files

```
workspace/
├── manifest.json         # catalog entry: name, description, category, icon
├── index.html            # the shell: sidebar, one <section> per section, toasts, confirm dialog
├── css/app.css           # light and dark tokens, layout, components
├── js/
│   ├── main.js           # entry point
│   ├── shell.js          # mounts sections, follows the route, refreshes on focus/visibility
│   ├── router.js         # hash routes and deep links; restores the last route after a reload
│   ├── api.js            # the only module that calls fetch: base URL, auth, errors
│   ├── ui.js             # escaping, messages, pills, empty states, pagination, toasts, confirmation
│   ├── documents.js      # document previews shared by Collections and Runs
│   └── sections/         # overview, library, collections, prompts, runs, search (+ search_render)
├── tests/                # node --test suites (*.cjs) and their small DOM stand-in
├── manifest_test.py      # catalog, serving and packaging checks
└── package.json          # marks js/ as ES modules for Node; not used by the browser
```

There is no build step and nothing loads from a CDN. `index.html` loads `js/main.js` as
a module and every import is relative, so the browser fetches each file from
`/app-html/phases_v2/workspace/...`. Nexus serves any `.js`, `.css` or `.json` file
under an app folder there, authorised by the `abi_app_html_token` cookie that its first
response sets.

## Routes

| Route | Shows |
| --- | --- |
| `#/overview` | The workflow in four steps with live counts |
| `#/library`, `#/library?query_id=...&page=2` | The paper library, with its filters and page |
| `#/library/search?query=<query_id>` | PubMed search, with a saved search previewed |
| `#/library/downloads` | Ingestion requests and full ingestions |
| `#/library/schedules` | Scheduled searches |
| `#/library/enrichment` | OpenAlex enrichment (only when the module is enabled) |
| `#/collections`, `#/collections/<collection_id>`, `#/collections/new` | Collections |
| `#/prompts`, `#/prompts/<prompt_id>`, `#/prompts/new` | The prompt library |
| `#/runs`, `#/runs/<request_id>` | Run requests, with one opened |
| `#/runs/new` | The new-run form and saved configurations |
| `#/search?q=...&mode=semantic\|keyword\|effects&prompt=...&model=...&path=...` | Search results |

Nexus gives the iframe a new URL, with a new access token, each time it reloads the app,
which drops the hash. The router therefore keeps the last route in `sessionStorage` and
restores it when the app opens without one.

## Sections

Each module in `js/sections/` exports `create(root, ctx)` and returns
`{ show(route, { entering }), hide(), refresh() }`. The shell creates a section on its
first visit and keeps it, so a draft survives a visit elsewhere. When the user comes back
to a section from another one, `show` receives `entering: true` and the section re-reads
its lists first, so a collection, folder, prompt or saved search created elsewhere is
there; an open draft is kept. Within a section, following a link to what is already open
(New collection, New prompt, a list item) re-renders it. The shell also calls `refresh()`
on the open section when the page becomes visible again or the window regains focus, so
changes made outside the app appear. Sections that follow work in progress also poll every 10 seconds while
they are open and visible: run requests, downloads and enrichment progress.

`ctx` gives a section `href`, `navigate`, `replace` (record state in the URL without
re-rendering), `section(name)` (reach another section, for example to hand folders to
the new-run form; hand-offs are applied the next time Runs loads its choices, which
entering it does), `toast`, `confirm` and `every`.

Every destructive or costly action asks first: archiving a collection, deleting a
schedule, starting a full ingestion, queueing OpenAlex enrichment and running a saved
configuration. While the confirmed action is being sent, Cancel and Escape are held
back, so the dialog only ever reports what actually happened.

## Tests

```bash
make test-app      # this folder only
make test          # the whole module, this app included
```

The `.cjs` suites import the ES modules into Node with a small DOM stand-in
(`tests/harness.cjs`): elements are created on first lookup by id, so a section's
template is never parsed and the test inspects the same objects the module writes to.
