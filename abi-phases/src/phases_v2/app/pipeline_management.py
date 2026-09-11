"""Pipeline authoring use cases over the existing row and object stores."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime

from phases_v2.app.contracts.pipeline_validation import validate_message
from phases_v2.chunking.chunkers import DECLARED_CHUNKERS
from phases_v2.identity import paper_id
from phases_v2.models.catalog import DECLARED_MODELS
from phases_v2.papers.interfaces import ObjectSource
from phases_v2.ports import RowStore
from phases_v2.prompts.domain import PromptTemplate, register_prompts
from phases_v2.prompts.templates import declared_prompts
from phases_v2.sql import literal

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class ManagementUnavailable(RuntimeError):
    pass


def prompt_catalog(rows: RowStore | None = None) -> list[dict]:
    catalog = {
        p.prompt_id: {
            "prompt_id": p.prompt_id,
            "name": p.name,
            "template": p.template,
            "output_key": p.output_key,
        }
        for p in declared_prompts()
    }
    if rows is not None:
        for row in rows.query(
            "SELECT prompt_id, name, template, output_key FROM prompts"
        ):
            catalog[row["prompt_id"]] = row
    return sorted(catalog.values(), key=lambda p: (p["name"], p["prompt_id"]))


class PipelineManagement:
    def __init__(
        self,
        rows: RowStore | None,
        storage: ObjectSource | None,
        papers_root: str,
        is_model_available: Callable[[str], bool] | None = None,
    ):
        self.rows = rows
        self.storage = storage
        self.root = papers_root
        self.is_model_available = is_model_available

    def _rows(self) -> RowStore:
        if self.rows is None:
            raise ManagementUnavailable("The dataset service is unavailable.")
        return self.rows

    def location(self, value: str) -> str:
        if (
            not value
            or "\\" in value
            or any(ord(c) < 32 for c in value)
            or any(p in ("", ".", "..") for p in value.split("/"))
            or not (value == self.root or value.startswith(self.root + "/"))
        ):
            raise ValueError("locations must be beneath the module's papers root")
        return value

    def prompts(self) -> list[dict]:
        return prompt_catalog(self.rows)

    def save_prompt(self, payload: dict) -> dict:
        validate_message("SavePrompt", payload)
        prompt = PromptTemplate(**payload)
        existing = next(
            (p for p in self.prompts() if p["prompt_id"] == prompt.prompt_id), None
        )
        if existing:
            if existing["output_key"] != prompt.output_key:
                raise ValueError(
                    "Changing output format requires a new name or template text."
                )
            return existing
        register_prompts(self._rows(), [prompt])
        return {"prompt_id": prompt.prompt_id, **payload}

    def collections(self) -> list[dict]:
        if self.rows is None:
            return []
        return [
            row
            for row in self.rows.query("SELECT prefix, name FROM input_locations")
            if row["prefix"].startswith(self.root + "/")
        ]

    def create_location(self, payload: dict) -> dict:
        validate_message("CreateLocation", payload)
        prefix = self.location(f"{self.root}/{payload['name']}")
        self._rows().write_rows(
            "input_locations",
            [
                {
                    "prefix": prefix,
                    "name": payload["name"],
                    "created_at": datetime.now(UTC),
                }
            ],
        )
        return {"prefix": prefix, "name": payload["name"]}

    def upload(self, location: str, filename: str, content: bytes) -> dict:
        validate_message("UploadDocument", {"location": location, "filename": filename})
        self.location(location)
        if (
            "/" in filename
            or "\\" in filename
            or any(ord(c) < 32 for c in filename)
            or filename.startswith(".")
            or not filename.lower().endswith(".pdf")
        ):
            raise ValueError("Use a PDF filename without directory separators.")
        if not content or len(content) > MAX_UPLOAD_BYTES:
            raise ValueError("PDFs must be between 1 byte and 25 MiB.")
        if not content.startswith(b"%PDF-"):
            raise ValueError("The file does not have a PDF header.")
        if self.storage is None:
            raise ManagementUnavailable("The object storage service is unavailable.")
        # Content-addressed keys make retries idempotent and preserve different
        # documents sharing a filename, including concurrent uploads.
        key = f"{paper_id(content)}/{filename}"
        self.storage.put_object(location, key, content)
        return {
            "location": location,
            "key": f"{location}/{key}",
            "name": filename,
            "size_bytes": len(content),
        }

    def validate_inputs(self, inputs: dict) -> dict:
        validate_message("PipelineInputs", inputs)
        for location in inputs["locations"]:
            self.location(location)
        if inputs["chunker_id"] not in {c.chunker_id for c in DECLARED_CHUNKERS}:
            raise ValueError("Unknown chunker_id")
        if inputs["model_id"] not in {m.model_id for m in DECLARED_MODELS}:
            raise ValueError("Unknown model_id")
        if self.is_model_available and not self.is_model_available(inputs["model_id"]):
            raise ValueError("The selected model_id is unavailable on this deployment")
        known = {p["prompt_id"] for p in self.prompts()}
        if set(inputs["prompt_ids"]) - known:
            raise ValueError("Unknown prompt_ids; reload the prompt catalog")
        return inputs

    def pipelines(self) -> list[dict]:
        return self._rows().query(
            "SELECT pipeline_id, name, inputs, created_at FROM pipelines ORDER BY created_at DESC"
        )

    def save_pipeline(self, payload: dict) -> dict:
        validate_message("SavePipeline", payload)
        self.validate_inputs(payload["inputs"])
        row = {
            "pipeline_id": str(uuid.uuid4()),
            **payload,
            "created_at": datetime.now(UTC),
        }
        self._rows().write_rows("pipelines", [row])
        return row

    def pipeline(self, pipeline_id: str) -> dict:
        rows = self._rows().query(
            f"SELECT pipeline_id, name, inputs, created_at FROM pipelines WHERE pipeline_id = {literal(pipeline_id)}"
        )
        if not rows:
            raise KeyError("Saved pipeline not found")
        return rows[0]
