"""Tests for `weco start codex`: parser, dispatch, and the streaming bridge.

No network, no real codex binary: the bridge is exercised against a fake
``codex`` script emitting the fixture event stream. The fixtures pin the
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
from weco.commands.start.codex_bridge import normalize_event, run_codex_bridge


def build_start_parser() -> argparse.ArgumentParser:
    from weco.commands.start import configure_start_parser

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    configure_start_parser(subparsers.add_parser("start"))
    return parser


def build_console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False, color_system=None)


def test_start_parser_accepts_codex_flags():
    parser = build_start_parser()
    args = parser.parse_args(["start", "codex", "-p", "optimize this", "--", "--model", "gpt-5.3-codex"])
    assert args.start_command == "codex"
    assert args.prompt == "optimize this"
    assert args.codex_args == ["--", "--model", "gpt-5.3-codex"]


def test_dispatch_requires_codex_binary(monkeypatch):
    monkeypatch.setattr("weco.commands.start.cli.shutil.which", lambda name: None)
    with pytest.raises(SystemExit) as excinfo:
        handle_start_command(argparse.Namespace(start_command="codex", prompt="hi", codex_args=[]), build_console())
    assert excinfo.value.code == 1


def test_dispatch_runs_bridge_and_exits_with_its_code(monkeypatch):
    monkeypatch.setattr("weco.commands.start.cli.shutil.which", lambda name: "/usr/bin/codex")
    recorded = {}

    def fake_bridge(*, prompt, forwarded_args, console, stdout=None):  # noqa: ANN003
        recorded.update(prompt=prompt, forwarded_args=forwarded_args)
        return 5

    monkeypatch.setattr("weco.commands.start.codex_bridge.run_codex_bridge", fake_bridge)
    with pytest.raises(SystemExit) as excinfo:
        handle_start_command(
            argparse.Namespace(start_command="codex", prompt="hi", codex_args=["--", "--sandbox", "workspace-write"]),
            build_console(),
        )
    assert excinfo.value.code == 5
    assert recorded["prompt"] == "hi"
    assert recorded["forwarded_args"] == ["--sandbox", "workspace-write"]


def test_normalize_event_flattens_known_kinds():
    thread = normalize_event({"type": "thread.started", "thread_id": "th_1"})
    assert thread == {"type": "codex.thread.started", "thread_id": "th_1"}

    item = normalize_event({"type": "item.completed", "item": {"item_type": "agent_message", "text": "done optimizing"}})
    assert item["item_type"] == "agent_message"
    assert item["text"] == "done optimizing"


def test_normalize_event_passes_unknown_kinds_through():
    envelope = normalize_event({"type": "turn.completed", "usage": {"input": 4}})
    assert envelope["type"] == "codex.turn.completed"
    assert envelope["data"] == {"type": "turn.completed", "usage": {"input": 4}}


def _fake_codex(tmp_path: pathlib.Path, events: list[dict]) -> pathlib.Path:
    binary = tmp_path / "codex"
    payload = "".join(f"echo '{json.dumps(event)}'\n" for event in events)
    binary.write_text("#!/bin/sh\n" + payload, encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    return binary


def test_bridge_streams_normalized_jsonl(tmp_path, monkeypatch):
    events = [
        {"type": "thread.started", "thread_id": "th_1"},
        {"type": "item.completed", "item": {"item_type": "agent_message", "text": "hi"}},
        {"type": "turn.completed", "usage": {"input": 1}},
    ]
    _fake_codex(tmp_path, events)  # presence on PATH is what matters
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', '')}")
    captured = io.StringIO()
    code = run_codex_bridge(
        prompt="do the thing", forwarded_args=["--sandbox", "read-only"], console=build_console(), stdout=captured
    )
    assert code == 0
    out_lines = [json.loads(line) for line in captured.getvalue().splitlines() if line.startswith("{")]
    assert [event["type"] for event in out_lines] == ["codex.thread.started", "codex.item.completed", "codex.turn.completed"]
    assert out_lines[1]["text"] == "hi"
