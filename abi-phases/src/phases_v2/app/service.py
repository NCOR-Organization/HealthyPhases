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
    def __init__(self, request_store, object_storage=None, rows=None):
        self._requests = request_store
        self._storage = object_storage
        self._rows = rows

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

    @staticmethod
    def models() -> list[dict[str, Any]]:
        return [asdict(model) for model in DECLARED_MODELS]

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

    def locations(self, prefix: str = "") -> list[str]:
        """Storage locations a user can pick as a source of papers."""
        if self._storage is None:
            return []
        try:
            keys = self._storage.list_objects(prefix)
        except Exception:  # noqa: BLE001 - a missing prefix is an empty listing here
            return []
        return sorted({key.rstrip("/") for key in keys if key})

    # -- submitting -----------------------------------------------------

    def submit_run(
        self,
        *,
        locations: list[str],
        chunker_id: str,
        prompt_id: str,
        model_id: str,
        requested_by: str | None = None,
    ) -> RunRequest:
        return submit(
            self._requests,
            locations=locations,
            chunker_id=chunker_id,
            prompt_id=prompt_id,
            model_id=model_id,
            requested_by=requested_by,
        )

    def recent_requests(self, limit: int = 25) -> list[dict[str, Any]]:
        return [_request_json(request) for request in self._requests.recent(limit)]

    def request(self, request_id: str) -> dict[str, Any]:
        data = _request_json(self._requests.get(request_id))
        data["counts"] = self._counts_for(request_id)
        return data

    def _counts_for(self, request_id: str) -> dict[str, int] | None:
        """What the run actually did, from ``extraction_runs``.

        The extraction run is recorded under the request id, so this is an
        exact lookup rather than a guess at which run belonged to whom.
        """
        if self._rows is None:
            return None
        from phases_v2.sql import literal

        rows = self._rows.query(
            "SELECT succeeded, failed, skipped FROM extraction_runs "  # nosec B608
            f"WHERE run_id = {literal(request_id)}"
        )
        if not rows:
            return None
        return {
            "succeeded": rows[0]["succeeded"],
            "failed": rows[0]["failed"],
            "skipped": rows[0]["skipped"],
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
