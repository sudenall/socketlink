"""Shared helpers for the benchmark scripts.

OWNER: Meryem

Every benchmark repeats each measurement REPEATS times and reports mean +/- standard
deviation, then writes one CSV to results/<name>.csv.

Typical use in a benchmark script:

    summary = run_series(lambda: measure_latency(...))
    rows.append({"loss_rate": 0.1, **summary_columns("latency_ms", summary)})
    write_csv("latency", rows)
"""

from __future__ import annotations

import csv
import statistics
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

REPEATS = 5
RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


@dataclass(frozen=True)
class Summary:
    mean: float
    stdev: float  # sample standard deviation; 0.0 when there is a single run
    runs: int


def summarize(values: Sequence[float]) -> Summary:
    """Mean and sample standard deviation of `values` (at least one value)."""
    if not values:
        raise ValueError("summarize() needs at least one value")
    stdev = statistics.stdev(values) if len(values) > 1 else 0.0
    return Summary(mean=statistics.fmean(values), stdev=stdev, runs=len(values))


def run_series(measure: Callable[[], float], repeats: int = REPEATS) -> Summary:
    """Call `measure()` `repeats` times and summarize the returned numbers."""
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    return summarize([measure() for _ in range(repeats)])


def summary_columns(metric: str, summary: Summary) -> dict[str, float | int]:
    """CSV columns for one metric: <metric>_mean, <metric>_std, runs."""
    return {
        f"{metric}_mean": round(summary.mean, 6),
        f"{metric}_std": round(summary.stdev, 6),
        "runs": summary.runs,
    }


def write_csv(
    name: str,
    rows: Iterable[Mapping[str, object]],
    results_dir: Path = RESULTS_DIR,
) -> Path:
    """Write `rows` to <results_dir>/<name>.csv (columns taken from the first row)."""
    rows = list(rows)
    if not rows:
        raise ValueError("write_csv() needs at least one row")
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"{name}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path
