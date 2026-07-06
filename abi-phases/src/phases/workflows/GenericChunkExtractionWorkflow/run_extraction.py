"""Click CLI runner for GenericChunkExtractionWorkflow.

Provides named pipelines so you don't have to remember prompt files / keys.

Examples
--------
List available pipelines:
    uv run abi run script abi_phases/phases/workflows/GenericChunkExtractionWorkflow/run_extraction.py list

Dry run a single pipeline (first chunk only):
    uv run abi run script abi_phases/phases/workflows/GenericChunkExtractionWorkflow/run_extraction.py run causes --dry-run

Run one pipeline, write JSON output:
    uv run abi run script abi_phases/phases/workflows/GenericChunkExtractionWorkflow/run_extraction.py run causes \
        --chunk-limit 20 --output ./out/causes.json

Run ALL solitude pipelines sequentially, one JSON file per pipeline in ./out/:
    uv run abi run script abi_phases/phases/workflows/GenericChunkExtractionWorkflow/run_extraction.py run-all \
        --chunk-limit 20 --output-dir ./out
"""

from __future__ import annotations

from pathlib import Path

import click

from phases.workflows.GenericChunkExtractionWorkflow.GenericChunkExtractionWorkflow import (
    GenericChunkExtractionWorkflow,
    GenericChunkExtractionWorkflowConfiguration,
    GenericChunkExtractionWorkflowParameters,
)

PROMPTS_DIR = Path(__file__).parent / "prompts"

# Registry of named pipelines: name -> (prompt filename, JSON output key, description)
PIPELINES: dict[str, tuple[str, str, str]] = {
    "what":    ("solitude_what.txt",    "what",    "What solitude is (definition, nature, characteristics)"),
    "causes":  ("solitude_causes.txt",  "causes",  "What leads to solitude (antecedents, triggers)"),
    "how":     ("solitude_how.txt",     "how",     "How solitude happens (mechanism, manner)"),
    "when":    ("solitude_when.txt",    "when",    "When solitude happens (temporal context)"),
    "where":   ("solitude_where.txt",   "where",   "Where solitude happens (spatial context)"),
    "effects": ("solitude_effects.txt", "effects", "Effects and purpose of solitude"),
    "logical_sentences": (
        "logical_sentences.txt",
        "logical_sentences",
        "Generic logical/axiom-style claims (if X then Y) the paper is asserting",
    ),
}


def _run_one(
    pipeline: str,
    *,
    paths: list[str] | None,
    chunk_limit: int | None,
    workers: int | None,
    model: str,
    output_path: str | None,
    dry_run: bool,
) -> dict[str, list[str]]:
    if pipeline not in PIPELINES:
        raise click.BadParameter(
            f"Unknown pipeline '{pipeline}'. Available: {', '.join(PIPELINES)}"
        )
    prompt_file, output_key, _desc = PIPELINES[pipeline]
    prompt_template = (PROMPTS_DIR / prompt_file).read_text()

    workflow = GenericChunkExtractionWorkflow(
        GenericChunkExtractionWorkflowConfiguration(
            prompt_template=prompt_template,
            output_key=output_key,
            model_name=model,
            pipeline_name=pipeline,
        )
    )
    return workflow.run(
        GenericChunkExtractionWorkflowParameters(
            paths=paths or None,
            chunk_limit=chunk_limit,
            workers=workers,
            output_path=output_path,
            dry_run=dry_run,
        )
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group()
def cli() -> None:
    """Run named LLM extraction pipelines over document chunks."""


@cli.command("list")
def list_cmd() -> None:
    """List available pipelines."""
    click.echo("Available pipelines:\n")
    for name, (prompt_file, key, desc) in PIPELINES.items():
        click.echo(f"  {name:8s}  ({key:8s})  {desc}")
        click.echo(f"  {'':8s}  prompt: prompts/{prompt_file}\n")


# Shared options ------------------------------------------------------------

def _common_options(func):
    func = click.option(
        "--path",
        "paths",
        multiple=True,
        help="Restrict to chunks from this paper path (repeatable).",
    )(func)
    func = click.option(
        "--chunk-limit",
        type=int,
        default=None,
        help="Max number of chunks to process.",
    )(func)
    func = click.option(
        "--workers",
        type=int,
        default=None,
        help="Parallel LLM workers.",
    )(func)
    func = click.option(
        "--model",
        type=str,
        default="gpt-5-mini",
        show_default=True,
        help="LLM model name.",
    )(func)
    func = click.option(
        "--dry-run",
        is_flag=True,
        default=False,
        help="Process only the first chunk, print result, do not write output.",
    )(func)
    return func


@cli.command("run")
@click.argument("pipeline", type=click.Choice(list(PIPELINES.keys())))
@click.option(
    "--output",
    type=click.Path(dir_okay=False),
    default=None,
    help="Write {chunk_id: [items]} JSON to this path.",
)
@_common_options
def run_cmd(
    pipeline: str,
    output: str | None,
    paths: tuple[str, ...],
    chunk_limit: int | None,
    workers: int | None,
    model: str,
    dry_run: bool,
) -> None:
    """Run a single named pipeline."""
    results = _run_one(
        pipeline,
        paths=list(paths),
        chunk_limit=chunk_limit,
        workers=workers,
        model=model,
        output_path=output,
        dry_run=dry_run,
    )
    click.echo(
        f"[{pipeline}] processed {len(results)} chunks"
        + (f" -> {output}" if output else "")
    )


@cli.command("run-all")
@click.option(
    "--output-dir",
    type=click.Path(file_okay=False),
    default="./out",
    show_default=True,
    help="Directory to write one JSON file per pipeline.",
)
@_common_options
def run_all_cmd(
    output_dir: str,
    paths: tuple[str, ...],
    chunk_limit: int | None,
    workers: int | None,
    model: str,
    dry_run: bool,
) -> None:
    """Run every pipeline sequentially."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    for name in PIPELINES:
        target = None if dry_run else str(out / f"{name}.json")
        click.echo(f"\n=== Running pipeline: {name} ===")
        results = _run_one(
            name,
            paths=list(paths),
            chunk_limit=chunk_limit,
            workers=workers,
            model=model,
            output_path=target,
            dry_run=dry_run,
        )
        click.echo(
            f"[{name}] processed {len(results)} chunks"
            + (f" -> {target}" if target else "")
        )


if __name__ == "__main__":
    cli()
