"""`weco start codex` — spawn Codex headlessly and stream its events.

Codex resolves its own authentication, so this bridge adds no billing and
requires no Weco login: it runs ``codex exec --json`` and re-emits each
JSON event as one normalized JSONL line on stdout, exactly the opencode
bridge's contract. The normalization is deliberately thin; the event
shapes are pinned by test fixtures rather than a live Codex, and
``WECO_TEST_CODEX_BIN`` can point at a fake binary for live-style runs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import IO, Any, Mapping


def normalize_event(raw: Any) -> dict:
    """Normalize one Codex JSON event into a sparse JSONL envelope.

    Known kinds get flattened conveniences (thread and item ids, text);
    every event carries its kind, and unknown kinds pass through under
    ``data``.
    """
    if not isinstance(raw, Mapping):
        return {"type": "codex.unknown", "data": raw}
    kind = raw.get("type")
    envelope: dict[str, Any] = {"type": f"codex.{kind}" if kind else "codex.event"}
    for source, target in (("thread_id", "thread_id"), ("id", "item_id"), ("call_id", "call_id")):
        if raw.get(source):
            envelope[target] = raw[source]
    item = raw.get("item")
    if isinstance(item, Mapping):
        if item.get("item_type"):
            envelope["item_type"] = item["item_type"]
        if item.get("text"):
            envelope["text"] = item["text"]
    if raw.get("text") and "text" not in envelope:
        envelope["text"] = raw["text"]
    if kind not in (None, "item.completed", "item.started", "thread.started"):
        envelope["data"] = raw
    return envelope


def run_codex_bridge(*, prompt: str | None, forwarded_args: list[str], console, stdout: IO[str] | None = None) -> int:
    """Run ``codex exec --json`` and stream normalized events as JSONL."""
    argv = ["codex", "exec", "--json"]
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
