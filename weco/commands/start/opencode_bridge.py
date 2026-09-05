"""`weco start opencode` — spawn opencode headlessly and stream its events.

opencode resolves its own providers, endpoints, and credentials from its
configuration, so this bridge adds no billing and requires no Weco login:
it runs ``opencode run --format json`` and re-emits each JSON event as one
normalized JSONL line on stdout. The normalization is deliberately thin
(familiar top-level fields, unknown kinds passed through); translating to
the dashboard's envelope shapes belongs to the dashboard integration, not
the minimal bridge.

The event shapes are pinned by test fixtures rather than a live opencode;
``WECO_TEST_OPENCODE_BIN`` can point at a fake binary for live-style runs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import IO, Any, Mapping


def normalize_event(raw: Any) -> dict:
    """Normalize one opencode JSON event into a sparse JSONL envelope.

    Known kinds get flattened conveniences (session id, role, text); every
    event carries its kind, and unknown kinds pass through under ``data``.
    """
    if not isinstance(raw, Mapping):
        return {"type": "opencode.unknown", "data": raw}
    kind = raw.get("type")
    envelope: dict[str, Any] = {"type": f"opencode.{kind}" if kind else "opencode.event"}
    session_id = raw.get("sessionID") or raw.get("session_id")
    if session_id:
        envelope["session_id"] = session_id
    message = raw.get("message")
    if isinstance(message, Mapping):
        if message.get("role"):
            envelope["role"] = message["role"]
        parts = message.get("parts")
        if isinstance(parts, list):
            text = "".join(part.get("text", "") for part in parts if isinstance(part, Mapping) and part.get("type") == "text")
            if text:
                envelope["text"] = text
    part = raw.get("part")
    if isinstance(part, Mapping) and part.get("type") == "text" and part.get("text"):
        envelope["text"] = part["text"]
    if kind not in (None, "message.updated", "message.part.updated", "session.id"):
        envelope["data"] = raw
    return envelope


def run_opencode_bridge(
    *, prompt: str | None, agent: str | None, forwarded_args: list[str], console, stdout: IO[str] | None = None
) -> int:
    """Run ``opencode run --format json`` and stream normalized events as JSONL."""
    argv = ["opencode", "run", "--format", "json"]
    if agent:
        argv += ["--agent", agent]
    argv += forwarded_args
    if prompt:
        argv.append(prompt)

    out = stdout or sys.stdout
    console.print(f"[dim]$ {' '.join(argv)}[/]")
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=None, text=True, bufsize=1)
    assert process.stdout is not None
    for line in process.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except ValueError:
            # Non-JSON chatter (logs, banners): pass it through untouched.
            out.write(line + "\n")
            continue
        out.write(json.dumps(normalize_event(raw), ensure_ascii=False) + "\n")
        out.flush()
    process.stdout.close()
    return process.wait()
