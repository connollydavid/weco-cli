"""The local optimization loop: the harness provides the intelligence.

In local mode there is no server-side optimizer. The loop is thin and
local: run the evaluation command, parse the metric the weco eval
contract prints (``metric_name: value``), ask the locally configured
harness to improve on the current best, and repeat. Every step lands in
an append-only report under ``.weco/local-loop/``.

Campaign resilience (feature/local-campaign-resilience): the loop can
resume from its own append-only step log, bound a wedged eval with a
timeout, and survive harness failures with one retry before recording
the step as failed; three consecutive harness failures abort the run
loudly instead of silently burning walltime. These mirror the
supervision proven by the campaign-runner wrapper
(agentic-vllm tools/campaign-runner, selftest 6/6).
"""

from __future__ import annotations

import io
import json
import pathlib
import subprocess
from typing import Callable

HarnessStep = Callable[[int, float | None], None]

MAX_CONSECUTIVE_HARNESS_FAILURES = 3


def parse_metric(output: str, metric: str) -> float | None:
    """The last ``<metric>: <value>`` line in an eval output, or None."""
    prefix = f"{metric}:"
    value: float | None = None
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(prefix.lower()):
            try:
                value = float(stripped[len(prefix) :].strip())
            except ValueError:
                continue
    return value


def run_eval(
    eval_command: str,
    *,
    metric: str,
    cwd: pathlib.Path,
    runner=subprocess.run,
    timeout: float | None = None,
) -> tuple[float | None, str]:
    try:
        result = runner(
            ["bash", "-c", eval_command],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        output = ""
        if exc.stdout:
            output = (
                exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout
            )
        if exc.stderr:
            err = exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr
            output += err
        output += f"\nweco: eval timed out after {timeout}s"
        return None, output
    output = (result.stdout or "") + (result.stderr or "")
    return parse_metric(output, metric), output


def _reconstruct_best(
    report_dir: pathlib.Path, maximize: bool
) -> tuple[int, float | None, int | None]:
    """Resume state from the append-only step log: how many steps are
    already recorded, and the best value among them."""
    steps_file = report_dir / "steps.jsonl"
    if not steps_file.exists():
        return 0, None, None
    done = 0
    best: float | None = None
    best_step: int | None = None
    for line in steps_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        done += 1
        value = rec.get("value")
        if value is not None and (best is None or (value > best) == maximize):
            best, best_step = value, rec.get("step")
    return done, best, best_step


def local_optimize(
    *,
    harness_step: HarnessStep,
    eval_command: str,
    metric: str,
    maximize: bool,
    steps: int,
    workdir: pathlib.Path,
    report_dir: pathlib.Path | None = None,
    runner=subprocess.run,
    resume: bool = False,
    eval_timeout: float | None = None,
) -> dict:
    """Run the local loop and return the summary; the report lands on disk.

    ``harness_step(step, current_best)`` does the improving: it drives the
    locally configured agent (in production, over the opencode bridge) and
    edits files in ``workdir``. The loop measures before and after and
    never talks to the network itself.

    With ``resume=True`` the append-only step log is the state of record:
    already-recorded steps are skipped, numbering continues, and the best
    value is reconstructed from the recorded history rather than reused
    as a fresh measurement. A harness failure is retried once; a step
    that still fails is recorded with ``harness_error`` and the loop
    continues unless failures turn consecutive-three, which aborts loudly.
    """
    if steps < 1:
        raise ValueError("steps must be at least one")
    report_dir = report_dir or workdir / ".weco" / "local-loop"
    report_dir.mkdir(parents=True, exist_ok=True)

    start = 0
    best_value: float | None = None
    best_step: int | None = None
    if resume:
        start, best_value, best_step = _reconstruct_best(report_dir, maximize)

    history: list[dict] = []
    consecutive_harness_failures = 0
    aborted_harness = False

    for step in range(start, steps):
        try:
            harness_step(step, best_value)
            consecutive_harness_failures = 0
        except Exception as first:  # noqa: BLE001 - recorded, then retried
            try:
                harness_step(step, best_value)
                consecutive_harness_failures = 0
            except Exception as second:  # noqa: BLE001
                record = {
                    "step": step,
                    "value": None,
                    "improved_best": False,
                    "harness_error": str(second)[:500],
                    "first_error": str(first)[:500],
                }
                history.append(record)
                with (report_dir / "steps.jsonl").open(
                    "a", encoding="utf-8"
                ) as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                consecutive_harness_failures += 1
                if consecutive_harness_failures >= MAX_CONSECUTIVE_HARNESS_FAILURES:
                    aborted_harness = True
                    break
                continue
        value, output = run_eval(
            eval_command,
            metric=metric,
            cwd=workdir,
            runner=runner,
            timeout=eval_timeout,
        )
        improved = value is not None and (
            best_value is None or (value > best_value) == maximize
        )
        if improved:
            best_value, best_step = value, step
        history.append(
            {
                "step": step,
                "value": value,
                "improved_best": improved,
                "output_tail": output[-2000:],
            }
        )
        with (report_dir / "steps.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(history[-1], ensure_ascii=False) + "\n")

    summary = {
        "metric": metric,
        "goal": "maximize" if maximize else "minimize",
        "steps": steps,
        "best": {"step": best_step, "value": best_value},
        "history": history,
        "resumed_from": start if resume else 0,
        "aborted_harness": aborted_harness,
    }
    (report_dir / "report.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def make_opencode_step(workdir: pathlib.Path, *, metric: str, maximize: bool, agent: str | None = None):
    """A harness step that drives opencode over the bridge, in workdir."""

    def step(index: int, current_best: float | None) -> None:
        from rich.console import Console

        from weco.commands.start.opencode_bridge import run_opencode_bridge

        goal = "maximize" if maximize else "minimize"
        prompt = (
            f"Optimization step {index + 1}: improve the {metric} metric ({goal}) of the code in this "
            "workspace by editing the files. "
            + (
                f"The best {metric} so far is {current_best}; beat it. "
                if current_best is not None
                else "Establish a strong baseline. "
            )
            + "The evaluation command will measure your changes afterwards. Edit files only; do not run "
            "the evaluation loop yourself."
        )
        console = Console(file=io.StringIO(), force_terminal=False, color_system=None)
        code = run_opencode_bridge(prompt=prompt, agent=agent, forwarded_args=[], console=console)
        if code != 0:
            raise RuntimeError(f"the opencode harness exited {code}")

    return step
