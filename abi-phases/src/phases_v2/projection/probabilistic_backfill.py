"""Run via `uv run abi run script src/phases_v2/projection/probabilistic_backfill.py`.

`--dry-run` reports without writing. `--rebuild` recreates the dataset and
derives every relation again, for a change to the row shape.
"""

import json
import sys
from dataclasses import asdict

from phases_v2 import ABIModule
from phases_v2.projection.factory import project_to_relations, rebuild_relations

if __name__ == "__main__":
    if {"--rebuild", "--dry-run"} <= set(sys.argv):
        sys.exit("--rebuild drops the dataset, so it cannot be a dry run.")
    engine = ABIModule.get_instance().engine
    report = (
        rebuild_relations(engine)
        if "--rebuild" in sys.argv
        else project_to_relations(engine, dry_run="--dry-run" in sys.argv)
    )
    print(json.dumps(asdict(report), default=str), flush=True)
