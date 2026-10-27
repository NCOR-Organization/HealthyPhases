"""Resolving a collection into the exact documents it holds."""

from phases_v2.paper_collections.domain import (
    add_members,
    folder_member,
    legacy_members,
    member_from_command,
    resolve,
)
from phases_v2.paper_collections.fakes import FakeMemberSources
from phases_v2.paper_collections.interfaces import Artifact

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
QUERY = "00000000-0000-4000-8000-000000000001"


def pubmed(pmid, sha):
    return Artifact(
        "pubmed/papers", f"{pmid}.pdf", sha, f"Title {pmid}", f"art-{pmid}", pmid
    )


def query_member():
    return member_from_command({"pubmed_query": {"query_id": QUERY}})


def pdf_only(name):
    return name.endswith(".pdf")


def test_an_empty_collection_resolves_to_nothing():
    resolution = resolve([], FakeMemberSources())

    assert resolution.papers == []
    assert resolution.manifest() == []
    assert resolution.paper_ids() == []


def test_a_member_naming_nothing_counts_zero_without_failing():
    members = [folder_member("phases_v2/empty"), query_member()]

    resolution = resolve(members, FakeMemberSources())

    assert resolution.papers == []
    assert set(resolution.member_counts.values()) == {0}
    assert resolution.failed == {}


def test_the_same_content_through_several_members_is_one_paper():
    shared = pubmed("1", SHA_A)
    sources = FakeMemberSources(
        queries={QUERY: [shared, pubmed("2", SHA_B)]},
        pmids={"1": [shared]},
        # The same PDF uploaded into a folder: same content, another path.
        folders={"phases_v2/mine": [Artifact("phases_v2/mine", f"{SHA_A}/copy.pdf")]},
    )
    members = [
        query_member(),
        member_from_command({"paper": {"pmid": "1"}}),
        folder_member("phases_v2/mine"),
    ]

    resolution = resolve(members, sources)

    assert sorted(resolution.paper_ids()) == [SHA_A, SHA_B]
    first = next(p for p in resolution.papers if p.paper_id == SHA_A)
    # The first member to name it keeps its storage location and title.
    assert first.artifact.pmid == "1"
    assert first.member_ids == [m["member_id"] for m in members]
    assert [resolution.member_counts[m["member_id"]] for m in members] == [2, 1, 1]


def test_nested_folders_list_a_document_once():
    sources = FakeMemberSources(
        folders={
            "phases_v2/a": [Artifact("phases_v2/a", "b/x.pdf")],
            "phases_v2/a/b": [Artifact("phases_v2/a/b", "x.pdf")],
        }
    )

    resolution = resolve(
        [folder_member("phases_v2/a"), folder_member("phases_v2/a/b")], sources
    )

    assert len(resolution.papers) == 1
    assert resolution.papers[0].paper_id is None
    assert resolution.manifest() == [
        {
            "storage_prefix": "phases_v2/a",
            "storage_key": "b/x.pdf",
            "content_sha256": "",
            "artifact_id": "",
        }
    ]


def test_a_folder_document_ingested_before_is_known_by_its_content():
    stored = Artifact("phases_v2/a", "x.pdf", SHA_C, "x.pdf")
    sources = FakeMemberSources(
        folders={"phases_v2/a": [Artifact("phases_v2/a", "x.pdf")]},
        ingested={SHA_C: stored},
    )
    members = [
        folder_member("phases_v2/a"),
        member_from_command({"paper": {"paper_id": SHA_C}}),
    ]

    resolution = resolve(members, sources)

    assert resolution.paper_ids() == [SHA_C]
    assert resolution.manifest()[0]["content_sha256"] == SHA_C


def test_a_pubmed_query_member_follows_newly_published_papers():
    sources = FakeMemberSources(queries={QUERY: [pubmed("1", SHA_A)]})
    members = [query_member()]
    assert resolve(members, sources).paper_ids() == [SHA_A]

    # Published later, with nothing changed on the collection.
    sources.queries[QUERY].append(pubmed("2", SHA_B))

    assert resolve(members, sources).paper_ids() == [SHA_A, SHA_B]


def test_documents_no_renderer_reads_are_counted_not_listed():
    sources = FakeMemberSources(
        folders={
            "phases_v2/a": [
                Artifact("phases_v2/a", "x.pdf"),
                Artifact("phases_v2/a", "notes.txt"),
            ]
        }
    )

    resolution = resolve([folder_member("phases_v2/a")], sources, pdf_only)

    assert [p.artifact.storage_key for p in resolution.papers] == ["x.pdf"]
    assert resolution.unsupported == 1


def test_an_unreadable_member_is_reported_and_the_rest_still_resolve():
    sources = FakeMemberSources(
        unreachable={"phases_v2/down"}, queries={QUERY: [pubmed("1", SHA_A)]}
    )
    down = folder_member("phases_v2/down")

    resolution = resolve([down, query_member()], sources)

    assert resolution.paper_ids() == [SHA_A]
    assert resolution.failed == {down["member_id"]: "Could not read phases_v2/down"}


def test_legacy_locations_become_folder_members_without_loss():
    members = legacy_members(["phases_v2/a", "phases_v2/b", "phases_v2/a"])

    assert [(m["kind"], m["prefix"]) for m in members] == [
        ("folder", "phases_v2/a"),
        ("folder", "phases_v2/b"),
    ]
    sources = FakeMemberSources(
        folders={
            "phases_v2/a": [Artifact("phases_v2/a", "x.pdf")],
            "phases_v2/b": [Artifact("phases_v2/b", "y.pdf")],
        }
    )
    assert len(resolve(members, sources).papers) == 2


def test_adding_a_member_twice_keeps_one():
    first = member_from_command({"paper": {"pmid": "7"}})
    again = member_from_command({"paper": {"pmid": "7"}})
    other = member_from_command({"paper": {"paper_id": SHA_A}})

    members = add_members([first], [again, other, other])

    assert [m["member_id"] for m in members] == [
        first["member_id"],
        other["member_id"],
    ]
    # An ingested paper and a PMID never share an id.
    assert first["member_id"] != other["member_id"]
