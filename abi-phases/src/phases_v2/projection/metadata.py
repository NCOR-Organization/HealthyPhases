"""Versioned search attributes stored alongside extracted-item vectors."""

METADATA_VERSION = 1


def search_metadata(item, extraction, paper, prompt):
    prefix = (paper.get("storage_prefix") or "").strip("/")
    directory = (paper.get("storage_key") or "").strip("/").rpartition("/")[0]
    folder = "/".join(part for part in (prefix, directory) if part)
    return {
        "search_metadata_version": METADATA_VERSION,
        "item_id": item["item_id"],
        "document_id": item["item_id"],
        "extraction_id": item["extraction_id"],
        "chunk_id": item["chunk_id"],
        "paper_id": item["paper_id"],
        "prompt_id": item["prompt_id"],
        "prompt_name": prompt.get("name"),
        "model_id": extraction.get("model_id"),
        "source_path": folder or None,
        "source_ancestors": [
            "/".join(folder.split("/")[:n])
            for n in range(1, len(folder.split("/")) + 1)
        ]
        if folder
        else [],
        "seq": item.get("seq"),
    }
