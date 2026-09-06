"""ZCode harness support: the z.ai MCP suite, wired into ZCode's config.

z.ai serves four MCP servers to coding-plan users: web search, web reader,
and zread as remote streamable-HTTP endpoints (Bearer auth; a legacy SSE
transport exists at the ``/sse`` suffix for old clients), and vision as a
local stdio server whose ``Z_AI_MODE`` selects the region. Both the
international (api.z.ai) and the China-domestic (open.bigmodel.cn) bases
are carried. Keys are env-var indirection only: the generated config
references ``Z_AI_API_KEY`` by name, never a literal key, so the file
stays committable.

References: https://docs.z.ai/devpack/mcp and
https://docs.bigmodel.cn/cn/coding-plan/mcp
"""

from __future__ import annotations

import json
import pathlib
import shutil

REGIONS = {"intl": "https://api.z.ai", "zh": "https://open.bigmodel.cn"}
MANAGED_PREFIX = "zai-"
API_KEY_ENV = "Z_AI_API_KEY"


class ZcodeConfigError(RuntimeError):
    """Raised when the ZCode config cannot be generated or merged."""


def server_entries(region: str) -> dict[str, dict]:
    """The z.ai MCP server entries for a region, env-indirected throughout."""
    if region not in REGIONS:
        raise ZcodeConfigError(f"unknown z.ai region {region!r} (expected one of {', '.join(REGIONS)})")
    base = REGIONS[region]
    auth_header = {"Authorization": f"Bearer ${{{API_KEY_ENV}}}"}
    return {
        "zai-web-search": {"url": f"{base}/api/mcp/web_search_prime/mcp", "headers": dict(auth_header)},
        "zai-web-reader": {"url": f"{base}/api/mcp/web_reader/mcp", "headers": dict(auth_header)},
        "zai-zread": {"url": f"{base}/api/mcp/zread/mcp", "headers": dict(auth_header)},
        "zai-vision": {
            "command": "npx",
            "args": ["-y", "@z_ai/mcp-server"],
            "env": {API_KEY_ENV: f"${{{API_KEY_ENV}}}", "Z_AI_MODE": "ZAI" if region == "intl" else "ZHIPU"},
        },
    }


def merge_config(existing: dict, servers: dict[str, dict]) -> dict:
    """Merge managed server entries into a config, preserving everything else."""
    merged = dict(existing)
    mcp = dict(merged.get("mcp") or {})
    existing_servers = dict(mcp.get("servers") or {})
    existing_servers.update(servers)
    mcp["servers"] = existing_servers
    merged["mcp"] = mcp
    return merged


def required_exports() -> list[str]:
    """The shell exports the generated config needs from the user."""
    return [f"export {API_KEY_ENV}=<your coding-plan key>"]


def write_config(path: pathlib.Path, region: str, *, force: bool = False) -> list[str]:
    """Write the managed server entries into a ZCode config file.

    Unknown keys are preserved and a backup (``<path>.bak``) is written
    before any overwrite. A managed entry that already exists with
    different content is refused unless ``force``; an identical entry is
    accepted (the write is idempotent). Returns the required exports.
    """
    path = pathlib.Path(path)
    entries = server_entries(region)

    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise ZcodeConfigError(f"{path}: invalid JSON ({exc})") from exc
        if not isinstance(existing, dict):
            raise ZcodeConfigError(f"{path}: expected an object at top level")
        current = dict((existing.get("mcp") or {}).get("servers") or {})
        for name, entry in entries.items():
            if name in current and current[name] != entry and not force:
                raise ZcodeConfigError(
                    f"refusing to overwrite {name} in {path} (it differs from the generated entry); pass --force to replace it"
                )
        shutil.copyfile(path, path.with_name(path.name + ".bak"))

    merged = merge_config(existing, entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return required_exports()
