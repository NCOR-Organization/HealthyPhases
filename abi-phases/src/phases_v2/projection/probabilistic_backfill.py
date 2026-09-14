"""Run via `uv run abi run script src/phases_v2/projection/probabilistic_backfill.py`."""

import json
import sys
from dataclasses import asdict

from phases_v2 import ABIModule
from phases_v2.projection.factory import project_to_relations

if __name__ == "__main__":
    report = project_to_relations(
        ABIModule.get_instance().engine, dry_run="--dry-run" in sys.argv
    )
    print(json.dumps(asdict(report), default=str), flush=True)
