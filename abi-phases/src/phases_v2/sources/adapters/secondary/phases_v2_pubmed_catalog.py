"""Read the public PubMed v1 datasets without importing the publisher."""

from naas_abi_core.services.dataset.DatasetPort import DatasetNotFoundError

from phases_v2.sql import literal


class PubmedCatalog:
    def __init__(self, dataset):
        self.dataset = dataset

    def queries(self):
        try:
            self.dataset.describe("queries", namespace="pubmed")
            rows = self.dataset.query(
                "SELECT query_id, query, created_at, total FROM queries "
                "WHERE contract_version = 1 ORDER BY created_at DESC",
                namespace="pubmed",
            ).rows
        except DatasetNotFoundError:
            return {"available": False, "queries": []}
        return {"available": True, "queries": rows}

    def artifacts(self, query_id):
        try:
            for table in ("artifacts", "query_papers", "papers"):
                self.dataset.describe(table, namespace="pubmed")
            # One SQL statement sees membership, metadata and ready artifacts together.
            return self.dataset.query(
                "SELECT a.*, p.title FROM artifacts a "
                "JOIN query_papers q ON q.pmid = a.pmid "
                "JOIN papers p ON p.pmid = a.pmid "
                "WHERE a.status = 'ready' AND a.contract_version = 1 "
                f"AND q.query_id = {literal(query_id)} ORDER BY a.pmid, a.artifact_id",
                namespace="pubmed",
            ).rows
        except DatasetNotFoundError:
            return []
