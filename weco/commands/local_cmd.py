"""``weco local run`` — the local optimization loop as a command."""

from __future__ import annotations

import argparse
import pathlib
import sys

from rich.console import Console


def configure_local_parser(local_parser: argparse.ArgumentParser) -> None:
    sub = local_parser.add_subparsers(dest="local_command", help="Local-mode commands")

    run_parser = sub.add_parser(
        "run",
        help="Run the local optimization loop (the configured harness provides the intelligence)",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    run_parser.add_argument(
        "--harness",
        type=str,
        choices=["opencode"],
        default="opencode",
        help="The locally configured agent harness that improves the code each step.",
    )
    run_parser.add_argument(
        "-e", "--eval-command", type=str, required=True, help="Shell command that prints 'metric_name: value'."
    )
    run_parser.add_argument("--metric", type=str, required=True, help="Primary metric name the eval prints.")
    run_parser.add_argument(
        "-g", "--goal", type=str, choices=["maximize", "max", "minimize", "min"], default="minimize", help="Optimization goal."
    )
    run_parser.add_argument("--steps", type=int, default=5, help="Number of improve-and-measure steps (default: 5).")
    run_parser.add_argument("--workdir", type=str, default=".", help="Workspace to optimize (default: current directory).")


def execute_local_command(args: argparse.Namespace, console: Console) -> None:
    if not getattr(args, "local_command", None):
        console.print("Usage: [bold]weco local run[/]")
        sys.exit(2)
    if args.local_command != "run":
        console.print(f"[red]Unknown local subcommand {args.local_command}.[/]")
        sys.exit(2)

    from weco.local.loop import local_optimize, make_opencode_step

    workdir = pathlib.Path(args.workdir).expanduser().resolve()
    if not workdir.is_dir():
        console.print(f"[red]workdir {workdir} is not a directory.[/]")
        sys.exit(1)

    harness_step = make_opencode_step(workdir, metric=args.metric, maximize=args.goal in ("maximize", "max"))
    summary = local_optimize(
        harness_step=harness_step,
        eval_command=args.eval_command,
        metric=args.metric,
        maximize=args.goal in ("maximize", "max"),
        steps=args.steps,
        workdir=workdir,
    )
    best = summary["best"]
    console.print(
        f"Local loop done: best {summary['metric']} = {best['value']} at step {best['step']} "
        f"(report: {workdir / '.weco' / 'local-loop' / 'report.json'})"
    )
