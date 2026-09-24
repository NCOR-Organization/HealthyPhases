# /// script
# requires-python = ">=3.12"
# dependencies = ["qdrant-client>=1.10", "numpy", "pyarrow"]
# ///
"""One-off: copy the phases_v2 Qdrant collections to local files for offline analysis.

Writes, per collection, ``<name>.vectors.npy`` (float32, one row per point) and
``<name>.meta.parquet`` (the flat payload plus the item text), rows aligned.

    uv run scripts/term_clustering/dump_vectors.py --host 100.64.0.9

Idempotent: an existing dump is skipped unless ``--force`` is given.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from qdrant_client import QdrantClient

COLLECTIONS = ("phases_v2_extracted_items", "phases_v2_chunks")
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "storage/spikes/term_clustering"
SCROLL_BATCH = 512


def connect(host: str, port: int, grpc_port: int) -> QdrantClient:
    # gRPC moves 3072-d vectors far cheaper than JSON; fall back if it is not exposed.
    try:
        client = QdrantClient(host=host, port=port, grpc_port=grpc_port, prefer_grpc=True, timeout=120)
        client.get_collections()
        return client
    except Exception as exc:  # noqa: BLE001 - any transport failure means "try HTTP"
        print(f"gRPC unavailable ({exc.__class__.__name__}), using HTTP", file=sys.stderr)
        return QdrantClient(host=host, port=port, prefer_grpc=False, timeout=120)


def flatten(payload: dict) -> dict:
    """The sink stores metadata at the top level and ``{"text": ...}`` under ``payload``."""
    row = {k: v for k, v in payload.items() if k != "payload"}
    inner = payload.get("payload") or {}
    row["text"] = inner.get("text", "")
    # Lists/dicts become JSON strings so the parquet schema stays flat.
    return {k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in row.items()}


def dump(client: QdrantClient, name: str, out: Path, force: bool) -> None:
    vec_path, meta_path = out / f"{name}.vectors.npy", out / f"{name}.meta.parquet"
    if vec_path.exists() and meta_path.exists() and not force:
        print(f"{name}: already dumped, skipping (use --force to redo)")
        return

    total = client.count(name, exact=True).count
    vectors: list[np.ndarray] = []
    rows: list[dict] = []
    offset = None
    while True:
        points, offset = client.scroll(
            name, limit=SCROLL_BATCH, offset=offset, with_payload=True, with_vectors=True
        )
        for p in points:
            vectors.append(np.asarray(p.vector, dtype=np.float32))
            rows.append({"point_id": str(p.id)} | flatten(p.payload or {}))
        print(f"\r{name}: {len(rows)}/{total}", end="", file=sys.stderr, flush=True)
        if offset is None:
            break
    print(file=sys.stderr)

    if len(rows) != total:
        raise RuntimeError(f"{name}: scrolled {len(rows)} points but the collection reports {total}")

    out.mkdir(parents=True, exist_ok=True)
    np.save(vec_path, np.vstack(vectors) if vectors else np.zeros((0, 0), np.float32))
    pq.write_table(pa.Table.from_pylist(rows), meta_path)
    print(f"{name}: wrote {len(rows)} rows -> {vec_path.name}, {meta_path.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=6333)
    parser.add_argument("--grpc-port", type=int, default=6334)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--collections", nargs="+", default=COLLECTIONS)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    client = connect(args.host, args.port, args.grpc_port)
    for name in args.collections:
        dump(client, name, args.out, args.force)


if __name__ == "__main__":
    main()
