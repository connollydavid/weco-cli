"""Tests for the opencode setup target and install placement."""

from __future__ import annotations

import argparse
import io
import pathlib

from rich.console import Console

from weco.cli import configure_setup_parser
from weco.commands.setup import install as setup_install
from weco.commands.setup.install import SetupError, install_target
from weco.commands.setup.targets import SETUP_TARGET_BY_NAME, SetupTarget


def build_setup_parser() -> argparse.ArgumentParser:
    """Create an isolated parser for setup command tests."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    setup_parser = subparsers.add_parser("setup")
    configure_setup_parser(setup_parser)
    return parser


def build_console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False, color_system=None)


def make_skill_source(root: pathlib.Path) -> pathlib.Path:
    """A minimal valid skill source: SKILL.md plus reference and asset files."""
    source = root / "skill-source"
    (source / "references").mkdir(parents=True)
    (source / "assets").mkdir()
    (source / "SKILL.md").write_text("---\nname: weco\ndescription: test\n---\n", encoding="utf-8")
    (source / "references" / "prepare.md").write_text("reference\n", encoding="utf-8")
    (source / "assets" / "evaluate-wrapper.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    return source


def test_opencode_target_registered():
    target = SETUP_TARGET_BY_NAME["opencode"]
    assert target.label == "opencode"
    assert target.install_dir == pathlib.Path.home() / ".config" / "opencode" / "skills" / "weco"
    assert target.extra_files == ()


def test_setup_parser_accepts_opencode():
    parser = build_setup_parser()
    args = parser.parse_args(["setup", "opencode"])
    assert args.tool == "opencode"


def test_install_target_places_opencode_layout(tmp_path, monkeypatch):
    """A real install run: files land under the opencode skills root, verbatim."""
    home = tmp_path / "home"
    target = SetupTarget(
        name="opencode-test",
        label="opencode-test",
        help_text="",
        install_dir=home / ".config" / "opencode" / "skills" / "weco",
    )
    monkeypatch.setattr(setup_install, "_ALLOWED_SKILL_PARENTS", {target.install_parent})
    source = make_skill_source(tmp_path)

    install_target(target, build_console(), source)

    installed = target.install_dir
    assert (installed / "SKILL.md").is_file()
    assert (installed / "references" / "prepare.md").is_file()
    assert (installed / "assets" / "evaluate-wrapper.sh").is_file()
    # The source tree must not be mutated by the install.
    assert (source / "SKILL.md").is_file()


def test_install_target_replaces_stale_install(tmp_path, monkeypatch):
    """Re-running an install replaces the directory instead of merging into it."""
    home = tmp_path / "home"
    target = SetupTarget(
        name="opencode-test",
        label="opencode-test",
        help_text="",
        install_dir=home / ".config" / "opencode" / "skills" / "weco",
    )
    monkeypatch.setattr(setup_install, "_ALLOWED_SKILL_PARENTS", {target.install_parent})
    source = make_skill_source(tmp_path)

    install_target(target, build_console(), source)
    stale = target.install_dir / "references" / "stale.md"
    stale.write_text("stale\n", encoding="utf-8")

    install_target(target, build_console(), source)
    assert not stale.exists()
    assert (target.install_dir / "SKILL.md").is_file()


def test_install_target_rejects_source_without_skill(tmp_path, monkeypatch):
    home = tmp_path / "home"
    target = SetupTarget(
        name="opencode-test",
        label="opencode-test",
        help_text="",
        install_dir=home / ".config" / "opencode" / "skills" / "weco",
    )
    monkeypatch.setattr(setup_install, "_ALLOWED_SKILL_PARENTS", {target.install_parent})
    empty = tmp_path / "empty"
    empty.mkdir()

    try:
        install_target(target, build_console(), empty)
    except SetupError:
        pass
    else:
        raise AssertionError("expected SetupError for a source without SKILL.md")
    assert not target.install_dir.exists()
