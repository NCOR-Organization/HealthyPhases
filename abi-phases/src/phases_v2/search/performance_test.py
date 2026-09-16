from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest

from phases_v2.search.domain import SearchService
from phases_v2.search.fakes import FakeExtractedItems, FakeItem, FakeSemanticIndex
from phases_v2.search.models import ItemLocation
from phases_v2.search.result_cache import SearchResultCache


def test_pages_and_export_reuse_ranking_and_only_locate_requested_items():
    records = [FakeItem(str(i), "claim", ItemLocation()) for i in range(10000)]
    index = FakeSemanticIndex(records)
    index.search_all = Mock(wraps=index.search_all)
    items = FakeExtractedItems(records)
    items.resolve_locations = Mock(wraps=items.resolve_locations)
    items.snapshot = lambda: 42
    items.at_snapshot = lambda snapshot: items
    service = SearchService(index, items)
    for offset in (0, 10):
        view, snapshot = service.read_view()
        hits, total = view.page("semantic", "claim", limit=10, offset=offset)
        assert len(hits) == 10 and total == 10000 and snapshot == 42
    assert index.search_all.call_count == 1
    assert [len(c.args[0]) for c in items.resolve_locations.call_args_list] == [10, 10]
    assert len(list(view.all_hits("semantic", "claim"))) == 10000
    assert index.search_all.call_count == 1
    view, _ = service.read_view(43)
    view.page("semantic", "claim")
    assert index.search_all.call_count == 2


def test_filters_apply_before_count_without_full_provenance_reads():
    records = [
        FakeItem(str(i), "claim", ItemLocation(prompt_name="yes" if i >= 900 else "no"))
        for i in range(1000)
    ]
    items = FakeExtractedItems(records)
    items.resolve_locations = Mock(wraps=items.resolve_locations)
    service = SearchService(FakeSemanticIndex(records), items)
    hits, total = service.page("semantic", "claim", limit=10, prompts=["yes"])
    assert total == 100 and len(hits) == 10
    assert all(h.prompt_name == "yes" for h in hits)
    assert len(items.resolve_locations.call_args.args[0]) == 10
    assert service.page("semantic", "claim", prompts=["missing"]) == ([], 0)


def test_keyword_count_reused_but_filters_have_separate_counts():
    items = FakeExtractedItems(
        [FakeItem("1", "claim", ItemLocation(prompt_name="yes"))]
    )
    items.keyword_count = Mock(wraps=items.keyword_count)
    service = SearchService(FakeSemanticIndex(), items)
    service.page("keyword", "claim")
    service.page("keyword", "claim", offset=10)
    assert items.keyword_count.call_count == 1
    assert service.page("keyword", "claim", prompts=["missing"]) == ([], 0)
    assert items.keyword_count.call_count == 2


def test_cache_expiry_eviction_and_oversized_values():
    now = [0]
    cache = SearchResultCache(max_entries=1, ttl=5, clock=lambda: now[0])
    compute = Mock(return_value=("value",))
    cache.get_or_compute("a", compute)
    cache.get_or_compute("a", compute)
    assert compute.call_count == 1
    now[0] = 5
    cache.get_or_compute("a", compute)
    cache.get_or_compute("b", compute)
    cache.get_or_compute("a", compute)
    assert compute.call_count == 4
    small = SearchResultCache(max_bytes=1)
    small.get_or_compute("a", compute)
    small.get_or_compute("a", compute)
    assert compute.call_count == 6


def test_cache_coalesces_concurrent_calls_and_retries_failures():
    cache = SearchResultCache()
    started, release = Event(), Event()

    def compute():
        started.set()
        assert release.wait(3)
        return ("result",)

    work = Mock(side_effect=compute)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.get_or_compute, "a", work)
        assert started.wait(3)
        second = pool.submit(cache.get_or_compute, "a", work)
        release.set()
        assert first.result() == second.result() == ("result",)
    assert work.call_count == 1
    fail = Mock(side_effect=[RuntimeError("unavailable"), ("ok",)])
    with pytest.raises(RuntimeError):
        cache.get_or_compute("b", fail)
    assert cache.get_or_compute("b", fail) == ("ok",)
