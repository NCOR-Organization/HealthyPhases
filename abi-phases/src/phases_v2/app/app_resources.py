"""Resource management using the pipeline's existing row-store port."""

import json
import uuid
from typing import Any

from phases_v2.app.contracts.app_validation import validate_command
from phases_v2.app.pipeline_management import ManagementUnavailable
from phases_v2.ports import RowStore


class ResourceNotFound(KeyError):
    pass


class AppResources:
    def __init__(self, rows: RowStore | None, papers_root: str):
        self._rows = rows
        self._root = papers_root.strip("/")

    def _writable(self):
        if self._rows is None:
            raise ManagementUnavailable(
                "Resource storage is unavailable in this deployment."
            )

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
                or any(ord(c) < 32 for c in location)
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
