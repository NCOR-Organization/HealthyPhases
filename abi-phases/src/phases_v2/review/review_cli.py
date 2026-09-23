"""Run with uv run abi run script src/phases_v2/review/review_cli.py -- ..."""

import argparse
import json
from pathlib import Path

from phases_v2.review.review_automation import automatic_review
from phases_v2.review.review_factory import model_for, service_for
from phases_v2.review.review_report import render_report


def main(argv=None, engine=None):
    parser = argparse.ArgumentParser(
        description="Review extracted effects before trusted search"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("--output", type=Path, required=True)
    auto = sub.add_parser("auto")
    auto.add_argument("--model", required=True)
    for command in (export, auto):
        command.add_argument("--after", default="")
        command.add_argument(
            "--limit", type=int, choices=range(1, 201), default=100, metavar="1..200"
        )
    apply = sub.add_parser("apply")
    apply.add_argument("--decisions", type=Path, required=True)
    args = parser.parse_args(argv)
    if engine is None:
        from phases_v2 import ABIModule

        engine = ABIModule.get_instance().engine
    service = service_for(engine)
    if args.command == "export":
        rows = service.queue(after=args.after, limit=args.limit)
        args.output.write_text(render_report(rows), encoding="utf-8")
        print(
            json.dumps(
                {
                    "rows": len(rows),
                    "next_after": rows[-1]["relation_id"] if rows else None,
                    "output": str(args.output),
                }
            )
        )
    elif args.command == "apply":
        events = service.decide(json.loads(args.decisions.read_text()))
        print(json.dumps({"recorded_events": events}))
    else:
        report = automatic_review(
            service,
            model_for(engine, args.model),
            args.model,
            after=args.after,
            limit=args.limit,
        )
        print(json.dumps(report))
        if report["errors"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
