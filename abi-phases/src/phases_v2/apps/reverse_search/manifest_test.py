"""The app manifest is what the workspace listing reads."""

import json
import pathlib

MANIFEST = pathlib.Path(__file__).parent / "manifest.json"
INDEX = pathlib.Path(__file__).parent / "index.html"


def test_the_manifest_is_valid_json_with_what_the_listing_needs():
    manifest = json.loads(MANIFEST.read_text())

    for field in ("name", "description", "category", "url", "icon_emoji", "version"):
        assert manifest[field], field


def test_the_manifest_points_at_a_page_that_exists():
    manifest = json.loads(MANIFEST.read_text())

    assert manifest["url"].startswith("html:")
    assert (INDEX.parent / manifest["url"].removeprefix("html:")).is_file()


def test_the_app_is_not_named_the_same_as_v1s_or_v2s_pipeline_app():
    manifest = json.loads(MANIFEST.read_text())

    assert manifest["name"] != "Reverse Search"
    assert manifest["name"] != "Phases Pipeline"


def test_the_page_talks_to_this_modules_search_api():
    from phases_v2.app.adapters.primary.SearchAPI import PREFIX

    assert PREFIX in INDEX.read_text()


def test_the_page_declares_a_charset_and_a_title():
    text = INDEX.read_text()

    assert "charset" in text
    assert "<title>" in text


def test_the_page_does_not_assume_the_api_is_same_origin():
    # Bundled apps are served by the Nexus frontend through /app-html/, so a
    # relative fetch reaches Next and returns its 404 page as HTML. The page
    # must resolve the ABI API base from the Nexus runtime config instead.
    text = INDEX.read_text()

    assert "__NEXUS_RUNTIME_CONFIG__" in text
    assert "apiUrl" in text


def test_every_api_call_goes_through_the_resolved_base():
    text = INDEX.read_text()

    # `${API}` would be a stale relative constant; `${API()}` is the resolver.
    assert "${API}" not in text
    assert "API()" in text


def test_a_non_json_response_is_reported_rather_than_dumped():
    # Throwing the raw body showed the user a wall of Next.js HTML.
    text = INDEX.read_text()

    assert "readJson" in text
    assert "Expected JSON from" in text


def test_the_facet_and_field_names_match_v2s_vocabulary_not_v1s():
    # v1 called this "pipeline"; v2 has no pipelines, only prompts.
    text = INDEX.read_text()

    assert "pipeline" not in text.lower()
    assert '"prompt"' in text or "'prompt'" in text
    assert "prompt_name" in text
