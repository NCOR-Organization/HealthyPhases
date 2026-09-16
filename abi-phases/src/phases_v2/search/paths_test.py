import pytest

from phases_v2.search.paths import matches_path, parent_paths, source_folder


def test_folder_comes_from_prefix_and_nested_object_key():
    assert (
        source_folder("/phases_v2/solitude/", "paid/nested/paper.pdf")
        == "phases_v2/solitude/paid/nested"
    )
    assert source_folder("phases_v2/solitude", "paper.pdf") == "phases_v2/solitude"
    assert source_folder(None, "folder/paper.pdf") == "folder"
    assert source_folder(None, None) is None


@pytest.mark.parametrize(
    "folder,expected",
    [
        ("phases_v2/solitude", True),
        ("phases_v2/solitude/paid", True),
        ("phases_v2/solitude-other", False),
        ("phases_v2", False),
        (None, False),
    ],
)
def test_paths_include_descendants_but_not_similarly_named_siblings(folder, expected):
    assert matches_path(folder, ["/phases_v2/solitude/"]) is expected


def test_parent_choices_are_deduplicated_and_patterns_are_literal():
    assert parent_paths(["root/a/b", "root/a"]) == ["root", "root/a", "root/a/b"]
    assert not matches_path("root/abc", ["root/%", "root/_"])
    assert not matches_path("root/a", ["/", ""])
