"""Tests for the local observe store and its CLI dispatch (local mode)."""

from __future__ import annotations

import argparse
import json

import pytest

from weco.observe.cli import execute_observe_command
from weco.observe.local_store import LocalStore, LocalStoreError


@pytest.fixture()
def local_mode(monkeypatch):
    monkeypatch.delenv("WECO_MODE", raising=False)


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_store_roundtrip(tmp_path):
    store = LocalStore(tmp_path)
    run_id = store.init_run(
        name="speed pass",
        metric="latency_ms",
        maximize=False,
        source_code={"train.py": "print(1)"},
        additional_instructions=None,
    )
    store.log_step(
        run_id=run_id,
        step=0,
        status="completed",
        description="baseline",
        metrics={"latency_ms": 100.0},
        code=None,
        parent_step=None,
    )
    store.log_step(
        run_id=run_id,
        step=1,
        status="failed",
        description="oom",
        metrics={"latency_ms": 0.0},
        code={"train.py": "print(2)"},
        parent_step=0,
    )

    listed = store.list_runs()
    assert len(listed) == 1
    assert listed[0]["run_id"] == run_id
    assert listed[0]["steps"] == 2
    assert listed[0]["metric"] == "latency_ms"
    assert listed[0]["goal"] == "minimize"

    shown = store.show_run(run_id)
    assert shown["sources"] == ["train.py"]
    assert [step["step"] for step in shown["steps"]] == [0, 1]
    assert shown["steps"][1]["metrics"] == {"latency_ms": 0.0}

    # The on-disk shape: append-only JSONL index plus per-run records.
    index_lines = (tmp_path / ".weco" / "observe" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(index_lines) == 1
    snapshots = (tmp_path / ".weco" / "observe" / "runs" / run_id / "snapshots.jsonl").read_text(encoding="utf-8")
    assert json.loads(snapshots.splitlines()[0])["files"]["train.py"] == "print(2)"


def test_store_unknown_run_raises(tmp_path):
    store = LocalStore(tmp_path)
    with pytest.raises(LocalStoreError):
        store.log_step(run_id="missing", step=0, status="completed", description=None, metrics={}, code=None, parent_step=None)
    with pytest.raises(LocalStoreError):
        store.show_run("missing")


def test_cli_local_init_log_list_show(local_mode, workspace, capsys, monkeypatch):
    (workspace / "train.py").write_text("print('baseline')\n", encoding="utf-8")

    execute_observe_command(
        argparse.Namespace(
            observe_command="init",
            name="latency",
            metric="latency_ms",
            goal="minimize",
            source="train.py",
            sources=None,
            additional_instructions=None,
        )
    )
    run_id = capsys.readouterr().out.strip()

    execute_observe_command(
        argparse.Namespace(
            observe_command="log",
            run_id=run_id,
            step=0,
            status="completed",
            description="baseline",
            metrics='{"latency_ms": 42.0}',
            source=None,
            sources=None,
            parent_step=None,
            strict=False,
        )
    )

    execute_observe_command(argparse.Namespace(observe_command="list"))
    listed = capsys.readouterr().out
    assert run_id in listed
    assert "latency_ms" in listed

    execute_observe_command(argparse.Namespace(observe_command="show", run_id=run_id))
    shown = json.loads(capsys.readouterr().out)
    assert shown["steps"][0]["metrics"] == {"latency_ms": 42.0}


def test_cli_local_log_unknown_run_fails(local_mode, workspace, capsys):
    with pytest.raises(SystemExit) as excinfo:
        execute_observe_command(
            argparse.Namespace(
                observe_command="log",
                run_id="nope",
                step=0,
                status="completed",
                description=None,
                metrics=None,
                source=None,
                sources=None,
                parent_step=None,
                strict=False,
            )
        )
    assert excinfo.value.code == 1


def test_cli_local_invalid_metrics_json_fails(local_mode, workspace):
    (workspace / "train.py").write_text("x = 1\n", encoding="utf-8")
    execute_observe_command(
        argparse.Namespace(
            observe_command="init",
            name=None,
            metric="m",
            goal="minimize",
            source="train.py",
            sources=None,
            additional_instructions=None,
        )
    )
    with pytest.raises(SystemExit) as excinfo:
        execute_observe_command(
            argparse.Namespace(
                observe_command="log",
                run_id="whatever",
                step=0,
                status="completed",
                description=None,
                metrics="{not json",
                source=None,
                sources=None,
                parent_step=None,
                strict=False,
            )
        )
    assert excinfo.value.code == 1
