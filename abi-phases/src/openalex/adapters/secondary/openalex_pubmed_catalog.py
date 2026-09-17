"""Read the published PubMed dataset contract; no PubMed code dependency."""

from naas_abi_core.services.dataset.DatasetPort import DatasetNotFoundError

from openalex.adapters.secondary.openalex_dataset_store import literal
from openalex.domain.openalex_errors import EnrichmentNotFound


class PubmedCatalog:
    def __init__(self, dataset):
        self.dataset = dataset

    def queries(self):
        try:
            self.dataset.describe("queries", namespace="pubmed")
        except DatasetNotFoundError:
            return []
        return self.dataset.query(
            "SELECT * FROM queries ORDER BY created_at DESC", namespace="pubmed"
        ).rows

    def capture(self, query_id):
        try:
            snapshot = self.dataset.describe(
                "query_papers", namespace="pubmed"
            ).snapshot_id
        except DatasetNotFoundError as exc:
            raise EnrichmentNotFound("PubMed dataset is unavailable") from exc
        query = self.dataset.query(
            f"SELECT * FROM queries WHERE query_id = {literal(query_id)}",
            namespace="pubmed",
            snapshot_id=snapshot,
        ).rows
        if not query:
            raise EnrichmentNotFound(query_id)
        total = self.dataset.query(
            f"SELECT count(*) AS n FROM query_papers m JOIN papers p ON p.pmid=m.pmid WHERE m.query_id={literal(query_id)}",
            namespace="pubmed",
            snapshot_id=snapshot,
        ).rows[0]["n"]
        return query[0], snapshot, total

    def page(self, query_id, snapshot, cursor, limit):
        return self.dataset.query(
            f"SELECT p.* FROM query_papers m JOIN papers p ON p.pmid=m.pmid WHERE m.query_id={literal(query_id)} AND p.pmid > {literal(cursor)} ORDER BY p.pmid LIMIT {int(limit)}",
            namespace="pubmed",
            snapshot_id=int(snapshot),
        ).rows
