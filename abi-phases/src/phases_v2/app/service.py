"""What the app needs, assembled from the module's domains.

Kept separate from the HTTP adapter so the app's behaviour can be tested
without a web server, and so the endpoints stay a thin translation layer.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any

from phases_v2.chunking.chunkers import DECLARED_CHUNKERS
from phases_v2.models.catalog import DECLARED_MODELS
from phases_v2.prompts.templates import declared_prompts
from phases_v2.requests.domain import submit
from phases_v2.requests.interfaces import RunRequest


class PipelineAppService:
    def __init__(
        self,
        request_store,
        object_storage=None,
        rows=None,
        is_model_available=None,
        renderer=None,
        papers_root: str = "phases_v2",
    ):
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

    # -- what a user chooses from ---------------------------------------

    @staticmethod
    def prompts() -> list[dict[str, Any]]:
        return [
            {
                "prompt_id": template.prompt_id,
                "name": template.name,
                "output_key": template.output_key,
            }
            for template in declared_prompts()
        ]

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
        if self._storage is None:
            return found

        try:
            keys = self._storage.list_objects(root)
        except Exception:  # noqa: BLE001 - a root that does not exist yet
            return found

        for key in sorted({k.rstrip("/") for k in keys if k}):
            name = key.rsplit("/", 1)[-1]
            prefix = key if key.startswith(root + "/") else f"{root}/{name}"
            if prefix == root:
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
            return {"documents": [], "total": 0, "already_ingested": 0, "truncated": False}

        known = self._ingested_names()
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
                found.append(
                    {
                        "location": location,
                        "key": key,
                        "name": name,
                        "already_ingested": name in known,
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

    def _ingested_names(self) -> set[str]:
        if self._rows is None:
            return set()
        try:
            return {
                row["file_name"]
                for row in self._rows.query("SELECT file_name FROM papers")
                if row.get("file_name")
            }
        except Exception:  # noqa: BLE001 - a preview must not fail the page
            return set()

    # -- submitting -----------------------------------------------------

    def submit_run(
        self,
        *,
        locations: list[str],
        chunker_id: str,
        prompt_ids: list[str],
        model_id: str,
        requested_by: str | None = None,
    ) -> RunRequest:
        return submit(
            self._requests,
            locations=locations,
            chunker_id=chunker_id,
            prompt_ids=prompt_ids,
            model_id=model_id,
            requested_by=requested_by,
        )

    def recent_requests(self, limit: int = 25) -> list[dict[str, Any]]:
        return [_request_json(request) for request in self._requests.recent(limit)]

    def request(self, request_id: str) -> dict[str, Any]:
        request = self._requests.get(request_id)
        data = _request_json(request)
        data["counts"] = self._counts_for(request)
        return data

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
            "re-chunk it and make every extraction outstanding again."
        )


def _request_json(request: RunRequest) -> dict[str, Any]:
    data = asdict(request)
    for field in ("requested_at", "started_at", "finished_at"):
        value = data.get(field)
        if isinstance(value, datetime):
            data[field] = value.isoformat()
    return data
