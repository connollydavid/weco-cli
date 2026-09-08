import argparse
import sys

from rich.console import Console
from rich.traceback import install

from . import build_identity
from .observe.cli import configure_observe_parser, execute_observe_command
from .commands.setup.targets import ALL_SETUP_OPTION_NAME, SETUP_TARGETS

install(show_locals=True)
console = Console()


def _add_setup_source_args(parser: argparse.ArgumentParser) -> None:
    """Add common source arguments to a setup subparser."""
    parser.add_argument(
        "--local", type=str, metavar="PATH", help="Use a local weco-skill directory instead of downloading (for development)"
    )


def configure_setup_parser(setup_parser: argparse.ArgumentParser) -> None:
    """Configure the setup command parser and its subcommands."""
    setup_subparsers = setup_parser.add_subparsers(dest="tool", help="AI tool to set up")

    for target in SETUP_TARGETS:
        target_parser = setup_subparsers.add_parser(target.name, help=target.help_text)
        _add_setup_source_args(target_parser)
        if target.name == "zcode":
            target_parser.add_argument(
                "--zai-endpoint",
                type=str,
                choices=["intl", "zh"],
                default="intl",
                help="z.ai region for the MCP servers: intl (api.z.ai, default) or zh (open.bigmodel.cn)",
            )
            target_parser.add_argument(
                "--zcode-config",
                type=str,
                default=".zcode/config.json",
                help="ZCode workspace config to merge the servers into (default: .zcode/config.json)",
            )
            target_parser.add_argument(
                "--force", action="store_true", help="Replace managed z.ai entries that differ instead of refusing"
            )

    all_parser = setup_subparsers.add_parser(ALL_SETUP_OPTION_NAME, help="Set up Weco for all supported AI tools")
    _add_setup_source_args(all_parser)


def main() -> None:
    """Main function for the Weco CLI."""
    try:
        _main()
    except KeyboardInterrupt:
        # Clean exit on Ctrl+C without traceback
        console.print("\n[yellow]Interrupted.[/]")
        sys.exit(130)  # Standard exit code for SIGINT


def _main() -> None:
    """Internal main function containing the CLI logic."""
    parser = argparse.ArgumentParser(
        description="Weco CLI\nEnhance your code with AI-driven optimization.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Global flags
    parser.add_argument(
        "--version",
        action="version",
        version=build_identity(),
        help="Show the version, the fork it comes from, and the installed commitish",
    )
    parser.add_argument(
        "--via-skill",
        action="store_true",
        help=argparse.SUPPRESS,  # Hidden flag for AI agents invoking via skill
    )

    subparsers = parser.add_subparsers(
        dest="command", help="Available commands"
    )  # Removed required=True for now to handle chatbot case easily

    # --- Setup Command Parser Setup ---
    setup_parser = subparsers.add_parser("setup", help="Set up Weco for use with AI tools")
    configure_setup_parser(setup_parser)

    # --- Observe Command Parser Setup ---
    observe_parser = subparsers.add_parser(
        "observe",
        help="Track optimization runs locally (init, log, list, show)",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    configure_observe_parser(observe_parser)

    # --- Local Command Parser Setup ---
    from .commands.local_cmd import configure_local_parser

    local_parser = subparsers.add_parser(
        "local",
        help="Local-mode commands (the optimization loop on your own infrastructure)",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    configure_local_parser(local_parser)

    # --- Start Command Parser Setup ---
    from .commands.start import configure_start_parser

    start_parser = subparsers.add_parser(
        "start",
        help="Launch an agent harness headlessly or bridged (claude, opencode, codex)",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    configure_start_parser(start_parser)

    args = parser.parse_args()

    if args.command == "setup":
        from .commands.setup import handle_setup_command

        handle_setup_command(args, console)
        sys.exit(0)
    elif args.command == "observe":
        execute_observe_command(args)
        sys.exit(0)
    elif args.command == "local":
        from .commands.local_cmd import execute_local_command

        execute_local_command(args, console)
        sys.exit(0)
    elif args.command == "start":
        from .commands.start import handle_start_command

        handle_start_command(args, console)
        sys.exit(0)
    else:
        # This case is hit when 'weco' runs alone or with an unknown command.
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
