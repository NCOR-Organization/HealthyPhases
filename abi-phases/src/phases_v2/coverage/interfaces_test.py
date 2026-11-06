"""The report's ledger names are the ones the projectors record."""

import ast
from pathlib import Path

from phases_v2.coverage import interfaces
from phases_v2.projection import interfaces as projection
from phases_v2.projection.probabilistic import TARGET


def test_targets_match_the_projection_ledger():
    assert interfaces.GRAPH == projection.GRAPH
    assert interfaces.VECTOR_CHUNKS == projection.VECTOR_CHUNKS
    assert interfaces.VECTOR_ITEMS == projection.VECTOR_ITEMS
    assert interfaces.RELATIONS == TARGET


# Calls that change a dataset, object storage, the vector store or a request.
_WRITES = {
    "write_rows",
    "delete_rows",
    "truncate",
    "recreate",
    "put_object",
    "delete_object",
    "submit",
    "store",
    "insert",
    "record",
    "upsert",
    "save",
    "save_items",
    "save_paths",
    "ensure_datasets",
    "ensure_collection",
}


def test_nothing_in_the_report_writes():
    root = Path(interfaces.__file__).parent
    offenders = []
    for path in sorted(root.rglob("*.py")):
        if path.name.endswith("_test.py"):
            continue
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", getattr(node.func, "id", None))
            if name in _WRITES:
                offenders.append(f"{path.relative_to(root)}:{node.lineno} {name}")
            if any(
                kw.arg == "dry_run" and getattr(kw.value, "value", None) is not True
                for kw in node.keywords
            ):
                offenders.append(f"{path.relative_to(root)}:{node.lineno} dry_run")

    assert offenders == []
