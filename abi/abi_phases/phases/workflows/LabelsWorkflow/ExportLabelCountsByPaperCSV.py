from __future__ import annotations

import argparse
import csv
from pathlib import Path

from abi_phases.phases import ABIModule


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


def build_query(path_tokens: list[str] | None) -> str:
    outer_filter = _build_path_filter("?path", path_tokens)
    inner_filter = _build_path_filter("?path_all", path_tokens)

    return f"""PREFIX phases-label: <http://purl.obolibrary.org/obo/phases/labels.owl#>
PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>

SELECT
  ?label_text
  ?path
  (COUNT(?label) AS ?occurrence_count_in_paper)
  ?total_occurrence_count
  ?distinct_paper_count
WHERE {{
  ?label a phases-label:ExtractedLabel ;
         phases-label:label_text ?label_text ;
         phases-label:label_from_chunk ?chunk .
  ?chunk phases-doc:chunk_of ?paper .
  ?paper phases-doc:path ?path .

  {outer_filter}

  {{
    SELECT
      ?label_text
      (COUNT(?label_all) AS ?total_occurrence_count)
      (COUNT(DISTINCT ?path_all) AS ?distinct_paper_count)
    WHERE {{
      ?label_all a phases-label:ExtractedLabel ;
                 phases-label:label_text ?label_text ;
                 phases-label:label_from_chunk ?chunk_all .
      ?chunk_all phases-doc:chunk_of ?paper_all .
      ?paper_all phases-doc:path ?path_all .

      {inner_filter}
    }}
    GROUP BY ?label_text
  }}
}}
GROUP BY
  ?label_text
  ?path
  ?total_occurrence_count
  ?distinct_paper_count
ORDER BY DESC(?distinct_paper_count) DESC(?total_occurrence_count) ?label_text ?path
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export label counts per paper path and global aggregates"
    )
    parser.add_argument(
        "--output-csv-path",
        type=str,
        default=str(Path(__file__).with_name("label_counts_by_paper.csv")),
        help="Output CSV path",
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
    rows = module.engine.services.triple_store.query(build_query(args.path_tokens))

    output_path = Path(args.output_csv_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(
            [
                "label_text",
                "path",
                "occurrence_count_in_paper",
                "total_occurrence_count",
                "distinct_paper_count",
            ]
        )
        for row in rows:
            if isinstance(row, bool):
                continue
            values = tuple(row)
            if len(values) != 5:
                continue

            (
                label_text,
                path,
                occurrence_count_in_paper,
                total_occurrence_count,
                distinct_paper_count,
            ) = values

            writer.writerow(
                [
                    str(label_text),
                    str(path),
                    int(str(occurrence_count_in_paper)),
                    int(str(total_occurrence_count)),
                    int(str(distinct_paper_count)),
                ]
            )
            written += 1

    print(f"Wrote {written} label-paper rows to: {output_path}", flush=True)


if __name__ == "__main__":
    main()
