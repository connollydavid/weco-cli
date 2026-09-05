"""Local-first run tracking for ``weco observe`` in local mode.

Runs and steps are recorded under ``.weco/observe/`` as append-only JSONL:
one ``runs.jsonl`` line per run, one ``steps.jsonl`` per run directory.
Nothing is posted anywhere; ``list`` and ``show`` read the files back.
The record shapes mirror what the cloud observe API carries (metric, goal,
per-step metrics and code snapshots) so a local history is legible on its
own and exportable later.
"""

from __future__ import annotations

import json
import pathlib
import uuid


class LocalStoreError(RuntimeError):
    """Raised when the local observe store cannot satisfy a request."""


class LocalStore:
    """Append-only run/step store rooted at ``<root>/.weco/observe``."""

    def __init__(self, root: pathlib.Path):
        self.root = pathlib.Path(root)
        self.observe_dir = self.root / ".weco" / "observe"
        self.runs_index = self.observe_dir / "runs.jsonl"

    # ── runs ──────────────────────────────────────────────────────

    def init_run(
        self,
        *,
        name: str | None,
        metric: str,
        maximize: bool,
        source_code: dict[str, str],
        additional_instructions: str | None,
    ) -> str:
        run_id = uuid.uuid4().hex
        record = {
            "run_id": run_id,
            "name": name,
            "metric": metric,
            "goal": "maximize" if maximize else "minimize",
            "sources": sorted(source_code),
            "additional_instructions": additional_instructions,
            "created_at": _utc_now(),
        }
        run_dir = self._run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        _append_jsonl(self.runs_index, record)
        (run_dir / "run.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        _append_jsonl(run_dir / "sources.jsonl", [{"path": p, "code": code} for p, code in source_code.items()])
        return run_id

    def list_runs(self) -> list[dict]:
        if not self.runs_index.is_file():
            return []
        records = [json.loads(line) for line in self.runs_index.read_text(encoding="utf-8").splitlines() if line.strip()]
        for record in records:
            record["steps"] = self._count_steps(record.get("run_id", ""))
        return records

    def show_run(self, run_id: str) -> dict:
        run_dir = self._run_dir(run_id)
        run_file = run_dir / "run.json"
        if not run_file.is_file():
            raise LocalStoreError(f"no local run {run_id} under {self.observe_dir}")
        record = json.loads(run_file.read_text(encoding="utf-8"))
        record["steps"] = self._read_steps(run_id)
        return record

    # ── steps ─────────────────────────────────────────────────────

    def log_step(
        self,
        *,
        run_id: str,
        step: int,
        status: str,
        description: str | None,
        metrics: dict,
        code: dict[str, str] | None,
        parent_step: int | None,
    ) -> None:
        run_dir = self._run_dir(run_id)
        if not (run_dir / "run.json").is_file():
            raise LocalStoreError(f"no local run {run_id} under {self.observe_dir}")
        record = {
            "step": step,
            "status": status,
            "description": description,
            "metrics": metrics,
            "parent_step": parent_step,
            "logged_at": _utc_now(),
        }
        _append_jsonl(run_dir / "steps.jsonl", record)
        if code:
            _append_jsonl(run_dir / "snapshots.jsonl", {"step": step, "files": code})

    # ── internals ─────────────────────────────────────────────────

    def _run_dir(self, run_id: str) -> pathlib.Path:
        return self.observe_dir / "runs" / run_id

    def _steps_file(self, run_id: str) -> pathlib.Path:
        return self._run_dir(run_id) / "steps.jsonl"

    def _read_steps(self, run_id: str) -> list[dict]:
        path = self._steps_file(run_id)
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _count_steps(self, run_id: str) -> int:
        return len(self._read_steps(run_id))


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: pathlib.Path, records) -> None:
    if isinstance(records, dict):
        records = [records]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
