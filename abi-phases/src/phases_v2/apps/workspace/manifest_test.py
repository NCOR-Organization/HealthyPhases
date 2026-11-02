"""The workspace app as Nexus lists, serves and packages it."""

import json
import pathlib
import re
import tomllib

APP = pathlib.Path(__file__).parent
MANIFEST = APP / "manifest.json"
INDEX = APP / "index.html"
SRC = APP.parents[2]
PYPROJECT = SRC.parent / "pyproject.toml"

# What Nexus serves next to an app's index.html under /app-html/ (naas-abi
# apps adapter, _APP_ASSET_SUFFIXES). Anything else is not reachable.
SERVED = {".css", ".html", ".js", ".json", ".mjs", ".png", ".svg", ".ico", ".woff", ".woff2"}
IMPORT = re.compile(r"""(?:import|export)\s[^'"]*?from\s+['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]""")


def _modules():
    """Every ES module reachable from the page, following relative imports."""
    entry = re.search(r'<script type="module" src="([^"]+)"', INDEX.read_text()).group(1)
    pending, seen = [(APP / entry).resolve()], set()
    while pending:
        path = pending.pop()
        if path in seen:
            continue
        seen.add(path)
        for match in IMPORT.finditer(path.read_text()):
            target = match.group(1) or match.group(2)
            assert target.startswith("./") or target.startswith("../"), (path.name, target)
            pending.append((path.parent / target).resolve())
    return seen


def test_the_manifest_is_valid_json_with_what_the_listing_needs():
    manifest = json.loads(MANIFEST.read_text())

    for field in ("name", "description", "category", "url", "icon_emoji", "version"):
        assert manifest[field], field
    assert manifest["name"] == "HealthyPhases"


def test_the_manifest_points_at_a_page_that_exists():
    manifest = json.loads(MANIFEST.read_text())

    assert manifest["url"].startswith("html:")
    assert (APP / manifest["url"].removeprefix("html:")).is_file()


def test_healthyphases_is_the_only_app_these_modules_list():
    manifests = sorted(
        path.relative_to(SRC).as_posix()
        for module in ("phases", "phases_v2", "pubmed", "openalex")
        for path in (SRC / module / "apps").glob("*/manifest.json")
    )

    assert manifests == ["phases_v2/apps/workspace/manifest.json"]


def test_the_page_declares_a_charset_a_title_and_a_viewport():
    text = INDEX.read_text()

    assert 'charset="utf-8"' in text
    assert "<title>HealthyPhases</title>" in text
    assert 'name="viewport"' in text


def test_every_module_the_page_loads_exists_and_is_served_by_nexus():
    modules = _modules()

    assert len(modules) >= 10
    for path in modules:
        assert path.is_file(), path
        assert path.suffix in SERVED, path
        assert APP in path.parents, path


def test_the_stylesheet_is_local_and_served():
    hrefs = re.findall(r'<link rel="stylesheet" href="([^"]+)"', INDEX.read_text())

    assert hrefs == ["./css/app.css"]
    assert (APP / hrefs[0]).is_file()


def test_nothing_loads_from_another_origin():
    # No CDN: the app must work wherever Nexus serves it, offline included.
    sources = [INDEX, *APP.glob("css/*.css"), *APP.glob("js/**/*.js")]
    for path in sources:
        text = path.read_text()
        # Links out (to PubMed, OpenAlex) are fine; loaded resources are not.
        assert not re.search(r"""<(?:script|link|img|iframe|source)\b[^>]*\b(?:src|href)=["'](?:https?:)?//""", text), path
        assert not re.search(r"""(?:from|import)\s*\(?\s*['"](?:https?:)?//""", text), path
        assert not re.search(r"""url\(\s*['"]?(?:https?:)?//""", text), path
        assert "@import" not in text, path


def test_the_api_client_resolves_the_nexus_runtime_config_and_reports_non_json():
    # Bundled apps are served by the Nexus frontend through /app-html/, so a
    # relative fetch reaches Next and returns its 404 page as HTML.
    text = (APP / "js" / "api.js").read_text()

    assert "__NEXUS_RUNTIME_CONFIG__" in text
    assert "apiUrl" in text
    assert "Expected JSON from" in text
    assert "credentials: 'include'" in text
    assert "nexus-auth" in text


def test_the_client_talks_to_every_module_api():
    from phases_v2.app.adapters.primary.PipelineAPI import PREFIX as PIPELINE
    from phases_v2.app.adapters.primary.SearchAPI import PREFIX as SEARCH

    prefixes = {PIPELINE, SEARCH}
    for module in ("pubmed/adapters/primary/pubmed_api.py", "openalex/adapters/primary/openalex_api.py"):
        prefixes.add(re.search(r'prefix="([^"]+)"', (SRC / module).read_text()).group(1))
    text = (APP / "js" / "api.js").read_text()

    for prefix in prefixes:
        assert f"'{prefix}'" in text, prefix


def test_no_module_calls_fetch_except_the_api_client():
    for path in APP.glob("js/**/*.js"):
        if path.name != "api.js":
            assert "fetch(" not in path.read_text().replace("fetchBlob(", ""), path


def test_every_section_exposes_refresh():
    for name in ("overview", "library", "collections", "prompts", "runs", "search"):
        text = (APP / "js" / "sections" / f"{name}.js").read_text()
        assert "export function create(root, ctx)" in text, name
        assert re.search(r"\brefresh\b", text.split("return {")[-1]), name


def test_the_package_ships_every_file_the_app_serves():
    globs = tomllib.loads(PYPROJECT.read_text())["tool"]["setuptools"]["package-data"]["phases_v2"]
    package = SRC / "phases_v2"
    shipped = {path for pattern in globs for path in package.glob(pattern)}
    served = [p for p in APP.rglob("*") if p.is_file() and p.suffix in SERVED]

    assert served
    for path in served:
        assert path in shipped, path.relative_to(package).as_posix()



def test_the_manifest_binds_the_nexus_right_pane_to_the_assistant():
    """With the app open, Nexus loads this agent in its right pane."""
    manifest = json.loads(MANIFEST.read_text())

    assert manifest["agent"] == "phases_v2 WorkspaceAssistantAgent"


def test_every_section_says_how_to_open_the_assistant():
    sidebar = re.search(r'<p class="sidebar-foot">(.*?)</p>', INDEX.read_text()).group(1)

    assert "Open the Assistant with the panel button at the top right of Nexus" in sidebar
    # Nexus catches the shortcut on its own page, not inside the app's frame.
    assert "⌘K / Ctrl+K after clicking outside the app" in sidebar
