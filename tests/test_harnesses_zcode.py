"""Tests for the z.ai MCP wiring (goldens for both regions; no network)."""

from __future__ import annotations

import json
import pathlib

import pytest

from weco.harnesses.zcode import REGIONS, ZcodeConfigError, required_exports, server_entries, write_config


def test_intl_region_golden():
    assert server_entries("intl") == {
        "zai-web-search": {
            "url": "https://api.z.ai/api/mcp/web_search_prime/mcp",
            "headers": {"Authorization": "Bearer ${Z_AI_API_KEY}"},
        },
        "zai-web-reader": {
            "url": "https://api.z.ai/api/mcp/web_reader/mcp",
            "headers": {"Authorization": "Bearer ${Z_AI_API_KEY}"},
        },
        "zai-zread": {"url": "https://api.z.ai/api/mcp/zread/mcp", "headers": {"Authorization": "Bearer ${Z_AI_API_KEY}"}},
        "zai-vision": {
            "command": "npx",
            "args": ["-y", "@z_ai/mcp-server"],
            "env": {"Z_AI_API_KEY": "${Z_AI_API_KEY}", "Z_AI_MODE": "ZAI"},
        },
    }


def test_zh_region_golden_selects_domestic_base_and_mode():
    entries = server_entries("zh")
    assert entries["zai-web-search"]["url"] == "https://open.bigmodel.cn/api/mcp/web_search_prime/mcp"
    assert entries["zai-web-reader"]["url"] == "https://open.bigmodel.cn/api/mcp/web_reader/mcp"
    assert entries["zai-zread"]["url"] == "https://open.bigmodel.cn/api/mcp/zread/mcp"
    assert entries["zai-vision"]["env"]["Z_AI_MODE"] == "ZHIPU"


def test_unknown_region_refused():
    with pytest.raises(ZcodeConfigError):
        server_entries("eu")


def test_no_literal_secret_in_entries():
    blob = json.dumps(server_entries("intl"))
    assert "Bearer ${Z_AI_API_KEY}" in blob
    assert "sk-" not in blob


def test_write_config_fresh(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    exports = write_config(pathlib.Path(".zcode/config.json"), "intl")
    config = json.loads(pathlib.Path(".zcode/config.json").read_text(encoding="utf-8"))
    assert config["mcp"]["servers"]["zai-web-search"]["url"].startswith("https://api.z.ai/api/mcp/")
    assert not pathlib.Path(".zcode/config.json.bak").exists()
    assert exports == ["export Z_AI_API_KEY=<your coding-plan key>"]


def test_write_config_preserves_unknown_keys_and_backs_up(tmp_path):
    path = tmp_path / "config.json"
    existing = {"model": "glm-4.7", "mcp": {"servers": {"mine": {"command": "my-server"}}}}
    path.write_text(json.dumps(existing), encoding="utf-8")

    write_config(path, "zh")

    merged = json.loads(path.read_text(encoding="utf-8"))
    assert merged["model"] == "glm-4.7"
    assert merged["mcp"]["servers"]["mine"] == {"command": "my-server"}
    assert "zai-vision" in merged["mcp"]["servers"]
    backup = json.loads(path.with_name("config.json.bak").read_text(encoding="utf-8"))
    assert backup == existing


def test_write_config_is_idempotent_for_identical_entries(tmp_path):
    path = tmp_path / "config.json"
    write_config(path, "intl")
    first = path.read_text(encoding="utf-8")
    write_config(path, "intl")
    assert path.read_text(encoding="utf-8") == first


def test_write_config_refuses_differing_managed_entry_without_force(tmp_path):
    path = tmp_path / "config.json"
    write_config(path, "intl")
    config = json.loads(path.read_text(encoding="utf-8"))
    config["mcp"]["servers"]["zai-web-search"]["url"] = "https://elsewhere/mcp"
    path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ZcodeConfigError, match="refusing to overwrite zai-web-search"):
        write_config(path, "intl")

    write_config(path, "intl", force=True)
    merged = json.loads(path.read_text(encoding="utf-8"))
    assert merged["mcp"]["servers"]["zai-web-search"]["url"].startswith("https://api.z.ai/api/mcp/")


def test_write_config_rejects_invalid_existing_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ZcodeConfigError, match="invalid JSON"):
        write_config(path, "intl")


def test_regions_cover_both_endpoints():
    assert REGIONS == {"intl": "https://api.z.ai", "zh": "https://open.bigmodel.cn"}
    assert required_exports() == ["export Z_AI_API_KEY=<your coding-plan key>"]
