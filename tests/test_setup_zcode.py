"""Tests for the zcode setup target, its MCP wiring, and placement."""

from __future__ import annotations

import argparse
import dataclasses
import io
import json
import pathlib

from rich.console import Console

from weco.cli import configure_setup_parser
from weco.commands.setup import handle_setup_command
from weco.commands.setup import install as setup_install
from weco.commands.setup.install import install_target
from weco.commands.setup.targets import SETUP_TARGET_BY_NAME, SetupTarget


def build_setup_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    configure_setup_parser(subparsers.add_parser("setup"))
    return parser


def build_console() -> Console:
    return Console(file=io.StringIO(), force_terminal=False, color_system=None)


def make_skill_source(root: pathlib.Path) -> pathlib.Path:
    source = root / "skill-source"
    source.mkdir()
    (source / "SKILL.md").write_text("---\nname: weco\ndescription: test\n---\n", encoding="utf-8")
    return source


def test_zcode_target_registered():
    target = SETUP_TARGET_BY_NAME["zcode"]
    assert target.install_dir == pathlib.Path.home() / ".zcode" / "skills" / "weco"
    assert target.extra_files == ()


def test_setup_parser_accepts_zcode_flags():
    parser = build_setup_parser()
    args = parser.parse_args(["setup", "zcode", "--zai-endpoint", "zh", "--zcode-config", "cfg.json", "--force"])
    assert args.tool == "zcode"
    assert args.zai_endpoint == "zh"
    assert args.zcode_config == "cfg.json"
    assert args.force is True
    defaults = parser.parse_args(["setup", "zcode"])
    assert defaults.zai_endpoint == "intl"
    assert defaults.force is False


def test_install_target_places_zcode_layout(tmp_path, monkeypatch):
    home = tmp_path / "home"
    target = SetupTarget(name="zcode-test", label="zcode-test", help_text="", install_dir=home / ".zcode" / "skills" / "weco")
    monkeypatch.setattr(setup_install, "_ALLOWED_SKILL_PARENTS", {target.install_parent})
    source = make_skill_source(tmp_path)

    install_target(target, build_console(), source)
    assert (target.install_dir / "SKILL.md").is_file()


def test_setup_zcode_wires_mcp_after_install(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    source = make_skill_source(tmp_path)

    # Install into a sandboxed target dir (the registry paths resolve at
    # import against the real home, so replace the entry in place).
    sandboxed = dataclasses.replace(
        SETUP_TARGET_BY_NAME["zcode"], install_dir=tmp_path / "home" / ".zcode" / "skills" / "weco"
    )
    monkeypatch.setattr("weco.commands.setup.SETUP_TARGET_BY_NAME", {"zcode": sandboxed})
    monkeypatch.setattr(setup_install, "_ALLOWED_SKILL_PARENTS", {sandboxed.install_parent})

    args = argparse.Namespace(
        command="setup", tool="zcode", local=str(source), zai_endpoint="zh", zcode_config=".zcode/config.json", force=False
    )
    handle_setup_command(args, build_console())

    installed = tmp_path / "home" / ".zcode" / "skills" / "weco" / "SKILL.md"
    config = json.loads((tmp_path / ".zcode" / "config.json").read_text(encoding="utf-8"))
    assert installed.is_file()
    assert config["mcp"]["servers"]["zai-web-search"]["url"].startswith("https://open.bigmodel.cn/api/mcp/")
    assert config["mcp"]["servers"]["zai-vision"]["env"]["Z_AI_MODE"] == "ZHIPU"
