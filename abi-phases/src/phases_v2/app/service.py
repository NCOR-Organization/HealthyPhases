"""What the app needs, assembled from the module's domains.

Kept separate from the HTTP adapter so the app's behaviour can be tested
without a web server, and so the endpoints stay a thin translation layer.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from datetime import datetime
from typing import Any

from phases_v2.app.app_resources import AppResources
from phases_v2.app.papers_catalog import PapersCatalog
from phases_v2.app.pipeline_management import ManagementUnavailable, PipelineManagement
from phases_v2.app.prompt_versions import PromptVersions
from phases_v2.chunking.chunkers import DECLARED_CHUNKERS
from phases_v2.models.catalog import DECLARED_MODELS
from phases_v2.requests.domain import submit
from phases_v2.requests.interfaces import RunRequest

#: A request over a collection reads only its manifest; see ``ingest_papers_op``.
COLLECTION_SOURCE = "dataset:collection:"


class PipelineAppService:
    def __init__(
        self,
        request_store,
        object_storage=None,
        rows=None,
        is_model_available=None,
        renderer=None,
        papers_root: str = "phases_v2",
        pubmed_catalog=None,
        collection_sources=None,
        model_factory=None,
        try_timeout_seconds: float = 90.0,
    ):
        self._pubmed = pubmed_catalog
        #: Builds a model for a prompt try: ``(model_id, output_key) -> model``.
        self._model_factory = model_factory
        self._try_timeout_seconds = try_timeout_seconds
        self._requests = request_store
        self._storage = object_storage
        self._rows = rows
        # A declared model is only usable if this deployment's model registry
        # can actually build it — `google` needs a provider nothing registers
        # without an API key, for instance. Offering a choice that fails at run
        # time is worse than not offering it.
        self._is_model_available = is_model_available
        # Used only to say which documents a run would actually read. The
        # object-storage root holds other modules' data, so "how many files are
        # here" is not the same as "how many papers".
        self._renderer = renderer
        #: Papers are read from under this prefix only. The storage root is
        #: shared with every other module, so scanning it would offer their
        #: data as a paper source.
        self._papers_root = papers_root.strip("/")
        #: Reads collection members: folders, PubMed searches and papers.
        self.collection_sources = collection_sources
        self.resources = AppResources(
            rows,
            self._papers_root,
            collection_sources,
            supported=renderer.handles if renderer is not None else None,
        )
        self.management = PipelineManagement(
            rows,
            object_storage,
            self._papers_root,
            is_model_available,
            paper_collections=self.resources,
        )
        self.papers = PapersCatalog(rows)
        self.versions = PromptVersions(rows)

    def pubmed_queries(self):
        if self._pubmed is None:
            return {"available": False, "queries": []}
        return self._pubmed.queries()

    def pubmed_artifacts(self, query_id):
        return self._pubmed.artifacts(query_id) if self._pubmed else []

    # -- collections ----------------------------------------------------

    def upload_to_collection(
        self, collection_id: str, filename: str, content: bytes
    ) -> dict[str, Any]:
        """Store a PDF in the collection's own folder, which joins it as a member."""
        location = self.resources.upload_folder(collection_id)
        uploaded = self.management.upload(location, filename, content)
        self.resources.add_upload_folder(collection_id)
        return uploaded

    def ingested_papers(
        self, search: str = "", limit: int = 50
    ) -> list[dict[str, Any]]:
        if self.collection_sources is None:
            return []
        return [
            dict(row, discovered_at=_iso(row.get("discovered_at")))
            for row in self.collection_sources.ingested_papers(search, limit)
        ]

    def submit_collection_run(
        self,
        *,
        collection_id: str,
        chunker_id: str,
        prompt_ids: list[str],
        model_id: str,
        requested_by: str | None = None,
    ) -> RunRequest:
        """Queue a run over exactly the papers the collection holds right now.

        The resolved artifacts are written as the request's manifest before the
        request itself, so the orchestrator never sees the request without
        them; ingestion then reads only those artifacts.
        """
        from phases_v2.sources.phases_v2_sources import submit_with_manifest

        inputs = {
            "locations": [],
            "collection_id": collection_id,
            "chunker_id": chunker_id,
            "prompt_ids": prompt_ids,
            "model_id": model_id,
        }
        self.management.validate_inputs(inputs)
        collection = self.resources.collection(collection_id)
        resolution = self.resources.resolve(collection)
        if resolution.failed:
            raise ValueError(
                "Some members of this collection could not be read, so the run "
                "would not cover the whole collection: "
                + "; ".join(resolution.failed.values())
            )
        if not resolution.papers:
            raise ValueError(
                "This collection has no papers yet. Add papers before running it."
            )
        return submit_with_manifest(
            self._rows,
            self._requests,
            contract="CollectionManifest",
            source_id=collection_id,
            artifacts=resolution.manifest(),
            location=f"{COLLECTION_SOURCE}{collection_id}",
            chunker_id=chunker_id,
            prompt_ids=prompt_ids,
            model_id=model_id,
            requested_by=requested_by,
        )

    def submit_pubmed(self, payload):
        if self._pubmed is None or self._rows is None:
            raise ValueError("PubMed publication dataset is unavailable")
        from phases_v2.app.contracts.app_validation import validate_command
        from phases_v2.sources.phases_v2_sources import submit_pubmed

        validate_command("SubmitPubmedRun", payload)
        self.management.validate_choices(payload)
        return submit_pubmed(self._rows, self._requests, self._pubmed, payload)

    # -- what a user chooses from ---------------------------------------

    def prompts(self) -> list[dict[str, Any]]:
        return self.management.prompts()

    def models(self) -> list[dict[str, Any]]:
        """Declared models, each marked with whether it can actually be built."""
        out = []
        for model in DECLARED_MODELS:
            entry = asdict(model)
            entry["available"] = (
                True
                if self._is_model_available is None
                else bool(self._is_model_available(model.model_id))
            )
            out.append(entry)
        return out

    @staticmethod
    def chunkers() -> list[dict[str, Any]]:
        return [
            {
                "chunker_id": chunker.chunker_id,
                "name": chunker.name,
                "version": chunker.version,
                "params": chunker.params,
            }
            for chunker in DECLARED_CHUNKERS
        ]

    def locations(self) -> list[dict[str, str]]:
        """Where papers can be read from: the module's root and its subfolders.

        The root itself is always offered, so dropping PDFs straight into it
        works and so a root that does not exist yet is still visible — with the
        preview saying it is empty rather than the chooser being blank for no
        stated reason.
        """
        root = self._papers_root
        found = [{"prefix": root, "name": f"{root} (all)"}]
        found.extend(self.management.collections())
        if self._storage is None:
            return found

        try:
            keys = self._storage.list_objects(root)
        except Exception:  # noqa: BLE001 - a root that does not exist yet
            return found

        for key in sorted({k.rstrip("/") for k in keys if k}):
            name = key.rsplit("/", 1)[-1]
            if re.fullmatch(r"[a-f0-9]{64}", name):
                continue
            prefix = key if key.startswith(root + "/") else f"{root}/{name}"
            if prefix in {entry["prefix"] for entry in found}:
                continue
            found.append({"prefix": prefix, "name": name})
        return found

    def documents(self, locations: list[str], limit: int = 200) -> dict[str, Any]:
        """What a run over ``locations`` would actually see.

        Uses the recursive listing, so it shows the whole subtree rather than
        the top level — which is what ingestion will walk. Each document is
        marked with whether it has already been ingested, because that is the
        difference between a run that costs something and one that does not.
        """
        if self._storage is None:
            return {
                "documents": [],
                "total": 0,
                "ingestable": 0,
                "unsupported": 0,
                "failed_locations": [],
                "already_ingested": 0,
                "truncated": False,
            }

        known_paths, known_ids = self._ingested_documents()
        seen: set[str] = set()
        found: list[dict[str, Any]] = []
        failed: list[str] = []

        for location in locations:
            try:
                keys = self._storage.list_objects_recursive(location)
            except Exception as unreachable:  # noqa: BLE001
                failed.append(f"{location}: {unreachable}")
                continue
            for key in keys:
                name = key.rsplit("/", 1)[-1]
                full_key = (
                    key if key.startswith(location + "/") else f"{location}/{key}"
                )
                if full_key in seen:
                    continue
                seen.add(full_key)
                parent = full_key.rsplit("/", 2)[-2]
                is_uploaded = re.fullmatch(r"[a-f0-9]{64}", parent) is not None
                ingested = (
                    parent in known_ids if is_uploaded else full_key in known_paths
                )
                found.append(
                    {
                        "location": location,
                        "key": key,
                        "name": name,
                        "already_ingested": ingested,
                        "supported": self._supported(name),
                    }
                )

        found.sort(key=lambda d: (d["location"], d["key"]))
        ingestable = [d for d in found if d["supported"]]
        return {
            "documents": found[:limit],
            "total": len(found),
            "ingestable": len(ingestable),
            "unsupported": len(found) - len(ingestable),
            "already_ingested": sum(1 for d in ingestable if d["already_ingested"]),
            "truncated": len(found) > limit,
            "failed_locations": failed,
        }

    def _supported(self, file_name: str) -> bool:
        if self._renderer is None:
            return True
        return bool(self._renderer.handles(file_name))

    def _ingested_documents(self) -> tuple[set[str], set[str]]:
        if self._rows is None:
            return set(), set()
        rows = self._rows.query(
            "SELECT paper_id, storage_prefix, storage_key FROM papers WHERE text_key IS NOT NULL"
        )
        return (
            {f"{row['storage_prefix']}/{row['storage_key']}" for row in rows},
            {row["paper_id"] for row in rows},
        )

    # -- trying a prompt -------------------------------------------------

    def try_prompt(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Run a draft or saved version on a few chunks. Writes nothing."""
        from phases_v2.app.contracts.pipeline_validation import validate_message
        from phases_v2.playground.adapters.secondary.DatasetPlaygroundStore import (
            DatasetPlaygroundStore,
        )
        from phases_v2.playground.domain import MAX_CHUNKS, TryRefused, try_prompt
        from phases_v2.prompts.domain import CHUNK_PLACEHOLDER, PromptTemplate

        if self._rows is None or self._model_factory is None:
            raise ManagementUnavailable(
                "Trying prompts is unavailable in this deployment."
            )
        # The refusals users meet most, said plainly before the contract's
        # field-by-field wording.
        if ("draft" in payload) == ("prompt_id" in payload):
            raise TryRefused(
                "Try one thing at a time: either a draft or a saved prompt version."
            )
        seqs = payload.get("seqs")
        if isinstance(seqs, list) and len(seqs) > MAX_CHUNKS:
            raise TryRefused(
                f"Try at most {MAX_CHUNKS} chunks at a time; {len(seqs)} were chosen."
            )
        draft = payload.get("draft")
        if isinstance(draft, dict) and CHUNK_PLACEHOLDER not in str(
            draft.get("template", "")
        ):
            raise TryRefused(
                "The prompt text must contain {chunk_text}, where each chunk's "
                "text is placed."
            )
        validate_message("TryPrompt", payload)

        report = try_prompt(
            store=DatasetPlaygroundStore(self._rows),
            model_factory=self._model_factory,
            model_id=payload["model_id"],
            paper_id=payload["paper_id"],
            chunker_id=payload["chunker_id"],
            prompt_id=payload.get("prompt_id"),
            draft=PromptTemplate(**draft) if isinstance(draft, dict) else None,
            seqs=payload.get("seqs") or None,
            first=payload.get("first") or None,
            baseline_prompt_id=payload.get("baseline_prompt_id") or None,
            is_model_available=self._is_model_available,
            timeout_seconds=self._try_timeout_seconds,
        )
        return asdict(report)

    # -- submitting -----------------------------------------------------

    def submit_inputs(self, inputs: dict[str, Any]) -> RunRequest:
        """Queue a run from ``PipelineInputs``: storage folders or a collection."""
        from phases_v2.app.contracts.pipeline_validation import validate_message

        validate_message("PipelineInputs", inputs)
        common = {
            "chunker_id": inputs.get("chunker_id", ""),
            "prompt_ids": inputs.get("prompt_ids", []),
            "model_id": inputs.get("model_id", ""),
            "requested_by": inputs.get("requested_by"),
        }
        if inputs.get("collection_id"):
            if inputs.get("locations"):
                raise ValueError("Choose a collection or storage folders, not both.")
            return self.submit_collection_run(
                collection_id=inputs["collection_id"], **common
            )
        return self.submit_run(locations=inputs.get("locations", []), **common)

    def submit_run(
        self,
        *,
        locations: list[str],
        chunker_id: str,
        prompt_ids: list[str],
        model_id: str,
        requested_by: str | None = None,
    ) -> RunRequest:
        self.management.validate_inputs(
            {
                "locations": locations,
                "chunker_id": chunker_id,
                "prompt_ids": prompt_ids,
                "model_id": model_id,
                "requested_by": requested_by,
            }
        )
        return submit(
            self._requests,
            locations=locations,
            chunker_id=chunker_id,
            prompt_ids=prompt_ids,
            model_id=model_id,
            requested_by=requested_by,
        )

    def recent_requests(self, limit: int = 25) -> list[dict[str, Any]]:
        requests = self._requests.recent(limit)
        names = self._collection_names(requests)
        return [_request_json(request, names) for request in requests]

    def request(self, request_id: str) -> dict[str, Any]:
        request = self._requests.get(request_id)
        data = _request_json(request, self._collection_names([request]))
        data["counts"] = self._counts_for(request)
        return data

    def _collection_names(self, requests: list[RunRequest]) -> dict[str, dict]:
        """The collections these requests ran on, archived ones included."""
        if not any(_collection_of(r) for r in requests):
            return {}
        return {
            c["collection_id"]: {
                "collection_id": c["collection_id"],
                "name": c["name"],
                "archived": c["archived"],
            }
            for c in self.resources.collections(include_archived=True)
        }

    def _counts_for(self, request: RunRequest) -> dict[str, int] | None:
        """What the run actually did, summed across its prompts.

        One request produces one extraction run per prompt, each recorded under
        a run id derived from the request. Computing those ids here makes the
        lookup exact rather than a pattern match over run ids.
        """
        if self._rows is None:
            return None
        from phases_v2.orchestrations.PhasesV2Orchestration import extraction_run_id
        from phases_v2.sql import in_list

        run_ids = [
            extraction_run_id(request.request_id, prompt_id)
            for prompt_id in request.prompt_ids
        ]
        if not run_ids:
            return None
        rows = self._rows.query(
            "SELECT succeeded, failed, skipped FROM extraction_runs "  # nosec B608
            f"WHERE run_id IN {in_list(run_ids)}"
        )
        if not rows:
            return None
        return {
            "succeeded": sum(row["succeeded"] or 0 for row in rows),
            "failed": sum(row["failed"] or 0 for row in rows),
            "skipped": sum(row["skipped"] or 0 for row in rows),
            "prompts_run": len(rows),
        }

    def chunker_warning(self, chunker_id: str) -> str | None:
        """Warn when picking a chunker the corpus was not last cut with.

        A different mechanism means new chunk ids, so every extraction over the
        corpus becomes outstanding again — correct, but expensive, and not
        obvious from a dropdown.
        """
        if self._rows is None or not chunker_id:
            return None
        rows = self._rows.query("SELECT DISTINCT chunker_id FROM chunks")
        existing = {row["chunker_id"] for row in rows if row["chunker_id"]}
        if not existing or chunker_id in existing:
            return None
        return (
            "The corpus is currently chunked with "
            f"{', '.join(sorted(existing))}. Running with {chunker_id} will "
            "chunk the selected documents and may require new extractions."
        )


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _collection_of(request: RunRequest) -> str | None:
    for location in request.locations:
        if location.startswith(COLLECTION_SOURCE):
            return location[len(COLLECTION_SOURCE) :]
    return None


def _request_json(
    request: RunRequest, collections: dict[str, dict] | None = None
) -> dict[str, Any]:
    data = asdict(request)
    for field in ("requested_at", "started_at", "finished_at"):
        data[field] = _iso(data.get(field))
    collection_id = _collection_of(request)
    if collection_id:
        data["collection"] = (collections or {}).get(collection_id) or {
            "collection_id": collection_id,
            "name": None,
            "archived": None,
        }
    return data
