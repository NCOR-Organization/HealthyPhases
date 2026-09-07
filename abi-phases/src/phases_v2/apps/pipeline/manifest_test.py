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


def test_the_app_is_not_named_the_same_as_v1s():
    manifest = json.loads(MANIFEST.read_text())

    assert manifest["name"] != "Reverse Search"


def test_the_page_talks_to_this_modules_api():
    from phases_v2.app.adapters.primary.PipelineAPI import PREFIX

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

    # `${API}` would be the old relative constant; `${API()}` is the resolver.
    assert "${API}" not in text
    assert "API()" in text


def test_a_non_json_response_is_reported_rather_than_dumped():
    # Throwing the raw body showed the user a wall of Next.js HTML.
    text = INDEX.read_text()

    assert "readJson" in text
    assert "Expected JSON from" in text


def test_an_unavailable_model_cannot_be_selected():
    # The registry may not be able to build a declared model; offering it as a
    # selectable choice would just produce a failed run.
    text = INDEX.read_text()

    assert "available === false" in text
    assert "option.disabled = true" in text
    assert "unavailable here" in text


def test_every_prompt_is_selected_by_default():
    # Extracting one dimension of a corpus at a time is the exception; the
    # default should be the whole set.
    text = INDEX.read_text()

    assert 'id="prompt" multiple' in text
    assert "option.selected = true" in text


def test_the_run_submits_every_selected_prompt():
    text = INDEX.read_text()

    assert "prompt_ids:" in text
    assert 'selected($("prompt"))' in text


def test_selecting_a_location_previews_its_documents():
    text = INDEX.read_text()

    assert "refreshDocuments" in text
    assert "/documents?" in text
    assert 'addEventListener("change", refreshDocuments)' in text


def test_the_preview_distinguishes_new_from_already_ingested():
    text = INDEX.read_text()

    assert "already_ingested" in text
    assert ">ingested<" in text
    assert ">new<" in text


def test_the_preview_marks_objects_the_pipeline_cannot_read():
    # The locations list includes other modules' prefixes, so the preview has
    # to distinguish "a paper" from "some other module's file".
    text = INDEX.read_text()

    assert "not a document" in text
    assert "doc.supported" in text
    assert "preview.ingestable" in text
