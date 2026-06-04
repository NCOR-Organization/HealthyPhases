"""Click CLI for ProcessDispositionExtractionWorkflow.

Examples
--------
Dry run (first candidate chunk, no writes):
    uv run abi run script abi_phases/phases/workflows/ProcessDispositionExtractionWorkflow/run_extraction.py run --dry-run

Run over a limited set of chunks and dump JSON:
    uv run abi run script abi_phases/phases/workflows/ProcessDispositionExtractionWorkflow/run_extraction.py run \
        --chunk-limit 20 --output ./out/process_dispositions.json

Restrict to specific paper paths (repeatable):
    uv run abi run script abi_phases/phases/workflows/ProcessDispositionExtractionWorkflow/run_extraction.py run \
        --path ".../paper1.pdf" --path ".../paper2.pdf"
"""

from __future__ import annotations

from pathlib import Path

import click

from phases.workflows.ProcessDispositionExtractionWorkflow.ProcessDispositionExtractionWorkflow import (
    ProcessDispositionExtractionWorkflow,
    ProcessDispositionExtractionWorkflowConfiguration,
    ProcessDispositionExtractionWorkflowParameters,
)

PROMPTS_DIR = Path(__file__).parent / "prompts"
DEFAULT_PROMPT = PROMPTS_DIR / "probabilistic_processes.txt"


@click.group()
def cli() -> None:
    """Extract probability-modulating BFO process-disposition relations."""


@cli.command("run")
@click.option(
    "--prompt-file",
    type=click.Path(exists=True, dir_okay=False),
    default=str(DEFAULT_PROMPT),
    show_default=True,
    help="Prompt template (must contain {chunk_text}).",
)
@click.option(
    "--path",
    "paths",
    multiple=True,
    help="Restrict to chunks from this paper path (repeatable).",
)
@click.option(
    "--chunk-limit",
    type=int,
    default=None,
    help="Max number of chunks to process.",
)
@click.option(
    "--workers",
    type=int,
    default=None,
    help="Parallel LLM workers.",
)
@click.option(
    "--model",
    type=str,
    default="gpt-5-mini",
    show_default=True,
    help="LLM model name.",
)
@click.option(
    "--max-relations",
    type=int,
    default=8,
    show_default=True,
    help="Max relations kept per chunk.",
)
@click.option(
    "--no-label-linking",
    is_flag=True,
    default=False,
    help="Skip looking up canonical ExtractedLabel matches.",
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False),
    default=None,
    help="Write {chunk_id: [relations]} JSON to this path.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Process only the first candidate chunk, print result, do not persist.",
)
def run_cmd(
    prompt_file: str,
    paths: tuple[str, ...],
    chunk_limit: int | None,
    workers: int | None,
    model: str,
    max_relations: int,
    no_label_linking: bool,
    output: str | None,
    dry_run: bool,
) -> None:
    """Run the probability-modulating disposition extraction."""
    prompt_template = Path(prompt_file).read_text()

    workflow = ProcessDispositionExtractionWorkflow(
        ProcessDispositionExtractionWorkflowConfiguration(
            prompt_template=prompt_template,
            model_name=model,
            max_relations_per_chunk=max_relations,
            link_to_labels=not no_label_linking,
        )
    )
    results = workflow.run(
        ProcessDispositionExtractionWorkflowParameters(
            paths=list(paths) or None,
            chunk_limit=chunk_limit,
            workers=workers,
            output_path=output,
            dry_run=dry_run,
        )
    )
    total = sum(len(v) for v in results.values())
    click.echo(
        f"processed {len(results)} chunks, {total} relations"
        + (f" -> {output}" if output else "")
    )


if __name__ == "__main__":
    cli()
