from openalex.domain.openalex_errors import AlreadyClaimed


def owned(current, owner):
    if (
        current["status"] != "running"
        or current["generation"] != owner["generation"]
        or current["run_id"] != owner["run_id"]
    ):
        raise AlreadyClaimed(owner["request_id"])
    return current
