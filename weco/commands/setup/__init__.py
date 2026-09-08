"""Setup commands for integrating Weco with various AI tools."""

import pathlib
import sys
import tempfile

from rich.console import Console
from rich.prompt import Prompt

from ...utils import DownloadError
from .install import SafetyError, SetupError, download_skill_archive, install_target
from .targets import ALL_SETUP_OPTION_LABEL, ALL_SETUP_OPTION_NAME, SETUP_TARGET_BY_NAME, SETUP_TARGET_NAMES, SETUP_TARGETS


class _SkillSource:
    """Resolves the skill source directory on first use, downloading once if needed.

    Use as a context manager so any downloaded tempdir is cleaned up on exit.
    The resolved path is reused across every target so ``weco setup all``
    downloads exactly once.
    """

    def __init__(self, local_path: pathlib.Path | None, console: Console):
        self._local_path = local_path
        self._console = console
        self._tmp_dir: tempfile.TemporaryDirectory | None = None
        self._downloaded_path: pathlib.Path | None = None

    def __enter__(self) -> "_SkillSource":
        return self

    def __exit__(self, *exc_info) -> None:
        if self._tmp_dir is not None:
            self._tmp_dir.cleanup()
            self._tmp_dir = None

    @property
    def kind(self) -> str:
        return "local" if self._local_path else "download"

    def path(self) -> pathlib.Path:
        if self._local_path is not None:
            return self._local_path
        if self._downloaded_path is None:
            self._tmp_dir = tempfile.TemporaryDirectory()
            dest = pathlib.Path(self._tmp_dir.name) / "skill"
            download_skill_archive(dest, self._console)
            self._downloaded_path = dest
        return self._downloaded_path


def prompt_tool_selection(console: Console) -> list[str]:
    """Prompt the user to select which tool(s) to set up."""
    tool_names = list(SETUP_TARGET_NAMES)
    all_option = len(tool_names) + 1

    console.print("\n[bold cyan]Available tools to set up:[/]\n")
    for i, target in enumerate(SETUP_TARGETS, 1):
        console.print(f"  {i}. {target.label} [dim]({target.name})[/]")
    console.print(f"  {all_option}. {ALL_SETUP_OPTION_LABEL} [dim](default)[/]\n")

    valid_choices = [str(i) for i in range(1, all_option + 1)]
    choice = Prompt.ask("[bold]Select an option[/]", choices=valid_choices, default=str(all_option), show_choices=True)

    idx = int(choice)
    if idx == all_option:
        return tool_names
    return [tool_names[idx - 1]]


def run_setup_for_tool(tool: str, console: Console, source: _SkillSource) -> None:
    """Run setup for a single tool."""
    try:
        source_path = source.path()
        install_target(SETUP_TARGET_BY_NAME[tool], console, source_path)
    except DownloadError as e:
        console.print(f"\n[bold red]Error:[/] {e}")
        sys.exit(1)
    except SafetyError as e:
        console.print(f"\n[bold red]Safety Error:[/] {e}")
        sys.exit(1)
    except (SetupError, FileNotFoundError, OSError, ValueError) as e:
        console.print(f"\n[bold red]Error:[/] {e}")
        sys.exit(1)


def handle_setup_command(args, console: Console) -> None:
    """Handle the ``weco setup`` command."""

    if args.tool is None:
        selected_tools = prompt_tool_selection(console)
    elif args.tool == ALL_SETUP_OPTION_NAME:
        selected_tools = list(SETUP_TARGET_NAMES)
    elif args.tool in SETUP_TARGET_BY_NAME:
        selected_tools = [args.tool]
    else:
        available = ", ".join((*SETUP_TARGET_NAMES, ALL_SETUP_OPTION_NAME))
        console.print(f"[bold red]Error:[/] Unknown tool: {args.tool}")
        console.print(f"Available tools: {available}")
        sys.exit(1)

    local_path = None
    if getattr(args, "local", None):
        local_path = pathlib.Path(args.local).expanduser().resolve()
        console.print(f"[bold cyan]Using local skill source:[/] {local_path}\n")

    with _SkillSource(local_path, console) as source:
        for tool in selected_tools:
            run_setup_for_tool(tool, console, source)

    # The z.ai MCP wiring runs only on the explicit zcode selection (never
    # from the all shortcut): it writes a workspace config file.
    if getattr(args, "tool", None) == "zcode":
        _wire_zcode_mcp(args, console)

    console.print("\n[bold green]Setup complete.[/]")


def _wire_zcode_mcp(args, console: Console) -> None:
    """Merge the z.ai MCP servers into the ZCode workspace config."""
    from weco.harnesses.zcode import ZcodeConfigError, write_config

    config_path = pathlib.Path(getattr(args, "zcode_config", ".zcode/config.json")).expanduser().resolve()
    region = getattr(args, "zai_endpoint", "intl")
    force = bool(getattr(args, "force", False))
    try:
        exports = write_config(config_path, region, force=force)
    except ZcodeConfigError as e:
        console.print(f"[bold red]z.ai MCP wiring failed:[/] {e}")
        sys.exit(1)
    console.print(f"[cyan]z.ai MCP servers ({region}) merged into {config_path}[/]")
    console.print("[yellow]Export before starting ZCode:[/]")
    for line in exports:
        console.print(f"  {line}")
