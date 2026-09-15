"""Persist exact artifact selections before making a manual request visible."""

from uuid import uuid4

from google.protobuf.json_format import MessageToDict

from phases_v2.app.contracts.app_validation import validate_command
from phases_v2.requests.domain import submit
from phases_v2.sql import literal


def submit_pubmed(rows, requests, catalog, payload):
    command = validate_command("SubmitPubmedRun", payload)
    artifacts = catalog.artifacts(command.query_id)
    if not artifacts:
        raise ValueError("This query has no published PDF artifacts")
    request_id = str(uuid4())
    manifest = validate_command(
        "SourceManifest",
        {
            "request_id": request_id,
            "source_query_id": command.query_id,
            "artifacts": [
                {
                    key: a[key]
                    for key in (
                        "artifact_id",
                        "storage_prefix",
                        "storage_key",
                        "content_sha256",
                    )
                }
                for a in artifacts
            ],
        },
    )
    rows.write_rows(
        "source_manifests", [MessageToDict(manifest, preserving_proto_field_name=True)]
    )
    return submit(
        requests,
        request_id=request_id,
        locations=[f"dataset:pubmed:{command.query_id}"],
        chunker_id=command.chunker_id,
        prompt_ids=list(command.prompt_ids),
        model_id=command.model_id,
    )


def manifest_for(rows, request_id):
    records = rows.query(
        f"SELECT * FROM source_manifests WHERE request_id = {literal(request_id)}"
    )
    return records[0]["artifacts"] if records else None
