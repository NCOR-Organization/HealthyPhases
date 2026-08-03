#!/usr/bin/env python3
"""Reverse search over the PHASES extractions.

Pass a sentence or a set of keywords and get back extracted items, each resolved
to its source chunk and paper -- i.e. the thing the paper claims the system does,
actually done.

    ./search_extractions.py "solitude and stress"
    ./search_extractions.py "Does solitude increase the risk of depression?" --mode semantic
    ./search_extractions.py solitude sport --mode keyword --top 15
    ./search_extractions.py "loneliness in older adults" --by-paper

Modes
  keyword   substring AND-match over extracted_text. Offline, no API call.
  semantic  embeds the query (OpenAI text-embedding-3-large, 3072d) and searches
            Qdrant. Makes ONE outbound API call per query.
  both      (default) runs each and prints them side by side.

Needs: Fuseki on :3030 and -- for semantic -- Qdrant on :6333 plus OPENAI_API_KEY.
Stdlib only.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ABI = os.environ.get("ABI_ROOT", os.path.expanduser("~/dev/ncor/HealthyPhases/abi-phases"))
FUSEKI = os.environ.get("FUSEKI_URL", "http://localhost:3030/ds/sparql")
QDRANT = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION = "extracted_items"
EMBED_MODEL = "text-embedding-3-large"
EMBED_DIMS = 3072
DOC = "http://purl.obolibrary.org/obo/phases/documents.owl#"


def load_env():
    env = {}
    path = os.path.join(ABI, ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8", errors="replace"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                    v = v[1:-1]          # .env values may be quoted
                env[k.strip()] = v
    return env


ENV = load_env()


def sparql(query):
    data = urllib.parse.urlencode({"query": query}).encode()
    req = urllib.request.Request(FUSEKI, data=data)
    req.add_header("Accept", "application/sparql-results+json")
    pw = ENV.get("FUSEKI_ADMIN_PASSWORD")
    if pw:
        import base64
        tok = base64.b64encode(f"admin:{pw}".encode()).decode()
        req.add_header("Authorization", f"Basic {tok}")
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.load(r)
    rows = []
    for b in out["results"]["bindings"]:
        rows.append({k: v["value"] for k, v in b.items()})
    return rows


def paper_name(path):
    return path.rsplit("/", 1)[-1].replace(".pdf", "")


ITEM_BLOCK = f"""
  ?i a <{DOC}ExtractedItem> ;
     <{DOC}extracted_text> ?text ;
     <{DOC}extracted_by> ?e ;
     <{DOC}extracted_from_chunk> ?c .
  OPTIONAL {{ ?e <{DOC}pipeline_name> ?pipeline }}
  ?c <{DOC}chunk_id> ?cid ; <{DOC}chunk_of> ?p .
  ?p <{DOC}path> ?path .
"""


def keyword_search(terms, top):
    filt = " && ".join(
        f'CONTAINS(LCASE(?text), "{t.lower()}")'
        for t in terms if t
    )
    q = f"""SELECT ?text ?pipeline ?cid ?path WHERE {{
{ITEM_BLOCK}
  FILTER({filt})
}} LIMIT {top}"""
    return sparql(q)


def embed(text):
    key = ENV.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not found in .env or environment")
    body = json.dumps(
        {"model": EMBED_MODEL, "input": text, "dimensions": EMBED_DIMS}
    ).encode()
    req = urllib.request.Request("https://api.openai.com/v1/embeddings", data=body)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["data"][0]["embedding"]


def semantic_search(vector, top):
    body = json.dumps(
        {"vector": vector, "limit": top, "with_payload": True}
    ).encode()
    req = urllib.request.Request(
        f"{QDRANT}/collections/{COLLECTION}/points/search", data=body
    )
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        hits = json.load(r)["result"]
    out = []
    for h in hits:
        p = h.get("payload") or {}
        p = p.get("payload", p)
        out.append({
            "score": h.get("score", 0.0),
            "item_id": p.get("extracted_item_id", ""),
            "text": p.get("text", ""),
        })
    return out


def resolve(item_ids):
    """extracted_item_id -> pipeline, chunk, paper."""
    if not item_ids:
        return {}
    values = " ".join(json.dumps(i) for i in item_ids)
    q = f"""SELECT ?iid ?pipeline ?cid ?path WHERE {{
  VALUES ?iid {{ {values} }}
  ?i <{DOC}extracted_item_id> ?iid ;
     <{DOC}extracted_by> ?e ;
     <{DOC}extracted_from_chunk> ?c .
  OPTIONAL {{ ?e <{DOC}pipeline_name> ?pipeline }}
  ?c <{DOC}chunk_id> ?cid ; <{DOC}chunk_of> ?p .
  ?p <{DOC}path> ?path .
}}"""
    return {r["iid"]: r for r in sparql(q)}


def show(title, rows, scored=False):
    print(f"\n\033[1m{title}\033[0m  ({len(rows)} result{'s' if len(rows) != 1 else ''})")
    if not rows:
        print("  no matches")
        return
    print("-" * 78)
    for n, r in enumerate(rows, 1):
        head = f"{n:>2}."
        if scored and r.get("score") is not None:
            head += f" [{r['score']:.3f}]"
        print(f"{head} {r['text']}")
        meta = []
        if r.get("pipeline"):
            meta.append(f"pipeline={r['pipeline']}")
        if r.get("path"):
            meta.append(f"paper={paper_name(r['path'])}")
        if r.get("cid"):
            meta.append(f"chunk={r['cid'][:8]}")
        if meta:
            print(f"    \033[2m{'  ·  '.join(meta)}\033[0m")


def by_paper(rows):
    agg = {}
    for r in rows:
        if not r.get("path"):
            continue
        agg.setdefault(paper_name(r["path"]), []).append(r)
    print(f"\n\033[1mPapers\033[0m  ({len(agg)})")
    print("-" * 78)
    for name, items in sorted(agg.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(items):>3} item(s)  {name}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", nargs="+", help="sentence, or keywords to AND together")
    ap.add_argument("--mode", choices=["keyword", "semantic", "both"], default="both")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--by-paper", action="store_true",
                    help="also aggregate hits by source paper")
    args = ap.parse_args()

    sentence = " ".join(args.query)
    # keyword terms: split the sentence, drop stopwords and the connective "and"
    stop = {"and", "or", "the", "a", "an", "of", "in", "on", "to", "is", "are",
            "does", "do", "for", "with", "that", "this", "it"}
    terms = [w.strip("?.,!\"'").lower() for w in sentence.split()]
    terms = [t for t in terms if t and t not in stop]

    print(f"\n\033[1mQuery:\033[0m {sentence}")
    all_rows = []

    if args.mode in ("keyword", "both"):
        try:
            rows = keyword_search(terms, args.top)
            show(f"Keyword match  ({' AND '.join(terms)})", rows)
            all_rows += rows
        except Exception as e:
            print(f"\n  keyword search failed: {type(e).__name__}: {e}", file=sys.stderr)

    if args.mode in ("semantic", "both"):
        try:
            hits = semantic_search(embed(sentence), args.top)
            meta = resolve([h["item_id"] for h in hits if h["item_id"]])
            for h in hits:
                h.update({k: v for k, v in meta.get(h["item_id"], {}).items()
                          if k != "iid"})
            show("Semantic match  (embedding similarity)", hits, scored=True)
            all_rows += hits
        except Exception as e:
            print(f"\n  semantic search unavailable: {type(e).__name__}: {e}",
                  file=sys.stderr)

    if args.by_paper:
        by_paper(all_rows)
    print()


if __name__ == "__main__":
    main()
