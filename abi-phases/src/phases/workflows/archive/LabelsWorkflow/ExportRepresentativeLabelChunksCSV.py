from __future__ import annotations

import argparse
import csv
from pathlib import Path

from phases import ABIModule


def _build_path_filter(var_name: str, path_tokens: list[str] | None) -> str:
    filters: list[str] = []
    if path_tokens:
        for token in path_tokens:
            clean = token.strip().lower()
            if clean:
                filters.append(f'CONTAINS(LCASE(STR({var_name})), "{clean}")')

    if not filters:
        return ""

    return "FILTER(" + " || ".join(filters) + ")"


def build_query(path_tokens: list[str] | None, min_distinct_paper_count: int) -> str:
    outer_filter = _build_path_filter("?path", path_tokens)
    inner_filter = _build_path_filter("?path_all", path_tokens)

    return f"""PREFIX phases-label: <http://purl.obolibrary.org/obo/phases/labels.owl#>
PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>

SELECT ?label_text ?chunk_id ?path ?chunk_text
WHERE {{
  {{
    SELECT ?label_text
    WHERE {{
      ?label_all a phases-label:ExtractedLabel ;
                 phases-label:label_text ?label_text ;
                 phases-label:label_from_chunk ?chunk_all .
      ?chunk_all phases-doc:chunk_of ?paper_all .
      ?paper_all phases-doc:path ?path_all .

      {inner_filter}
    }}
    GROUP BY ?label_text
    HAVING (COUNT(DISTINCT ?path_all) > {min_distinct_paper_count})
  }}

  ?label a phases-label:ExtractedLabel ;
         phases-label:label_text ?label_text ;
         phases-label:label_from_chunk ?chunk .
  OPTIONAL {{ ?label phases-label:source_chunk_id ?chunk_id . }}
  ?chunk phases-doc:text ?chunk_text ;
         phases-doc:chunk_of ?paper .
  ?paper phases-doc:path ?path .

  {outer_filter}
}}
ORDER BY ?label_text ?path
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export label/path/chunk_text for labels above distinct paper threshold"
        )
    )
    parser.add_argument(
        "--output-csv-path",
        type=str,
        default=str(Path(__file__).with_name("representative_label_chunks.csv")),
        help="Output CSV path",
    )
    parser.add_argument(
        "--min-distinct-paper-count",
        type=int,
        default=2,
        help="Keep labels with distinct_paper_count strictly greater than this value",
    )
    parser.add_argument(
        "--path-token",
        dest="path_tokens",
        action="append",
        default=["solitude", "paid"],
        help=(
            "Path token filter (repeatable). "
            "Default includes both 'solitude' and 'paid'."
        ),
    )
    args = parser.parse_args()

    module = ABIModule.get_instance()
    rows = module.engine.services.triple_store.query(
        build_query(
            path_tokens=args.path_tokens,
            min_distinct_paper_count=max(0, args.min_distinct_paper_count),
        )
    )

    output_path = Path(args.output_csv_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["label_text", "chunk_id", "path", "chunk_text"])
        for row in rows:
            if isinstance(row, bool):
                continue
            values = tuple(row)
            if len(values) != 4:
                continue
            label_text, chunk_id, path, chunk_text = values
            writer.writerow(
                [str(label_text), str(chunk_id or ""), str(path), str(chunk_text)]
            )
            written += 1

    print(
        f"Wrote {written} rows to: {output_path} "
        f"(distinct_paper_count > {args.min_distinct_paper_count})",
        flush=True,
    )


if __name__ == "__main__":
    main()
