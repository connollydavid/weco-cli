"""`weco start claude` / `weco start opencode` — launch a bridged agent harness."""

from __future__ import annotations

import argparse
import shutil
import sys

from rich.console import Console

from .sdk_config import VALID_EFFORTS


def configure_start_parser(start_parser: argparse.ArgumentParser) -> None:
    sub = start_parser.add_subparsers(dest="start_command", help="What to start")

    claude_parser = sub.add_parser(
        "claude",
        help="Launch Claude Code bridged to the Weco dashboard (bidirectional)",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    claude_parser.add_argument(
        "--allow-tools",
        action="store_true",
        help=(
            "Auto-approve all Claude Code tool calls (passes --dangerously-skip-permissions). "
            "Bash, Write, Edit etc. run without prompting. Use only when you trust the agent."
        ),
    )
    claude_parser.add_argument(
        "--effort",
        type=str,
        choices=list(VALID_EFFORTS),
        default=None,
        help=(
            "Thinking effort level. Raises the thinking-token budget so Claude returns "
            "`thinking` content blocks alongside its response — these stream into the "
            "dashboard's Reasoning section. Omit to inherit Claude's own default (no extra "
            "thinking)."
        ),
    )
    claude_parser.add_argument(
        "--headless",
        action="store_true",
        help=(
            "Run with no local TUI — stream only to the dashboard, printing key "
            "lifecycle lines to the console. Use when launching in the background "
            "(no terminal to draw into), e.g. an agent spawning a bridged session. "
            "Pair with --allow-tools (no local approval modal) and --prompt to seed "
            "the first turn; the dashboard is the interactive surface."
        ),
    )
    claude_parser.add_argument(
        "-p",
        "--prompt",
        type=str,
        default=None,
        help=(
            "Seed the first turn with this prompt instead of waiting for input. "
            "Required to make --headless do anything immediately; also works in the TUI."
        ),
    )
    claude_parser.add_argument(
        "claude_args",
        nargs=argparse.REMAINDER,
        help="Arguments to forward to claude (prefix with -- to separate from weco flags)",
    )

    opencode_parser = sub.add_parser(
        "opencode",
        help="Launch opencode headlessly, streaming its JSON events as normalized JSONL",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    opencode_parser.add_argument(
        "-p",
        "--prompt",
        type=str,
        default=None,
        help="The prompt for the run (opencode runs headlessly; there is no TUI to type into).",
    )
    opencode_parser.add_argument(
        "--agent",
        type=str,
        default=None,
        help="Run with a specific opencode agent (defaults to opencode's own default agent).",
    )
    opencode_parser.add_argument(
        "opencode_args",
        nargs=argparse.REMAINDER,
        help="Arguments to forward to opencode (prefix with -- to separate from weco flags)",
    )

    codex_parser = sub.add_parser(
        "codex",
        help="Launch Codex headlessly, streaming its JSON events as normalized JSONL",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    codex_parser.add_argument(
        "-p",
        "--prompt",
        type=str,
        default=None,
        help="The prompt for the run (codex exec runs headlessly; there is no TUI to type into).",
    )
    codex_parser.add_argument(
        "codex_args",
        nargs=argparse.REMAINDER,
        help="Arguments to forward to codex (prefix with -- to separate from weco flags)",
    )


def handle_start_command(args: argparse.Namespace, console: Console) -> None:
    sub = getattr(args, "start_command", None)
    if sub == "claude":
        _handle_claude(args, console)
    elif sub == "opencode":
        _handle_opencode(args, console)
    elif sub == "codex":
        _handle_codex(args, console)
    else:
        console.print("[red]Unknown start subcommand.[/]")
        console.print("Usage: [bold]weco start claude | weco start opencode | weco start codex[/]")
        sys.exit(2)


def _require_claude_cli(console: Console) -> None:
    """Fail fast (before creating a session or launching the TUI) if Claude
    Code isn't installed — `weco start claude` drives it under the hood."""
    if shutil.which("claude"):
        return
    console.print(
        "[red]Claude Code CLI not found.[/] [bold]weco start claude[/] runs Claude Code under the hood.\n"
        "Install it, then re-run: https://code.claude.com/docs/en/quickstart"
    )
    sys.exit(1)


def _strip_arg_separator(args: list[str]) -> list[str]:
    if args and args[0] == "--":
        return args[1:]
    return args


def _require_opencode_cli(console: Console) -> None:
    """Fail fast if opencode isn't installed — `weco start opencode` drives it."""
    if shutil.which("opencode"):
        return
    console.print(
        "[red]opencode CLI not found.[/] [bold]weco start opencode[/] runs opencode under the hood.\n"
        "Install it, then re-run: https://opencode.ai/docs/"
    )
    sys.exit(1)


def _handle_opencode(args: argparse.Namespace, console: Console) -> None:
    # No Weco login: the bridge spawns opencode, which resolves its own
    # providers and credentials from its configuration (see weco.harnesses).
    _require_opencode_cli(console)
    forwarded = _strip_arg_separator(list(getattr(args, "opencode_args", []) or []))
    from .opencode_bridge import run_opencode_bridge

    exit_code = run_opencode_bridge(
        prompt=getattr(args, "prompt", None), agent=getattr(args, "agent", None), forwarded_args=forwarded, console=console
    )
    sys.exit(exit_code)


def _require_codex_cli(console: Console) -> None:
    """Fail fast if the Codex CLI isn't installed — `weco start codex` drives it."""
    if shutil.which("codex"):
        return
    console.print(
        "[red]Codex CLI not found.[/] [bold]weco start codex[/] runs Codex under the hood.\n"
        "Install it, then re-run: https://developers.openai.com/codex/cli/"
    )
    sys.exit(1)


def _handle_codex(args: argparse.Namespace, console: Console) -> None:
    # No Weco login: Codex resolves its own authentication.
    _require_codex_cli(console)
    forwarded = _strip_arg_separator(list(getattr(args, "codex_args", []) or []))
    from .codex_bridge import run_codex_bridge

    exit_code = run_codex_bridge(prompt=getattr(args, "prompt", None), forwarded_args=forwarded, console=console)
    sys.exit(exit_code)


def _handle_claude(args: argparse.Namespace, console: Console) -> None:
    _require_claude_cli(console)

    forwarded = _strip_arg_separator(list(getattr(args, "claude_args", []) or []))
    if getattr(args, "allow_tools", False) and not any(a == "--dangerously-skip-permissions" for a in forwarded):
        forwarded.append("--dangerously-skip-permissions")

    effort = getattr(args, "effort", None)
    headless = getattr(args, "headless", False)
    seed_prompt = getattr(args, "prompt", None)

    from .tui_bridge import run_headless_bridge, run_tui_bridge

    runner = run_headless_bridge if headless else run_tui_bridge
    exit_code = runner(
        claude_args=forwarded,
        api_key=None,
        console=console,
        billing="claude",
        weco_api_base=None,
        effort=effort,
        seed_prompt=seed_prompt,
    )
    sys.exit(exit_code)
