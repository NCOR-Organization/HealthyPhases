"""Read legacy structured item text without changing the stored extraction."""

import ast
import json


def canonical_payload_text(text: str) -> str:
    """Expose old ``str(dict)``/``str(list)`` items as JSON for result renderers."""
    # Bound parsing work and leave ordinary claims untouched.
    if len(text) > 65536 or not text.lstrip().startswith(("{", "[")):
        return text
    try:
        json.loads(text)
        return text
    except (ValueError, RecursionError):
        pass
    try:
        payload = ast.literal_eval(text)
        if isinstance(payload, (dict, list)):
            return json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except (SyntaxError, ValueError, TypeError, RecursionError):
        pass
    return text
