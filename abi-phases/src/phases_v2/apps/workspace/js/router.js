// Hash routes: #/<section>/<part>...?<params>, for example #/runs/<request_id>
// or #/search?q=stress&mode=keyword.
//
// Nexus mints a fresh iframe URL (with a new access token) whenever it reloads
// the app, which drops the hash. The last route is therefore kept in
// sessionStorage and restored when the app opens without one.

export const SECTIONS = ['overview', 'library', 'collections', 'prompts', 'runs', 'search'];
export const DEFAULT_SECTION = 'overview';
const STORAGE_KEY = 'healthyphases.workspace.route';

const decode = (part) => {
  try { return decodeURIComponent(part); } catch (_malformed) { return part; }
};

export function parse(hash) {
  const raw = String(hash || '').replace(/^#\/?/, '');
  const split = raw.indexOf('?');
  const path = split === -1 ? raw : raw.slice(0, split);
  const query = split === -1 ? '' : raw.slice(split + 1);
  const parts = path.split('/').filter(Boolean).map(decode);
  const known = SECTIONS.includes(parts[0]);
  return {
    section: known ? parts[0] : DEFAULT_SECTION,
    parts: known ? parts.slice(1) : [],
    params: new URLSearchParams(known ? query : ''),
  };
}

// Empty values are left out so links stay short and stable.
export function href(section, parts = [], params = {}) {
  const query = params instanceof URLSearchParams ? new URLSearchParams(params) : new URLSearchParams();
  if (!(params instanceof URLSearchParams)) {
    for (const [key, value] of Object.entries(params)) {
      for (const item of Array.isArray(value) ? value : [value]) {
        if (item !== undefined && item !== null && item !== '') query.append(key, String(item));
      }
    }
  }
  const path = [section, ...parts.filter((part) => part !== undefined && part !== null && part !== '')]
    .map((part) => encodeURIComponent(part)).join('/');
  const qs = query.toString();
  return `#/${path}${qs ? `?${qs}` : ''}`;
}

function remember(hash) {
  try { sessionStorage.setItem(STORAGE_KEY, hash); } catch (_unavailable) { /* private mode: deep links still work */ }
}

function recalled() {
  try { return sessionStorage.getItem(STORAGE_KEY) || ''; } catch (_unavailable) { return ''; }
}

export function createRouter(onChange) {
  const current = () => parse(location.hash);

  function changed() {
    if (location.hash) remember(location.hash);
    onChange(current());
  }

  return {
    current,
    start() {
      const saved = recalled();
      if (!location.hash && saved) history.replaceState(null, '', saved);
      window.addEventListener('hashchange', changed);
      changed();
    },
    // Navigating to the route already shown re-renders it, like following a link again.
    navigate(target) {
      if (location.hash === target) changed();
      else location.hash = target;
    },
    // Record state in the URL (filters, the open item) without re-rendering.
    replace(target) {
      if (location.hash === target) return;
      history.replaceState(null, '', target);
      remember(target);
    },
  };
}
