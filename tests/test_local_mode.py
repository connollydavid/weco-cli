"""Tests for local mode: the default, and every telemetry gate it closes."""

from __future__ import annotations

import io
import threading
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from weco import mode
from weco.commands import make_client
from weco.commands.start import cli as start_cli
from weco.config import get_or_create_installation_id
from weco.events import SkillInstallStartedEvent, _is_events_disabled, send_event
from weco.mode import ModeError, resolve_mode


def build_console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False, color_system=None)


@pytest.fixture()
def local_mode(monkeypatch):
    monkeypatch.delenv("WECO_MODE", raising=False)


@pytest.fixture()
def cloud_mode(monkeypatch):
    monkeypatch.setenv("WECO_MODE", "weco")


def test_unset_mode_defaults_to_local(local_mode):
    assert resolve_mode() == mode.LOCAL
    assert mode.is_local() is True


def test_explicit_values_resolve(local_mode, monkeypatch):
    monkeypatch.setenv("WECO_MODE", "weco")
    assert resolve_mode() == mode.WECO
    monkeypatch.setenv("WECO_MODE", "LOCAL")
    assert resolve_mode() == mode.LOCAL


def test_invalid_mode_raises(local_mode, monkeypatch):
    monkeypatch.setenv("WECO_MODE", "serverless")
    with pytest.raises(ModeError):
        resolve_mode()
    # The telemetry gates fail safe: an invalid value counts as local.
    assert mode.is_local() is True


def test_events_disabled_in_local_mode(local_mode):
    assert _is_events_disabled() is True


def test_events_respect_optout_in_cloud_mode(cloud_mode, monkeypatch):
    monkeypatch.delenv("WECO_DISABLE_EVENTS", raising=False)
    assert _is_events_disabled() is False
    monkeypatch.setenv("WECO_DISABLE_EVENTS", "1")
    assert _is_events_disabled() is True


def test_send_event_spawns_no_thread_in_local_mode(local_mode, monkeypatch):
    def no_threads(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("send_event must not spawn a thread in local mode")

    monkeypatch.setattr(threading, "Thread", no_threads)
    send_event(SkillInstallStartedEvent(tool="opencode", source="local"))


def test_installation_id_never_created_in_local_mode(local_mode, monkeypatch, tmp_path):
    marker = tmp_path / "installation.json"
    monkeypatch.setattr("weco.config.INSTALLATION_FILE", marker)
    assert get_or_create_installation_id() is None
    assert not marker.exists()


def test_installation_id_persists_in_cloud_mode(cloud_mode, monkeypatch, tmp_path):
    marker = tmp_path / "installation.json"
    monkeypatch.setattr("weco.config.INSTALLATION_FILE", marker)
    monkeypatch.setattr("weco.config.ensure_config_dir", lambda: None)
    first = get_or_create_installation_id()
    assert first and first.startswith("inst_")
    assert get_or_create_installation_id() == first
    assert marker.exists()


def test_update_checks_skipped_in_local_mode(local_mode, monkeypatch):
    recorder = MagicMock()
    monkeypatch.setattr("weco.env.requests.get", recorder)
    env = __import__("weco.env", fromlist=["WecoEnv"]).WecoEnv(via_skill=False)
    env.check_for_updates()
    recorder.assert_not_called()


def test_update_checks_run_in_cloud_mode(cloud_mode, monkeypatch):
    recorder = MagicMock()
    response = MagicMock()
    response.json.return_value = {"info": {"version": "0.0.1"}}
    recorder.return_value = response
    monkeypatch.setattr("weco.env.requests.get", recorder)
    env = __import__("weco.env", fromlist=["WecoEnv"]).WecoEnv(via_skill=False)
    env.check_for_updates()
    # The PyPI lookup always runs; the skill-version lookup also runs when a
    # skill is installed (none is, in the sandboxed test home).
    assert recorder.call_count >= 1
    assert recorder.call_args_list[0].args[0].startswith("https://pypi.org")


def test_make_client_refuses_in_local_mode(local_mode):
    with pytest.raises(SystemExit) as excinfo:
        make_client(build_console())
    assert excinfo.value.code == 2


def test_make_client_authenticates_in_cloud_mode(cloud_mode, monkeypatch):
    monkeypatch.setattr("weco.commands.handle_authentication", lambda console: (None, {"Authorization": "Bearer x"}))
    client = make_client(build_console())
    assert client is not None


def test_start_claude_needs_no_login_in_local_mode(local_mode, monkeypatch):
    assert start_cli._require_api_key(build_console()) is None


def test_start_claude_requires_login_in_cloud_mode(cloud_mode):
    with pytest.raises(SystemExit) as excinfo:
        start_cli._require_api_key(build_console())
    assert excinfo.value.code == 1


def test_start_claude_rejects_weco_billing_in_local_mode(local_mode, monkeypatch):
    monkeypatch.setattr("weco.commands.start.cli._require_claude_cli", lambda console: None)
    import argparse

    with pytest.raises(SystemExit) as excinfo:
        start_cli._handle_claude(
            argparse.Namespace(allow_tools=False, claude_args=[], effort=None, billing="weco", headless=False, prompt=None),
            build_console(),
        )
    assert excinfo.value.code == 2


def test_start_claude_offline_in_local_mode(local_mode, monkeypatch):
    monkeypatch.setattr("weco.commands.start.cli._require_claude_cli", lambda console: None)
    recorded = {}

    def fake_runner(*, claude_args, api_key, console, billing, weco_api_base, effort, seed_prompt):
        recorded.update(api_key=api_key, billing=billing)
        return 0

    monkeypatch.setattr("weco.commands.start.tui_bridge.run_tui_bridge", fake_runner)
    import argparse

    with pytest.raises(SystemExit) as excinfo:
        start_cli._handle_claude(
            argparse.Namespace(allow_tools=False, claude_args=[], effort=None, billing="claude", headless=False, prompt=None),
            build_console(),
        )
    assert excinfo.value.code == 0
    assert recorded["api_key"] is None
    assert recorded["billing"] == "claude"
