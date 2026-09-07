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
