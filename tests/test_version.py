"""Tests for the version surface: package version, fork, commitish."""

from __future__ import annotations

import json

import weco
from weco import build_identity


class _FakeDistribution:
    def __init__(self, direct_url: str | None):
        self._direct_url = direct_url

    def read_text(self, name: str) -> str | None:
        if name == "direct_url.json":
            return self._direct_url
        return None


def test_identity_names_the_commit_from_a_git_install(monkeypatch):
    direct = json.dumps(
        {"url": "https://github.com/connollydavid/weco-cli.git", "vcs_info": {"vcs": "git", "commit_id": "a" * 40}}
    )
    monkeypatch.setattr(weco.importlib.metadata, "distribution", lambda name: _FakeDistribution(direct))
    identity = build_identity()
    assert identity == f"weco {weco.__pkg_version__} ({weco.__fork_slug__}@{'a' * 12})"
    assert "unknown" not in identity


def test_identity_reads_the_flat_archive_commit_too(monkeypatch):
    direct = json.dumps({"url": "https://example/weco.zip", "commit_id": "b" * 40})
    monkeypatch.setattr(weco.importlib.metadata, "distribution", lambda name: _FakeDistribution(direct))
    assert f"@{'b' * 12}" in build_identity()


def test_identity_reports_unknown_commit_without_direct_url(monkeypatch):
    monkeypatch.setattr(weco.importlib.metadata, "distribution", lambda name: _FakeDistribution(None))
    identity = build_identity()
    assert identity == f"weco {weco.__pkg_version__} ({weco.__fork_slug__}, commit unknown)"


def test_identity_survives_metadata_errors(monkeypatch):
    def explode(name):
        raise RuntimeError("metadata unavailable")

    monkeypatch.setattr(weco.importlib.metadata, "distribution", explode)
    assert "commit unknown" in build_identity()


def test_version_flag_through_main(monkeypatch, capsys):
    import sys

    import pytest

    import weco.cli

    monkeypatch.setattr(sys, "argv", ["weco", "--version"])
    with pytest.raises(SystemExit) as excinfo:
        weco.cli.main()
    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("weco ")
    assert weco.__fork_slug__ in out
