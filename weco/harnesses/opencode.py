"""Read opencode's configuration and credentials.

opencode merges a chain of config sources, each later source overriding
per key: the global config, an ``OPENCODE_CONFIG`` override file, the
project config (discovered upward to the git root), and
``OPENCODE_CONFIG_CONTENT`` inline. String values may reference the
environment and files with ``{env:NAME}`` and ``{file:path}`` placeholders.
Authentication lives in ``auth.json`` keyed by provider id.

Reference: https://opencode.ai/docs/config/
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import pathlib
import re

_PLACEHOLDER = re.compile(r"\{(env|file):([^}]+)\}")


class HarnessConfigError(RuntimeError):
    """Raised when harness configuration cannot be read or resolved."""


def strip_jsonc(text: str) -> str:
    """Strip comments and trailing commas (JSONC), respecting strings."""

    def drop_trailing_comma(out: list[str]) -> None:
        while out and out[-1].isspace():
            out.pop()
        if out and out[-1] == ",":
            out.pop()

    out: list[str] = []
    i = 0
    in_string = False
    while i < len(text):
        ch = text[i]
        nxt = text[i + 1] if i + 1 < len(text) else ""
        if in_string:
            out.append(ch)
            if ch == "\\" and nxt:
                out.append(nxt)
                i += 2
                continue
            if ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch in "}]":
            drop_trailing_comma(out)
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_config_file(path: pathlib.Path) -> dict:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return {}
    try:
        data = json.loads(strip_jsonc(text))
    except ValueError as exc:
        raise HarnessConfigError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise HarnessConfigError(f"expected an object at top level of {path}")
    return data


def _global_config_path(env: dict[str, str]) -> pathlib.Path:
    config_home = env.get("XDG_CONFIG_HOME") or os.path.join(env.get("HOME") or "~", ".config")
    return pathlib.Path(config_home).expanduser() / "opencode" / "opencode.json"


def _find_project_config(start_dir: pathlib.Path | None) -> pathlib.Path | None:
    """The nearest opencode.json[c] from start_dir up to the git root."""
    directory = (start_dir or pathlib.Path.cwd()).resolve()
    boundaries: list[pathlib.Path] = []
    for candidate in [directory, *directory.parents]:
        boundaries.append(candidate)
        if (candidate / ".git").exists():
            break
    for candidate in boundaries:
        for name in ("opencode.jsonc", "opencode.json"):
            path = candidate / name
            if path.is_file():
                return path
    return None


def load_opencode_config(
    *,
    start_dir: pathlib.Path | None = None,
    env: dict[str, str] | None = None,
) -> dict:
    """Load opencode's merged config chain (values raw, placeholders intact).

    Order, later overriding per key: global config, ``OPENCODE_CONFIG``
    file, project config (upward to the git root), ``OPENCODE_CONFIG_CONTENT``.
    """
    env = dict(env if env is not None else os.environ)
    config: dict = {}
    config = _deep_merge(config, _read_config_file(_global_config_path(env)))
    if env.get("OPENCODE_CONFIG"):
        config = _deep_merge(config, _read_config_file(pathlib.Path(env["OPENCODE_CONFIG"]).expanduser()))
    project = _find_project_config(start_dir)
    if project is not None:
        config = _deep_merge(config, _read_config_file(project))
    if env.get("OPENCODE_CONFIG_CONTENT"):
        try:
            inline = json.loads(strip_jsonc(env["OPENCODE_CONFIG_CONTENT"]))
        except ValueError as exc:
            raise HarnessConfigError(f"invalid OPENCODE_CONFIG_CONTENT: {exc}") from exc
        if not isinstance(inline, dict):
            raise HarnessConfigError("OPENCODE_CONFIG_CONTENT must be an object")
        config = _deep_merge(config, inline)
    return config


def substitute(value, *, env: dict[str, str] | None = None):
    """Resolve ``{env:NAME}`` and ``{file:path}`` placeholders in a value.

    Recurses into lists and dicts; other types pass through. An unset
    environment variable or an unreadable file raises
    :class:`HarnessConfigError`.
    """
    env = dict(env if env is not None else os.environ)

    def replace(match: re.Match) -> str:
        kind, ref = match.group(1), match.group(2).strip()
        if kind == "env":
            if ref not in env:
                raise HarnessConfigError(f"environment variable {ref} is not set")
            return env[ref]
        try:
            return pathlib.Path(ref).expanduser().read_text(encoding="utf-8").rstrip("\n")
        except OSError as exc:
            raise HarnessConfigError(f"cannot read {ref}: {exc}") from exc

    if isinstance(value, str):
        return _PLACEHOLDER.sub(replace, value)
    if isinstance(value, list):
        return [substitute(item, env=env) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, env=env) for key, item in value.items()}
    return value


def load_auth(*, env: dict[str, str] | None = None) -> dict:
    """Load opencode's auth.json (provider id to credential object)."""
    env = dict(env if env is not None else os.environ)
    if env.get("OPENCODE_AUTH_CONTENT"):
        try:
            data = json.loads(env["OPENCODE_AUTH_CONTENT"])
        except ValueError as exc:
            raise HarnessConfigError(f"invalid OPENCODE_AUTH_CONTENT: {exc}") from exc
        return data if isinstance(data, dict) else {}
    data_home = env.get("XDG_DATA_HOME") or os.path.join(env.get("HOME") or "~", ".local", "share")
    path = pathlib.Path(data_home).expanduser() / "opencode" / "auth.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise HarnessConfigError(f"invalid JSON in {path}: {exc}") from exc
    return data if isinstance(data, dict) else {}


@dataclass(frozen=True)
class ProviderEndpoint:
    """A resolved provider endpoint: where to talk, how to authenticate."""

    provider_id: str
    base_url: str | None
    api_key: str | None
    key_source: str  # "config" | "auth" | "none"


def resolve_provider_endpoint(
    config: dict,
    provider_id: str,
    *,
    auth: dict | None = None,
    catalog: dict[str, str] | None = None,
    env: dict[str, str] | None = None,
) -> ProviderEndpoint:
    """Resolve a provider's endpoint from config, auth, and a caller-supplied catalog.

    Precedence for the base URL: the provider's ``options.baseURL`` in the
    merged config, then the caller's catalog (for example a models.dev
    snapshot). For the key: ``options.apiKey``, then an ``api``-type entry
    in auth.json.
    """
    env = dict(env if env is not None else os.environ)
    provider = config.get("provider", {}).get(provider_id, {})
    if not isinstance(provider, dict):
        raise HarnessConfigError(f"provider {provider_id} must be an object")
    options = provider.get("options", {})
    if not isinstance(options, dict):
        raise HarnessConfigError(f"provider {provider_id} options must be an object")

    base_url: str | None = None
    if options.get("baseURL"):
        base_url = substitute(options["baseURL"], env=env)
    elif (catalog or {}).get(provider_id):
        base_url = catalog[provider_id]

    api_key: str | None = None
    key_source = "none"
    if options.get("apiKey"):
        api_key = substitute(options["apiKey"], env=env)
        key_source = "config"
    else:
        entry = (auth or {}).get(provider_id)
        if isinstance(entry, dict) and entry.get("type") == "api" and entry.get("key"):
            api_key = entry["key"]
            key_source = "auth"

    return ProviderEndpoint(provider_id=provider_id, base_url=base_url, api_key=api_key, key_source=key_source)
