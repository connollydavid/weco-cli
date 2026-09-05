"""The no-phone-home guard: in local mode, nothing reaches the network.

This is the standing lane every later milestone runs too: any outbound
HTTP attempt during a local-mode command run fails the test. ``requests``
is patched at the session layer and the low-level adapter, and the socket
constructor is instrumented so a library bypassing requests is caught as
well (localhost and unix sockets aside, none of which local mode opens).
"""

from __future__ import annotations

import argparse
import io
import pathlib
import socket

import pytest
from rich.console import Console

import weco.cli as weco_cli
from weco.commands.setup import handle_setup_command


@pytest.fixture()
def local_home(tmp_path, monkeypatch):
    monkeypatch.delenv("WECO_MODE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "home" / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "home" / ".local" / "share"))
    monkeypatch.delenv("WECO_API_KEY", raising=False)
    monkeypatch.delenv("WECO_DISABLE_EVENTS", raising=False)
    monkeypatch.delenv("OPENCODE_CONFIG", raising=False)
    monkeypatch.delenv("OPENCODE_CONFIG_CONTENT", raising=False)
    (tmp_path / "home").mkdir()
    return tmp_path


@pytest.fixture()
def network_is_closed(monkeypatch):
    calls: list[str] = []

    def refuse(*args, **kwargs):  # noqa: ANN002, ANN003
        calls.append(f"requests {args}")
        raise AssertionError(f"local mode attempted an HTTP call: {args} {kwargs}")

    real_socket = socket.socket

    class GuardSocket(real_socket):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
            family = args[0] if args else kwargs.get("family", socket.AF_INET)
            if family not in (socket.AF_UNIX,):
                calls.append("socket")
                raise AssertionError("local mode attempted to open a network socket")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("weco.core.api.requests.Session.request", refuse)
    monkeypatch.setattr("weco.events.requests.post", refuse)
    monkeypatch.setattr("weco.env.requests.get", refuse)
    monkeypatch.setattr("weco.auth.requests.post", refuse)
    monkeypatch.setattr("weco.observe.api.requests.request", refuse)
    monkeypatch.setattr(socket, "socket", GuardSocket)
    return calls


def _run_main(argv: list[str]) -> None:
    import contextlib

    with contextlib.suppress(SystemExit):
        weco_cli.main()


def test_main_dispatch_makes_no_calls(local_home, network_is_closed, capsys, monkeypatch):
    # A bare dispatch (the old update-check site) with no command args:
    # argparse prints usage and exits; nothing may touch the network first.
    monkeypatch.setattr("sys.argv", ["weco"])
    _run_main([])
    assert network_is_closed == []


def test_setup_local_source_makes_no_calls(local_home, network_is_closed, tmp_path, monkeypatch):
    source = tmp_path / "skill"
    source.mkdir()
    (source / "SKILL.md").write_text("---\nname: weco\ndescription: t\n---\n", encoding="utf-8")

    # The registry resolves install paths at import time, so point the
    # opencode target at the sandboxed home explicitly (the frozen dataclass
    # is replaced in place; the install path itself is the real code).
    import dataclasses

    import weco.commands.setup.install as setup_install
    from weco.commands.setup.targets import SETUP_TARGET_BY_NAME

    sandboxed = dataclasses.replace(
        SETUP_TARGET_BY_NAME["opencode"],
        install_dir=pathlib.Path(local_home) / "home" / ".config" / "opencode" / "skills" / "weco",
    )
    monkeypatch.setitem(SETUP_TARGET_BY_NAME, "opencode", sandboxed)
    monkeypatch.setattr(setup_install, "_ALLOWED_SKILL_PARENTS", {sandboxed.install_parent})

    args = argparse.Namespace(command="setup", tool="opencode", local=str(source))
    handle_setup_command(args, Console(file=io.StringIO(), force_terminal=False, color_system=None))
    installed = pathlib.Path(local_home) / "home" / ".config" / "opencode" / "skills" / "weco" / "SKILL.md"
    assert installed.is_file()
    assert not (pathlib.Path(local_home) / "home" / ".config" / "weco" / "installation.json").exists()
    assert network_is_closed == []


def test_observe_local_roundtrip_makes_no_calls(local_home, network_is_closed, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    from weco.observe.cli import execute_observe_command

    (tmp_path / "train.py").write_text("x = 1\n", encoding="utf-8")
    execute_observe_command(
        argparse.Namespace(
            observe_command="init",
            name=None,
            metric="m",
            goal="minimize",
            source="train.py",
            sources=None,
            additional_instructions=None,
        )
    )
    run_id = capsys.readouterr().out.strip()
    execute_observe_command(
        argparse.Namespace(
            observe_command="log",
            run_id=run_id,
            step=0,
            status="completed",
            description=None,
            metrics='{"m": 1}',
            source=None,
            sources=None,
            parent_step=None,
            strict=False,
        )
    )
    assert (tmp_path / ".weco" / "observe" / "runs" / run_id / "steps.jsonl").is_file()
    assert network_is_closed == []
