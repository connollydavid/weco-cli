"""Campaign-resilience tests for the local loop: resume, eval timeout,
and harness-failure retry/abort (feature/local-campaign-resilience)."""

from __future__ import annotations

import json
import subprocess

import pytest

from weco.local.loop import local_optimize
from weco.commands.start.opencode_bridge import _resolve_opencode


class FakeResult:
    def __init__(self, text: str):
        self.stdout = text
        self.stderr = ""


def _runner_factory(outputs):
    """A subprocess.run stand-in that yields canned eval outputs."""
    seq = list(outputs)

    def run(*args, **kwargs):
        return FakeResult(seq.pop(0))

    return run


def _write_steps(workdir, records):
    d = workdir / ".weco" / "local-loop"
    d.mkdir(parents=True, exist_ok=True)
    with (d / "steps.jsonl").open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def test_resume_skips_recorded_steps_and_carries_best(tmp_path):
    _write_steps(
        tmp_path,
        [
            {"step": 0, "value": 1.0, "improved_best": True, "output_tail": ""},
            {"step": 1, "value": 4.0, "improved_best": True, "output_tail": ""},
        ],
    )
    seen = []

    def harness(step, current_best):
        seen.append((step, current_best))

    summary = local_optimize(
        harness_step=harness,
        eval_command="true",
        metric="score",
        maximize=True,
        steps=4,
        workdir=tmp_path,
        runner=_runner_factory(["score: 5.0\n", "score: 4.5\n"]),
        resume=True,
    )
    assert [s for s, _ in seen] == [2, 3]
    # the best from history (4.0) is injected into the first new prompt
    assert seen[0] == (2, 4.0)
    assert summary["best"]["value"] == 5.0
    assert summary["resumed_from"] == 2
    lines = (tmp_path / ".weco" / "local-loop" / "steps.jsonl").read_text().splitlines()
    assert len(lines) == 4  # 2 pre-seeded + 2 new; append-only


def test_eval_timeout_records_null_and_continues(tmp_path):
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="bash", timeout=5, output=b"partial")

    def harness(step, current_best):
        return None

    summary = local_optimize(
        harness_step=harness,
        eval_command="sleep 999",
        metric="score",
        maximize=True,
        steps=2,
        workdir=tmp_path,
        runner=run,
        eval_timeout=5,
    )
    assert all(rec["value"] is None for rec in summary["history"])
    assert "timed out" in summary["history"][0]["output_tail"]
    assert summary["aborted_harness"] is False


def test_harness_failure_retried_once_then_succeeds(tmp_path):
    calls = {"n": 0}

    def harness(step, current_best):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient harness wedgie")

    summary = local_optimize(
        harness_step=harness,
        eval_command="true",
        metric="score",
        maximize=True,
        steps=1,
        workdir=tmp_path,
        runner=_runner_factory(["score: 2.0\n"]),
    )
    assert calls["n"] == 2  # one failure, one retry
    assert summary["history"][0]["value"] == 2.0
    assert summary["aborted_harness"] is False


def test_consecutive_harness_failures_abort_after_three(tmp_path):
    def harness(step, current_best):
        raise RuntimeError("the harness is down")

    summary = local_optimize(
        harness_step=harness,
        eval_command="true",
        metric="score",
        maximize=True,
        steps=5,
        workdir=tmp_path,
        runner=_runner_factory([]),
    )
    assert summary["aborted_harness"] is True
    assert len(summary["history"]) == 3  # three consecutive, then abort
    assert all("harness_error" in rec for rec in summary["history"])
    # the failures are on the append-only log, so a later resume sees them
    lines = (tmp_path / ".weco" / "local-loop" / "steps.jsonl").read_text().splitlines()
    assert len(lines) == 3


def test_resolve_opencode_prefers_path_then_default(monkeypatch):
    import weco.commands.start.opencode_bridge as bridge

    monkeypatch.setattr(bridge.shutil, "which", lambda name: "/opt/oc/bin/opencode")
    assert bridge._resolve_opencode() == "/opt/oc/bin/opencode"

    monkeypatch.setattr(bridge.shutil, "which", lambda name: None)
    monkeypatch.setattr(bridge.os.path, "expanduser", lambda p: "/nonexistent/.opencode/bin/opencode")
    with pytest.raises(FileNotFoundError):
        bridge._resolve_opencode()
