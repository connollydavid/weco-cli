"""Tests for `weco start opencode`: parser, dispatch, and the streaming bridge.

No network, no real opencode binary: the bridge is exercised against a fake
``opencode`` script that emits the fixture event stream. The fixtures pin the
event shapes this bridge understands.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import pathlib
import stat

import pytest
from rich.console import Console

from weco.commands.start.cli import handle_start_command
from weco.commands.start.opencode_bridge import normalize_event, run_opencode_bridge


def build_start_parser() -> argparse.ArgumentParser:
    from weco.commands.start import configure_start_parser

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    configure_start_parser(subparsers.add_parser("start"))
    return parser


def build_console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False, color_system=None)


def test_start_parser_accepts_opencode_flags():
    parser = build_start_parser()
    args = parser.parse_args(
        ["start", "opencode", "--agent", "build", "-p", "optimize this", "--", "--model", "anthropic/claude"]
    )
    assert args.start_command == "opencode"
    assert args.agent == "build"
    assert args.prompt == "optimize this"
    assert args.opencode_args == ["--", "--model", "anthropic/claude"]


def test_dispatch_requires_opencode_binary(monkeypatch):
    monkeypatch.setattr("weco.commands.start.cli.shutil.which", lambda name: None)
    with pytest.raises(SystemExit) as excinfo:
        handle_start_command(
            argparse.Namespace(start_command="opencode", prompt="hi", agent=None, opencode_args=[]), build_console()
        )
    assert excinfo.value.code == 1


def test_dispatch_runs_bridge_and_exits_with_its_code(monkeypatch):
    monkeypatch.setattr("weco.commands.start.cli.shutil.which", lambda name: "/usr/bin/opencode")
    recorded = {}

    def fake_bridge(*, prompt, agent, forwarded_args, console, stdout=None):
        recorded.update(prompt=prompt, agent=agent, forwarded_args=forwarded_args)
        return 7

    monkeypatch.setattr("weco.commands.start.opencode_bridge.run_opencode_bridge", fake_bridge)
    with pytest.raises(SystemExit) as excinfo:
        handle_start_command(
            argparse.Namespace(start_command="opencode", prompt="hi", agent="build", opencode_args=["--", "--model", "x/y"]),
            build_console(),
        )
    assert excinfo.value.code == 7
    assert recorded["prompt"] == "hi"
    assert recorded["agent"] == "build"
    assert recorded["forwarded_args"] == ["--model", "x/y"]


def test_normalize_event_flattens_known_kinds():
    session = normalize_event({"type": "session.id", "sessionID": "ses_123"})
    assert session == {"type": "opencode.session.id", "session_id": "ses_123"}

    message = normalize_event(
        {
            "type": "message.updated",
            "sessionID": "ses_123",
            "message": {"role": "assistant", "parts": [{"type": "text", "text": "hello "}, {"type": "text", "text": "world"}]},
        }
    )
    assert message["role"] == "assistant"
    assert message["text"] == "hello world"

    part = normalize_event({"type": "message.part.updated", "part": {"type": "text", "text": "delta"}})
    assert part["text"] == "delta"


def test_normalize_event_passes_unknown_kinds_through():
    envelope = normalize_event({"type": "cost.updated", "cost": {"input": 1}})
    assert envelope["type"] == "opencode.cost.updated"
    assert envelope["data"] == {"type": "cost.updated", "cost": {"input": 1}}


def _fake_opencode(tmp_path: pathlib.Path, lines: list[str]) -> pathlib.Path:
    binary = tmp_path / "opencode"
    payload = "".join(f"echo '{json.dumps(line)}'\n" for line in lines)
    binary.write_text("#!/bin/sh\n" + payload, encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    return binary


def test_bridge_streams_normalized_jsonl(tmp_path, monkeypatch):
    events = [
        {"type": "session.id", "sessionID": "ses_1"},
        {"type": "message.updated", "message": {"role": "assistant", "parts": [{"type": "text", "text": "hi"}]}},
        {"type": "cost.updated", "cost": {"input": 3}},
    ]
    binary = _fake_opencode(tmp_path, events)  # noqa: F841  (presence on PATH is what matters)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', '')}")
    # The fake binary ignores its arguments and always emits the fixture stream.
    captured = io.StringIO()
    code = run_opencode_bridge(
        prompt="do the thing", agent=None, forwarded_args=["--model", "x/y"], console=build_console(), stdout=captured
    )
    assert code == 0
    out_lines = [json.loads(line) for line in captured.getvalue().splitlines() if line.startswith("{")]
    assert [event["type"] for event in out_lines] == [
        "opencode.session.id",
        "opencode.message.updated",
        "opencode.cost.updated",
    ]
    assert out_lines[1]["text"] == "hi"
