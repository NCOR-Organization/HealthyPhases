"""Refresh vector annotations without recalculating embeddings."""

from phases_v2.projection.metadata import search_metadata


def refresh_metadata(reader, sink) -> int:
    papers = {p["paper_id"]: p for p in reader.papers()}
    prompts = {p["prompt_id"]: p for p in reader.prompts()}
    extractions = {e["extraction_id"]: e for e in reader.succeeded_extractions()}
    metadata = {
        item["item_id"]: search_metadata(
            item,
            extractions[item["extraction_id"]],
            papers.get(item["paper_id"], {}),
            prompts.get(item["prompt_id"], {}),
        )
        for item in reader.items_for(list(extractions))
    }
    return sink.refresh(metadata)
