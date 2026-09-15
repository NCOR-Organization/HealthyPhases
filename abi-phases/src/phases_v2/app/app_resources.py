"""Resource management using the pipeline's existing row-store port."""

import json
import uuid
from typing import Any

from phases_v2.app.contracts.app_validation import validate_command
from phases_v2.ports import RowStore
from phases_v2.prompts.domain import PromptTemplate, register_prompts
from phases_v2.prompts.templates import declared_prompts


class ResourceNotFound(LookupError):
    pass


class AppResources:
    def __init__(self, rows: RowStore | None, papers_root: str):
        self._rows = rows
        self._root = papers_root.strip("/")

    def _writable(self):
        if self._rows is None:
            raise ValueError("Resource storage is unavailable in this deployment.")

    def collections(self) -> list[dict[str, Any]]:
        if self._rows is None:
            return []
        entries = self._rows.query("SELECT * FROM input_collections")
        return sorted(
            [
                dict(
                    row,
                    locations=json.loads(row["locations"])
                    if isinstance(row["locations"], str)
                    else row["locations"],
                )
                for row in entries
                if not row["archived"]
            ],
            key=lambda row: row["name"].casefold(),
        )

    def collection(self, collection_id: str) -> dict[str, Any]:
        for row in self.collections():
            if row["collection_id"] == collection_id:
                return row
        raise ResourceNotFound("Collection not found.")

    def save_collection(
        self, payload: dict[str, Any], collection_id: str | None = None
    ) -> dict[str, Any]:
        self._writable()
        command = validate_command("SaveCollection", payload)
        if collection_id is not None:
            self.collection(collection_id)
        locations = list(
            dict.fromkeys(loc.strip().rstrip("/") for loc in command.locations)
        )
        for location in locations:
            if (
                not (location == self._root or location.startswith(self._root + "/"))
                or any(part in (".", "..", "") for part in location.split("/"))
                or "\\" in location
            ):
                raise ValueError(f"Locations must be inside {self._root}.")
        row = {
            "collection_id": collection_id or str(uuid.uuid4()),
            "name": command.name.strip(),
            "locations": locations,
            "archived": False,
        }
        self._rows.write_rows("input_collections", [row])
        return row

    def archive_collection(self, collection_id: str) -> None:
        self._writable()
        row = self.collection(collection_id)
        self._rows.write_rows("input_collections", [dict(row, archived=True)])

    def prompts(self) -> list[dict[str, Any]]:
        entries = {
            p.prompt_id: {
                "prompt_id": p.prompt_id,
                "name": p.name,
                "template": p.template,
                "output_key": p.output_key,
            }
            for p in declared_prompts()
        }
        if self._rows is not None:
            for row in self._rows.query(
                "SELECT prompt_id, name, template, output_key FROM prompts"
            ):
                entries[row["prompt_id"]] = row
        return sorted(entries.values(), key=lambda row: (row["name"], row["prompt_id"]))

    def save_prompt(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._writable()
        command = validate_command("SavePrompt", payload)
        if command.output_key not in {p.output_key for p in declared_prompts()}:
            raise ValueError("Choose an output schema supported by this pipeline.")
        template = PromptTemplate(
            command.name.strip(), command.template, command.output_key
        )
        for existing in self.prompts():
            if (
                existing["prompt_id"] == template.prompt_id
                and existing["output_key"] != template.output_key
            ):
                raise ValueError(
                    "Change the prompt name or text when changing its output schema."
                )
        register_prompts(self._rows, [template])
        return {
            "prompt_id": template.prompt_id,
            "name": template.name,
            "template": template.template,
            "output_key": template.output_key,
        }
