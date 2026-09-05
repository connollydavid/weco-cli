"""The local optimization loop: the harness provides the intelligence.

In local mode there is no server-side optimizer. The loop is thin and
local: run the evaluation command, parse the metric the weco eval
contract prints (``metric_name: value``), ask the locally configured
harness to improve on the current best, and repeat. Every step lands in
an append-only report under ``.weco/local-loop/``.
"""

from __future__ import annotations

import io
import json
import pathlib
import subprocess
from typing import Callable

HarnessStep = Callable[[int, float | None], None]


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


def run_eval(eval_command: str, *, metric: str, cwd: pathlib.Path, runner=subprocess.run) -> tuple[float | None, str]:
    result = runner(["bash", "-c", eval_command], cwd=str(cwd), capture_output=True, text=True, check=False)
    output = (result.stdout or "") + (result.stderr or "")
    return parse_metric(output, metric), output


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
) -> dict:
    """Run the local loop and return the summary; the report lands on disk.

    ``harness_step(step, current_best)`` does the improving: it drives the
    locally configured agent (in production, over the opencode bridge) and
    edits files in ``workdir``. The loop measures before and after and
    never talks to the network itself.
    """
    if steps < 1:
        raise ValueError("steps must be at least one")
    report_dir = report_dir or workdir / ".weco" / "local-loop"
    report_dir.mkdir(parents=True, exist_ok=True)

    history: list[dict] = []
    best_value: float | None = None
    best_step: int | None = None

    for step in range(steps):
        harness_step(step, best_value)
        value, output = run_eval(eval_command, metric=metric, cwd=workdir, runner=runner)
        improved = value is not None and (best_value is None or (value > best_value if maximize else value < best_value))
        if improved:
            best_value, best_step = value, step
        history.append({"step": step, "value": value, "improved_best": improved, "output_tail": output[-2000:]})
        with (report_dir / "steps.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(history[-1], ensure_ascii=False) + "\n")

    summary = {
        "metric": metric,
        "goal": "maximize" if maximize else "minimize",
        "steps": steps,
        "best": {"step": best_step, "value": best_value},
        "history": history,
    }
    (report_dir / "report.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
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
