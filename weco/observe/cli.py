"""CLI commands for weco observe.

Exit-code policy follows each command's role in the caller's workflow, not a
fault taxonomy:

- ``init`` runs once, before the loop being tracked exists. Any failure exits
  non-zero: nothing is at risk yet, and ``RUN_ID=$(weco observe init ...)``
  must never capture an empty string from a "polite" exit 0.
- ``log`` runs inside the tracked loop (often under ``set -e``). Errors the
  caller must fix (bad ``--metrics`` JSON, unreadable ``--source``, not logged
  in, a 4xx from the API) exit non-zero; weco-side failures print to stderr
  and exit 0 so a blip never crashes the tracked loop. ``--strict`` opts into
  making those fatal as well.
"""

import argparse
import json
import sys


def configure_observe_parser(observe_parser: argparse.ArgumentParser) -> None:
    """Configure the observe command parser and all its subcommands."""
    subparsers = observe_parser.add_subparsers(dest="observe_command", help="Observe commands")

    # --- init ---
    init_parser = subparsers.add_parser("init", help="Initialize an external run for tracking")
    init_parser.add_argument("--name", type=str, default=None, help="Run name")
    init_parser.add_argument("--metric", type=str, required=True, help="Primary metric name (e.g. val_bpb)")
    init_parser.add_argument(
        "-g",
        "--goal",
        type=str,
        choices=["maximize", "max", "minimize", "min"],
        default="minimize",
        help="Specify 'maximize'/'max' or 'minimize'/'min' (default: minimize)",
    )
    init_source_group = init_parser.add_mutually_exclusive_group(required=True)
    init_source_group.add_argument(
        "-s", "--source", type=str, help="Path to a single source code file to track (e.g. train.py)"
    )
    init_source_group.add_argument(
        "--sources", nargs="+", type=str, help="Paths to multiple source code files to track (e.g. train.py prepare.py)"
    )
    init_parser.add_argument(
        "-i", "--additional-instructions", type=str, default=None, help="Additional instructions for the run"
    )

    # --- log ---
    log_parser = subparsers.add_parser("log", help="Log a step for an external run")
    log_parser.add_argument("--run-id", type=str, required=True, help="Run ID (from weco observe init)")
    log_parser.add_argument("--step", type=int, required=True, help="Step number")
    log_parser.add_argument(
        "--status", type=str, default="completed", choices=["completed", "failed"], help="Step status (default: completed)"
    )
    log_parser.add_argument("--description", type=str, default=None, help="Description of what was tried")
    log_parser.add_argument("--metrics", type=str, default=None, help="Metrics as JSON (e.g. '{\"val_bpb\": 1.03}')")
    log_source_group = log_parser.add_mutually_exclusive_group()
    log_source_group.add_argument("-s", "--source", type=str, default=None, help="Single source code file to snapshot")
    log_source_group.add_argument(
        "--sources", nargs="+", type=str, default=None, help="Multiple source code files to snapshot"
    )
    log_parser.add_argument("--parent-step", type=int, default=None, help="Parent step number for tree lineage")
    log_parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when weco itself fails (default: warn on stderr and exit 0 so the tracked loop survives)",
    )

    # --- complete/fail are no longer needed ---
    # External run lifecycle is managed by the dashboard, not the CLI.
    # Logging a step to a closed run will silently reopen it.

    # --- list / show (local mode's reading surface) ---
    subparsers.add_parser("list", help="List locally tracked runs (local mode)")
    show_parser = subparsers.add_parser("show", help="Show a locally tracked run and its steps (local mode)")
    show_parser.add_argument("--run-id", type=str, required=True, help="Run ID (from weco observe init)")


def _read_code_files(paths: list[str]) -> dict[str, str]:
    """Read source code files from disk. Exits 1 if any file cannot be read.

    All-or-nothing: silently logging a partial snapshot would show wrong
    code recorded for the run, so a single unreadable file fails the command.
    """
    source_code = {}
    for path in paths:
        try:
            with open(path) as f:
                source_code[path] = f.read()
        except (OSError, UnicodeDecodeError) as e:
            print(f"weco observe: cannot read {path}: {e}", file=sys.stderr)
            sys.exit(1)
    return source_code


def execute_observe_command(args: argparse.Namespace) -> None:
    """Execute an observe subcommand."""
    if not args.observe_command:
        print("Usage: weco observe {init,log,list,show}", file=sys.stderr)
        sys.exit(2)

    _execute_local(args)


def _execute_local(args: argparse.Namespace) -> None:
    """Record under .weco/observe; post nothing, open nothing."""
    import pathlib

    from weco.observe.local_store import LocalStore, LocalStoreError

    store = LocalStore(pathlib.Path.cwd())

    if args.observe_command == "init":
        source_arg = args.sources if args.sources is not None else [args.source]
        source_code = _read_code_files(source_arg)
        run_id = store.init_run(
            name=args.name,
            metric=args.metric,
            maximize=args.goal in ("maximize", "max"),
            source_code=source_code,
            additional_instructions=args.additional_instructions,
        )
        # Only the run_id on stdout, capturable by $(...); where it lives on stderr.
        print(run_id)
        print(f"weco observe: tracking locally under {store.observe_dir}", file=sys.stderr)
    elif args.observe_command == "log":
        metrics = {}
        if args.metrics:
            try:
                metrics = json.loads(args.metrics)
            except json.JSONDecodeError as e:
                print(f"weco observe: invalid metrics JSON: {e}", file=sys.stderr)
                sys.exit(1)
        code = None
        source_arg = args.sources if args.sources is not None else ([args.source] if args.source else None)
        if source_arg:
            code = _read_code_files(source_arg)
        try:
            store.log_step(
                run_id=args.run_id,
                step=args.step,
                status=args.status,
                description=args.description,
                metrics=metrics,
                code=code,
                parent_step=args.parent_step,
            )
        except LocalStoreError as e:
            print(f"weco observe: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.observe_command == "list":
        for record in store.list_runs():
            print(
                f"{record.get('run_id')}  steps={record.get('steps', 0):3d}  "
                f"{record.get('metric')} ({record.get('goal')})  {record.get('name') or ''}"
            )
    elif args.observe_command == "show":
        try:
            print(json.dumps(store.show_run(args.run_id), indent=2))
        except LocalStoreError as e:
            print(f"weco observe: {e}", file=sys.stderr)
            sys.exit(1)
