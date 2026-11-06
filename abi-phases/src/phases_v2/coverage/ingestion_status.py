"""Has every paper we hold run through every prompt, with this model?

Reads only: no dataset write, no projection, no run request. Every number is
read at one dataset snapshot. Run on the deployment with::

    uv run abi run script src/phases_v2/coverage/ingestion_status.py -- \\
        [--model openai/gpt-4.1-mini ...] [--prompt-id ID ...] [--chunker-id ID] \\
        [--json] [--strict]

Starting the engine publishes the module's declarations, as every engine start
does. To read without starting it, load only the dataset and object storage
services from the configuration::

    uv run python -m phases_v2.coverage.ingestion_status [same flags]

Exit codes: 0 when the report was produced (and, with ``--strict``, nothing is
outstanding), 1 when ``--strict`` found something outstanding, 2 for a bad flag.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, TextIO

from phases_v2.coverage.domain import UnknownPrompt, render_text, to_dict
from phases_v2.coverage.interfaces import DEFAULT_MODEL


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ingestion_status",
        description="Report ingestion coverage per source, prompt version and model.",
    )
    parser.add_argument(
        "--model",
        action="append",
        default=[],
        help=f"model id to check; repeatable (default {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--prompt-id",
        action="append",
        default=[],
        help="prompt version to check; repeatable, replaces the default of the "
        "current version of every declared prompt",
    )
    parser.add_argument(
        "--chunker-id",
        default=None,
        help="chunker to check (default: the declared one)",
    )
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 when PDFs are not ingested or chunked, chunks are not run, "
        "calls failed or projections are behind",
    )
    # `abi run script path -- --flag` may hand the separator on.
    return parser.parse_args([a for a in argv if a != "--"])


def main(
    argv: list[str],
    *,
    dataset: Any,
    object_storage: Any,
    out: TextIO = sys.stdout,
    err: TextIO = sys.stderr,
) -> int:
    from phases_v2.coverage.factory import coverage_report, selection

    args = parse(argv)
    chosen = selection(args.model, args.prompt_id, args.chunker_id)
    try:
        report = coverage_report(dataset, object_storage, chosen)
    except UnknownPrompt as unknown:
        print(f"ingestion_status: {unknown}", file=err)
        return 2
    if args.json:
        print(json.dumps(to_dict(report), indent=2, default=str), file=out)
    else:
        print(render_text(report), end="", file=out)
    out.flush()
    return 1 if args.strict and report.problems() else 0


def _services() -> tuple[Any, Any]:
    """The engine's services when ``abi run script`` started it; otherwise only
    the two this report reads, loaded from the configuration."""
    from phases_v2 import ABIModule

    try:
        services = ABIModule.get_instance().engine.services
        return services.dataset, services.object_storage
    except ValueError:
        pass
    from naas_abi_core.engine.engine_configuration.EngineConfiguration import (
        EngineConfiguration,
    )
    from naas_abi_core.utils.Logger import reconfigure

    # Loading the configuration logs it, rendered with its secrets, at DEBUG.
    reconfigure("WARNING")
    configuration = EngineConfiguration.load_configuration()
    return (
        configuration.services.dataset.load(),
        configuration.services.object_storage.load(),
    )


if __name__ == "__main__":
    dataset, object_storage = _services()
    sys.exit(main(sys.argv[1:], dataset=dataset, object_storage=object_storage))
