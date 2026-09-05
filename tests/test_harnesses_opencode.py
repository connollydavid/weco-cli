"""Tests for the opencode configuration reader (no network, no real HOME)."""

from __future__ import annotations

import json
import pathlib
import subprocess

import pytest

from weco.harnesses import HarnessConfigError
from weco.harnesses.opencode import (
    load_auth,
    load_opencode_config,
    resolve_provider_endpoint,
    strip_jsonc,
    substitute,
)

EMPTY_ENV = {"HOME": "/nonexistent-weco-home", "PATH": "/usr/bin:/bin"}


def test_strip_jsonc_removes_comments_outside_strings() -> None:
    text = '{\n  // a line comment\n  "url": "http://example.com", /* block\n  comment */ "k": "v//x",\n}\n'
    parsed = json.loads(strip_jsonc(text))
    assert parsed == {"url": "http://example.com", "k": "v//x"}


def test_strip_jsonc_preserves_escaped_quotes() -> None:
    text = '{"k": "say \\"hi\\" // not a comment"}'
    parsed = json.loads(strip_jsonc(text))
    assert parsed["k"] == 'say "hi" // not a comment'


def _sandbox(tmp_path: pathlib.Path) -> tuple[pathlib.Path, dict[str, str]]:
    home = tmp_path / "home"
    (home / ".config" / "opencode").mkdir(parents=True)
    (home / ".local" / "share" / "opencode").mkdir(parents=True)
    env = {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        "PATH": "/usr/bin:/bin",
    }
    return home, env


def test_chain_merges_per_key_with_later_sources_overriding(tmp_path) -> None:
    home, env = _sandbox(tmp_path)
    global_config = home / ".config" / "opencode" / "opencode.json"
    global_config.write_text(
        json.dumps({"model": "anthropic/claude", "provider": {"custom": {"options": {"baseURL": "https://global"}}}}),
        encoding="utf-8",
    )
    override = tmp_path / "override.jsonc"
    override.write_text(
        "{\n  // jsonc works everywhere in the chain\n  \"model\": \"openai/gpt\",\n  \"small_model\": \"openai/gpt-mini\",\n}",
        encoding="utf-8",
    )
    env["OPENCODE_CONFIG"] = str(override)

    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (project / "opencode.json").write_text(
        json.dumps({"provider": {"custom": {"options": {"baseURL": "https://project", "apiKey": "{env:CUSTOM_KEY}"}}}}),
        encoding="utf-8",
    )
    nested = project / "nested" / "deeper"
    nested.mkdir(parents=True)

    config = load_opencode_config(start_dir=nested, env=env)

    assert config["model"] == "openai/gpt"  # OPENCODE_CONFIG overrides global
    assert config["small_model"] == "openai/gpt-mini"  # non-conflicting keys survive
    assert config["provider"]["custom"]["options"]["baseURL"] == "https://project"  # project overrides global
    env["CUSTOM_KEY"] = "sk-custom"
    endpoint = resolve_provider_endpoint(config, "custom", env=env)
    assert endpoint.base_url == "https://project"
    assert endpoint.api_key == "sk-custom"
    assert endpoint.key_source == "config"


def test_inline_content_is_highest_precedence(tmp_path) -> None:
    home, env = _sandbox(tmp_path)
    (home / ".config" / "opencode" / "opencode.json").write_text(json.dumps({"model": "a/b"}), encoding="utf-8")
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps({"model": "c/d"})
    config = load_opencode_config(start_dir=tmp_path, env=env)
    assert config["model"] == "c/d"


def test_project_config_stops_at_git_root(tmp_path) -> None:
    outer = tmp_path / "outer"
    outer.mkdir()
    subprocess.run(["git", "init", "-q", str(outer)], check=True)
    (outer / "opencode.json").write_text(json.dumps({"note": "outer"}), encoding="utf-8")
    inner = outer / "inner"
    inner.mkdir()
    (inner / "opencode.json").write_text(json.dumps({"note": "inner"}), encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()

    inside = load_opencode_config(start_dir=inner, env=EMPTY_ENV)
    assert inside["note"] == "inner"
    above = load_opencode_config(start_dir=outside, env=EMPTY_ENV)
    assert "note" not in above


def test_substitute_env_and_file(tmp_path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("file-key\n", encoding="utf-8")
    value = {"key": "{env:K}", "from_file": "{file:%s}" % secret, "list": ["{env:K}"], "n": 5}
    resolved = substitute(value, env={"K": "env-key"})
    assert resolved == {"key": "env-key", "from_file": "file-key", "list": ["env-key"], "n": 5}


def test_substitute_unset_env_raises() -> None:
    with pytest.raises(HarnessConfigError):
        substitute("{env:MISSING}", env={})


def test_auth_from_data_home(tmp_path) -> None:
    home, env = _sandbox(tmp_path)
    (home / ".local" / "share" / "opencode" / "auth.json").write_text(
        json.dumps({"anthropic": {"type": "api", "key": "sk-ant"}}), encoding="utf-8"
    )
    assert load_auth(env=env) == {"anthropic": {"type": "api", "key": "sk-ant"}}


def test_auth_inline_override(tmp_path) -> None:
    home, env = _sandbox(tmp_path)
    (home / ".local" / "share" / "opencode" / "auth.json").write_text(json.dumps({"a": {"type": "api", "key": "1"}}), encoding="utf-8")
    env["OPENCODE_AUTH_CONTENT"] = json.dumps({"b": {"type": "api", "key": "2"}})
    assert load_auth(env=env) == {"b": {"type": "api", "key": "2"}}


def test_endpoint_falls_back_to_catalog_then_auth_key(tmp_path) -> None:
    home, env = _sandbox(tmp_path)
    auth = {"anthropic": {"type": "api", "key": "sk-ant"}}
    catalog = {"anthropic": "https://api.anthropic.com"}

    from_config = resolve_provider_endpoint(
        {"provider": {"anthropic": {"options": {"baseURL": "https://proxy"}}}}, "anthropic", auth=auth, catalog=catalog, env=env
    )
    assert from_config.base_url == "https://proxy"
    assert from_config.key_source == "auth"

    fallback = resolve_provider_endpoint({}, "anthropic", auth=auth, catalog=catalog, env=env)
    assert fallback.base_url == "https://api.anthropic.com"
    assert fallback.api_key == "sk-ant"
    assert fallback.key_source == "auth"

    nothing = resolve_provider_endpoint({}, "anthropic", auth={}, catalog=None, env=env)
    assert nothing.base_url is None
    assert nothing.api_key is None
    assert nothing.key_source == "none"
