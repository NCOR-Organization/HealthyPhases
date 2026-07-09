from __future__ import annotations

import argparse
import csv
from pathlib import Path

from phases import ABIModule


def build_query(path_tokens: list[str] | None) -> str:
    filters: list[str] = []
    if path_tokens:
        for token in path_tokens:
            clean = token.strip().lower()
            if clean:
                filters.append(f'CONTAINS(LCASE(STR(?path)), "{clean}")')

    where_filter = ""
    if filters:
        where_filter = "FILTER(" + " || ".join(filters) + ")"

    return f"""PREFIX phases-label: <http://purl.obolibrary.org/obo/phases/labels.owl#>
PREFIX phases-doc: <http://purl.obolibrary.org/obo/phases/documents.owl#>

SELECT
  ?label_text
  (COUNT(DISTINCT ?path) AS ?paper_count)
  (COUNT(?label) AS ?occurrence_count)
WHERE {{
  ?label a phases-label:ExtractedLabel ;
         phases-label:label_text ?label_text ;
         phases-label:label_from_chunk ?chunk .

  ?chunk phases-doc:chunk_of ?pdf_paper_file .
  ?pdf_paper_file phases-doc:path ?path .

  {where_filter}
}}
GROUP BY ?label_text
ORDER BY DESC(?paper_count) DESC(?occurrence_count) ?label_text
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export extracted label counts to CSV (distinct by paper path)"
    )
    parser.add_argument(
        "--output-csv-path",
        type=str,
        default=str(Path(__file__).with_name("label_counts.csv")),
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
    query = build_query(args.path_tokens)
    rows = module.engine.services.triple_store.query(query)

    output_path = Path(args.output_csv_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["label_text", "paper_count", "occurrence_count"])
        for row in rows:
            if isinstance(row, bool):
                continue
            values = tuple(row)
            if len(values) != 3:
                continue
            label_text, paper_count, occurrence_count = values
            writer.writerow(
                [
                    str(label_text),
                    int(str(paper_count)),
                    int(str(occurrence_count)),
                ]
            )
            written += 1

    print(f"Wrote {written} label rows to: {output_path}", flush=True)


if __name__ == "__main__":
    main()
