"""Claude Code harness configuration: environment and credential routing.

Claude Code's own configuration surface for model routing is its process
environment plus the local OAuth store written by ``claude login``:
``ANTHROPIC_BASE_URL`` selects an Anthropic-compatible gateway and
``ANTHROPIC_API_KEY`` a BYO key. This module owns the routing rules the
bridge needs on top of that: pointing the SDK at Weco's LLM proxy when
billing routes through Weco, and sanitizing an inherited environment so a
previous proxied session cannot silently re-route a directly-billed one.
"""

from __future__ import annotations


def is_weco_proxy_base(base_url: str | None, weco_api_base: str | None) -> bool:
    """True when an ``ANTHROPIC_BASE_URL`` points at Weco's proxy."""
    marker = (weco_api_base or "").rstrip("/")
    return bool(marker) and bool(base_url) and base_url.startswith(marker)


def weco_proxy_env(api_key: str, weco_api_base: str, session_id: str | None) -> dict[str, str]:
    """The env overrides that route Anthropic traffic through Weco's proxy.

    The session id rides in the URL path (not a header) because the
    Anthropic SDK ignores header env vars; the proxy broadcasts
    ``credits_updated`` to the channel the id names.
    """
    base = weco_api_base.rstrip("/")
    if session_id:
        return {"ANTHROPIC_BASE_URL": f"{base}/llm/anthropic/s/{session_id}", "ANTHROPIC_API_KEY": api_key}
    return {"ANTHROPIC_BASE_URL": f"{base}/llm/anthropic", "ANTHROPIC_API_KEY": api_key}


def sanitize_claude_env(env: dict[str, str], weco_api_base: str | None) -> dict[str, str]:
    """Drop proxied leftovers so a direct (claude-billed) session is direct.

    A previous ``--billing weco`` run (or a shell override) can leave
    ``ANTHROPIC_BASE_URL`` pointing at Weco's proxy and a ``weco-`` API
    key in the environment; both would silently re-route a session the
    user asked to bill to Claude. Genuine BYO setup — a real ``sk-ant-``
    key, a non-Weco gateway base — passes through untouched.
    """
    cleaned = dict(env)
    if is_weco_proxy_base(cleaned.get("ANTHROPIC_BASE_URL", ""), weco_api_base):
        cleaned.pop("ANTHROPIC_BASE_URL", None)
    if cleaned.get("ANTHROPIC_API_KEY", "").startswith("weco-"):
        cleaned.pop("ANTHROPIC_API_KEY", None)
    return cleaned
