"""Every version of a prompt name, and what each one has been used for.

A version is one template text under a name (``prompt_id`` hashes both), so
this lists them side by side with the runs and requests that used each and how
many items each produced. Read-only.
"""

from __future__ import annotations

import json
from typing import Any

from phases_v2.app.app_resources import ResourceNotFound
from phases_v2.ports import RowStore
from phases_v2.prompts.templates import declared_prompts
from phases_v2.sql import in_list, literal

#: Runs and requests listed per version; the counts always cover all of them.
LISTED = 20


class PromptVersions:
    def __init__(self, rows: RowStore | None):
        self._rows = rows

    def versions(self, name: str) -> dict[str, Any]:
        versions = self._versions(name)
        if not versions:
            raise ResourceNotFound(f"No prompt is named {name!r}.")
        ids = list(versions)
        for prompt_id, runs in self._runs(ids).items():
            versions[prompt_id]["runs"] = runs[:LISTED]
            versions[prompt_id]["run_count"] = len(runs)
        for prompt_id, requests in self._requests(ids).items():
            versions[prompt_id]["requests"] = requests[:LISTED]
            versions[prompt_id]["request_count"] = len(requests)
        for prompt_id, usage in self._usage(ids).items():
            versions[prompt_id].update(usage)
        ordered = sorted(
            versions.values(),
            key=lambda v: (v["registered_at"] or "", v["prompt_id"]),
            reverse=True,
        )
        return {"name": name, "versions": ordered}

    def _versions(self, name: str) -> dict[str, dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        declared = {p.prompt_id for p in declared_prompts()}
        for prompt in declared_prompts():
            if prompt.name == name:
                found[prompt.prompt_id] = _version(
                    prompt.prompt_id, name, prompt.template, prompt.output_key, None
                )
        if self._rows is not None:
            for row in self._rows.query(
                "SELECT prompt_id, template, output_key, registered_at FROM prompts "  # nosec B608
                f"WHERE name = {literal(name)}"
            ):
                found[row["prompt_id"]] = _version(
                    row["prompt_id"],
                    name,
                    row["template"],
                    row["output_key"],
                    _iso(row["registered_at"]),
                )
        for prompt_id, version in found.items():
            version["declared"] = prompt_id in declared
        return found

    def _runs(self, ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        if self._rows is None:
            return {}
        runs: dict[str, list[dict[str, Any]]] = {}
        for row in self._rows.query(
            "SELECT run_id, prompt_id, model_id, chunker_id, started_at, "  # nosec B608
            "finished_at, succeeded, failed, skipped FROM extraction_runs "
            f"WHERE prompt_id IN {in_list(ids)} ORDER BY started_at DESC"
        ):
            run = {key: _iso(value) for key, value in row.items()}
            # Runs queued from the app are recorded as "<request_id>:<prompt_id>".
            suffix = f":{row['prompt_id']}"
            run["request_id"] = (
                row["run_id"][: -len(suffix)]
                if row["run_id"].endswith(suffix)
                else None
            )
            runs.setdefault(row["prompt_id"], []).append(run)
        return runs

    def _requests(self, ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        if self._rows is None:
            return {}
        wanted = set(ids)
        requests: dict[str, list[dict[str, Any]]] = {}
        # Prompt ids are a JSON list per request; requests are few, so the
        # match is made here rather than with dialect-specific JSON SQL.
        for row in self._rows.query(
            "SELECT request_id, status, prompt_ids, model_id, chunker_id, "
            "requested_by, requested_at FROM run_requests ORDER BY requested_at DESC"
        ):
            prompt_ids = row["prompt_ids"]
            if isinstance(prompt_ids, str):
                prompt_ids = json.loads(prompt_ids)
            for prompt_id in wanted.intersection(prompt_ids or []):
                requests.setdefault(prompt_id, []).append(
                    {
                        "request_id": row["request_id"],
                        "status": row["status"],
                        "model_id": row["model_id"],
                        "chunker_id": row["chunker_id"],
                        "requested_by": row["requested_by"],
                        "requested_at": _iso(row["requested_at"]),
                    }
                )
        return requests

    def _usage(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        if self._rows is None:
            return {}
        usage: dict[str, dict[str, Any]] = {}
        for row in self._rows.query(
            "SELECT prompt_id, model_id, status, count(*) AS chunks, "  # nosec B608
            "sum(item_count) AS items FROM extractions "
            f"WHERE prompt_id IN {in_list(ids)} GROUP BY prompt_id, model_id, status"
        ):
            entry = usage.setdefault(
                row["prompt_id"], {"item_count": 0, "chunk_count": 0, "by_model": {}}
            )
            model = entry["by_model"].setdefault(
                row["model_id"], {"items": 0, "succeeded": 0, "failed": 0}
            )
            chunks = int(row["chunks"] or 0)
            if row["status"] == "succeeded":
                items = int(row["items"] or 0)
                entry["item_count"] += items
                entry["chunk_count"] += chunks
                model["items"] += items
                model["succeeded"] += chunks
            else:
                model["failed"] += chunks
        return usage


def _version(
    prompt_id: str, name: str, template: str, output_key: str, registered_at: Any
) -> dict[str, Any]:
    return {
        "prompt_id": prompt_id,
        "name": name,
        "template": template,
        "output_key": output_key,
        "registered_at": registered_at,
        "declared": False,
        "runs": [],
        "run_count": 0,
        "requests": [],
        "request_count": 0,
        "item_count": 0,
        "chunk_count": 0,
        "by_model": {},
    }


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value
