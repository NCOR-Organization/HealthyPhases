"""Read the public PubMed v1 datasets without importing the publisher."""

from google.protobuf.json_format import MessageToDict
from naas_abi_core.services.dataset.DatasetPort import DatasetNotFoundError

from phases_v2.app.contracts.app_validation import validate_command
from phases_v2.sql import in_list, literal


class PubmedCatalog:
    def __init__(self, dataset):
        self.dataset = dataset

    def queries(self):
        try:
            self.dataset.describe("queries", namespace="pubmed")
            rows = self.dataset.query(
                "SELECT q.query_id, q.query, q.created_at, q.total, "
                "COALESCE(p.published_paper_count, 0) AS published_paper_count, "
                "COALESCE(r.last_ingested_at, '') AS last_ingested_at "
                "FROM queries q LEFT JOIN ("
                "SELECT m.query_id, COUNT(DISTINCT a.pmid) AS published_paper_count "
                "FROM query_papers m JOIN artifacts a ON a.pmid = m.pmid "
                "JOIN papers p ON p.pmid = a.pmid "
                "WHERE a.status = 'ready' AND a.contract_version = 1 "
                "GROUP BY m.query_id) p ON p.query_id = q.query_id "
                "LEFT JOIN (SELECT query_id, MAX(NULLIF(finished_at, '')) "
                "AS last_ingested_at FROM run_requests "
                "WHERE status IN ('succeeded', 'partial') GROUP BY query_id) r "
                "ON r.query_id = q.query_id "
                "WHERE q.contract_version = 1 ORDER BY q.created_at DESC, q.query_id",
                namespace="pubmed",
            ).rows
        except DatasetNotFoundError:
            return {"available": False, "queries": []}
        return MessageToDict(
            validate_command("PubmedQueryList", {"available": True, "queries": rows}),
            preserving_proto_field_name=True,
            always_print_fields_with_no_presence=True,
        )

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

    def paper_artifacts(self, pmid):
        """One paper's ready PDFs, the way :meth:`artifacts` reads a query's."""
        try:
            for table in ("artifacts", "papers"):
                self.dataset.describe(table, namespace="pubmed")
            return self.dataset.query(
                "SELECT a.*, p.title FROM artifacts a "
                "JOIN papers p ON p.pmid = a.pmid "
                "WHERE a.status = 'ready' AND a.contract_version = 1 "
                f"AND a.pmid = {literal(pmid)} ORDER BY a.artifact_id",
                namespace="pubmed",
            ).rows
        except DatasetNotFoundError:
            return []

    def query_texts(self, query_ids):
        """Saved searches' query text by id; unknown ids are left out."""
        if not query_ids:
            return {}
        try:
            self.dataset.describe("queries", namespace="pubmed")
            rows = self.dataset.query(
                "SELECT query_id, query FROM queries "
                f"WHERE query_id IN {in_list(sorted(set(query_ids)))}",
                namespace="pubmed",
            ).rows
        except DatasetNotFoundError:
            return {}
        return {row["query_id"]: row["query"] for row in rows}

    def titles(self, pmids):
        if not pmids:
            return {}
        try:
            self.dataset.describe("papers", namespace="pubmed")
            rows = self.dataset.query(
                "SELECT pmid, title FROM papers "
                f"WHERE pmid IN {in_list(sorted(set(pmids)))}",
                namespace="pubmed",
            ).rows
        except DatasetNotFoundError:
            return {}
        return {row["pmid"]: row["title"] for row in rows}
