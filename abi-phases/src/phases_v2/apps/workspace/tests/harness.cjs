// A minimal browser stand-in for the workspace modules.
//
// Elements are created on first lookup by id, so a section's template does not
// need parsing: the module finds the same element objects the test inspects.
// Each install() replaces the globals, giving every test a clean page.

const { join } = require('node:path');
const { pathToFileURL } = require('node:url');

const ROOT = join(__dirname, '..');

function element(tag = 'div') {
  const el = {
    tagName: tag.toUpperCase(), value: '', textContent: '', innerHTML: '', className: '', title: '', href: '',
    hidden: false, disabled: false, checked: false, selected: false, multiple: false, open: false,
    children: [], options: [], dataset: {}, style: {}, attributes: {}, listeners: {}, files: [],
    get selectedOptions() { return this.options.filter((option) => option.selected); },
    get firstElementChild() { if (!this.firstChild) this.firstChild = element('td'); return this.firstChild; },
    get lastElementChild() { if (!this.lastChild) this.lastChild = element('td'); return this.lastChild; },
    replaceChildren() { this.children = []; this.options = []; this.innerHTML = ''; },
    append(...nodes) {
      for (const node of nodes) {
        this.children.push(node);
        if (node && node.tagName === 'OPTION') this.options.push(node);
        if (node && typeof node === 'object') node.parent = this;
      }
    },
    remove() { if (this.parent) this.parent.children = this.parent.children.filter((c) => c !== this); },
    addEventListener(type, handler) { (this.listeners[type] ||= []).push(handler); },
    setAttribute(key, value) { this.attributes[key] = String(value); },
    getAttribute(key) { return this.attributes[key] ?? null; },
    removeAttribute(key) { delete this.attributes[key]; },
    querySelector() { return element(); },
    querySelectorAll() { return []; },
    focus() { el.focused = true; },
    click() { el.clicked = true; },
    showModal() { this.open = true; },
    close() { this.open = false; if (this.onclose) this.onclose(); for (const h of this.listeners.close || []) h({}); },
    getBoundingClientRect() { return { top: 10000 }; },
  };
  return el;
}

function fire(el, type, event = {}) {
  const full = { preventDefault() {}, target: el, ...event };
  return Promise.all((el.listeners[type] || []).map((handler) => handler(full)));
}

function response(payload, { ok = true, status = ok ? 200 : 422, type = 'application/json' } = {}) {
  return {
    ok, status,
    headers: { get: (name) => (name.toLowerCase() === 'content-type' ? type : null) },
    text: async () => (typeof payload === 'string' ? payload : JSON.stringify(payload)),
    blob: async () => new Blob([typeof payload === 'string' ? payload : JSON.stringify(payload)]),
  };
}

function install({ hash = '', storage = {}, session = {} } = {}) {
  const elements = new Map();
  const navLinks = ['overview', 'library', 'collections', 'prompts', 'runs', 'results', 'search'].map((name) => {
    const link = element('a');
    link.dataset.nav = name;
    return link;
  });
  const documentListeners = {};
  const document = {
    hidden: false, title: '',
    body: element('body'), documentElement: element('html'),
    getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
    querySelectorAll(selector) { return selector === '[data-nav]' ? navLinks : []; },
    createElement: element,
    addEventListener(type, handler) { (documentListeners[type] ||= []).push(handler); },
  };
  const location = { hash };
  const history = { replaceState(_state, _title, url) { location.hash = url; } };
  const windowListeners = {};
  const win = {
    innerHeight: 800,
    addEventListener(type, handler) { (windowListeners[type] ||= []).push(handler); },
  };
  win.parent = win;
  win.top = win;
  const store = (data) => ({
    getItem: (key) => (key in data ? data[key] : null),
    setItem: (key, value) => { data[key] = String(value); },
  });
  const calls = [];
  Object.assign(globalThis, {
    document, location, history, window: win,
    localStorage: store(storage), sessionStorage: store(session),
    // Initial loads stay pending unless a test answers them.
    fetch: (url, options = {}) => { calls.push({ url, options }); return new Promise(() => {}); },
  });
  return {
    document, location, history, window: win, calls, elements, navLinks, session,
    $: (id) => document.getElementById(id),
    dispatchWindow: (type) => (windowListeners[type] || []).forEach((h) => h({})),
    dispatchDocument: (type) => (documentListeners[type] || []).forEach((h) => h({})),
    hashchange: () => (windowListeners.hashchange || []).forEach((h) => h({})),
  };
}

// A section context that records navigation instead of performing it.
function context(overrides = {}) {
  const ctx = {
    navigated: [], replaced: [], toasts: [], intervals: [], sections: {},
    href: null,
    navigate(target) { ctx.navigated.push(target); },
    replace(target) { ctx.replaced.push(target); },
    toast(text) { ctx.toasts.push(text); },
    every(ms, work) { ctx.intervals.push({ ms, work }); },
    section(name) { return ctx.sections[name]; },
    confirm: undefined,
    ...overrides,
  };
  return ctx;
}

// Answers fetches by URL: routes maps a substring (optionally "METHOD substring") to a payload or function.
function routeFetch(routes, calls = []) {
  return async (url, options = {}) => {
    const method = options.method || 'GET';
    calls.push({ url, method, body: options.body === undefined ? undefined : (typeof options.body === 'string' ? JSON.parse(options.body) : options.body), headers: options.headers });
    const key = Object.keys(routes)
      .filter((pattern) => {
        const [verb, path] = pattern.includes(' ') ? pattern.split(' ') : [null, pattern];
        return (!verb || verb === method) && url.includes(path);
      })
      .sort((a, b) => b.length - a.length)[0];
    if (key === undefined) throw new Error(`Unexpected request: ${method} ${url}`);
    const value = routes[key];
    const result = typeof value === 'function' ? await value(url, options) : value;
    // Response-like values (or a bare 204) are returned as they are.
    return result && (typeof result.text === 'function' || result.status === 204) ? result : response(result);
  };
}

const load = (relative) => import(pathToFileURL(join(ROOT, 'js', relative)).href);
const tick = () => new Promise((resolve) => setImmediate(resolve));
const settle = async (rounds = 5) => { for (let i = 0; i < rounds; i += 1) await tick(); };

module.exports = { ROOT, context, element, fire, install, load, response, routeFetch, settle, tick };
