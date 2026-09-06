"""Tests for the Claude Code harness env routing (pure, no SDK, no network)."""

from __future__ import annotations

from weco.harnesses.claude_code import is_weco_proxy_base, sanitize_claude_env, weco_proxy_env

WECO_BASE = "https://api.weco.ai/v1"


def test_proxy_detection():
    assert is_weco_proxy_base(f"{WECO_BASE}/llm/anthropic/s/abc", WECO_BASE)
    assert is_weco_proxy_base(WECO_BASE, WECO_BASE)
    assert not is_weco_proxy_base("https://api.anthropic.com", WECO_BASE)
    assert not is_weco_proxy_base("", WECO_BASE)
    assert not is_weco_proxy_base(WECO_BASE, None)


def test_proxy_env_encodes_session_in_the_path():
    env = weco_proxy_env("weco-key", WECO_BASE, "sess-1")
    assert env == {"ANTHROPIC_BASE_URL": f"{WECO_BASE}/llm/anthropic/s/sess-1", "ANTHROPIC_API_KEY": "weco-key"}
    assert weco_proxy_env("weco-key", WECO_BASE, None)["ANTHROPIC_BASE_URL"] == f"{WECO_BASE}/llm/anthropic"


def test_sanitize_drops_proxied_leftovers():
    env = {"PATH": "/bin", "ANTHROPIC_BASE_URL": f"{WECO_BASE}/llm/anthropic/s/old", "ANTHROPIC_API_KEY": "weco-stale"}
    cleaned = sanitize_claude_env(env, WECO_BASE)
    assert cleaned == {"PATH": "/bin"}


def test_sanitize_keeps_genuine_byo_setup():
    env = {"PATH": "/bin", "ANTHROPIC_BASE_URL": "https://my-gateway.example", "ANTHROPIC_API_KEY": "sk-ant-real"}
    cleaned = sanitize_claude_env(env, WECO_BASE)
    assert cleaned == env


def test_sdk_env_delegates_without_changing_behavior(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from weco.commands.start.sdk_config import build_sdk_env

    proxied = build_sdk_env(billing="weco", api_key="weco-k", weco_api_base=WECO_BASE, session_id="s1")
    assert proxied["ANTHROPIC_BASE_URL"] == f"{WECO_BASE}/llm/anthropic/s/s1"
    assert proxied["ANTHROPIC_API_KEY"] == "weco-k"
    assert proxied["WECO_CC_SESSION_ID"] == "s1"

    direct = build_sdk_env(billing="claude", api_key="", weco_api_base=WECO_BASE, session_id=None)
    assert "ANTHROPIC_BASE_URL" not in direct
    assert "ANTHROPIC_API_KEY" not in direct
