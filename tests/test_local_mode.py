"""The local-only command surface: what exists, and that nothing cloud does.

The cloud commands (run, resume, credits, share, login, logout, slots)
are gone from this fork entirely; the CLI is setup, observe, local, and
start. These tests pin that surface and the offline posture.
"""

from __future__ import annotations

import argparse
import io

import pytest
from rich.console import Console

import weco.cli


def build_console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False, color_system=None)


def _build_parser() -> argparse.ArgumentParser:
    """Build the real top-level parser the way _main does."""
    import contextlib
    import sys as _sys

    parser = None

    # Reuse _main's construction by intercepting parse_args: feed it an
    # argument that makes argparse build everything, then capture the parser.
    original = argparse.ArgumentParser.parse_args

    def grab(self, *args, **kwargs):
        nonlocal parser
        parser = self
        raise SystemExit(0)

    argparse.ArgumentParser.parse_args = grab
    old_argv = _sys.argv
    _sys.argv = ["weco"]
    try:
        with contextlib.suppress(SystemExit):
            weco.cli._main()
    finally:
        argparse.ArgumentParser.parse_args = original
        _sys.argv = old_argv
    assert parser is not None
    return parser


def test_command_surface_is_local_only():
    parser = _build_parser()
    # The four survivors; every cloud command is gone.
    subparsers_action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    assert set(subparsers_action.choices) == {"setup", "observe", "local", "start"}


@pytest.mark.parametrize("gone", ["run", "resume", "credits", "share", "login", "logout", "slots"])
def test_cloud_commands_are_gone(gone, monkeypatch):
    import sys

    monkeypatch.setattr(sys, "argv", ["weco", gone])
    with pytest.raises(SystemExit) as excinfo:
        weco.cli.main()
    assert excinfo.value.code == 2  # argparse: invalid choice


def test_no_cloud_modules_remain():
    import importlib

    for module in [
        "weco.optimizer",
        "weco.auth",
        "weco.events",
        "weco.mode",
        "weco.env",
        "weco.credits",
        "weco.share",
        "weco.core.api",
    ]:
        try:
            importlib.import_module(module)
        except ModuleNotFoundError:
            continue
        raise AssertionError(f"{module} should not exist in the local-only fork")


def test_start_claude_runs_offline_without_login(monkeypatch):
    monkeypatch.setattr("weco.commands.start.cli._require_claude_cli", lambda console: None)
    recorded = {}

    def fake_runner(*, claude_args, api_key, console, billing, weco_api_base, effort, seed_prompt):
        recorded.update(api_key=api_key, billing=billing, weco_api_base=weco_api_base)
        return 0

    monkeypatch.setattr("weco.commands.start.tui_bridge.run_tui_bridge", fake_runner)
    from weco.commands.start import cli as start_cli

    with pytest.raises(SystemExit) as excinfo:
        start_cli._handle_claude(
            argparse.Namespace(allow_tools=False, claude_args=[], effort=None, headless=False, prompt=None), build_console()
        )
    assert excinfo.value.code == 0
    assert recorded["api_key"] is None
    assert recorded["billing"] == "claude"
    assert recorded["weco_api_base"] is None


def test_start_claude_has_no_billing_flag():
    from weco.commands.start import configure_start_parser

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    configure_start_parser(subparsers.add_parser("start"))
    help_text = parser.format_help()
    assert "--billing" not in help_text
