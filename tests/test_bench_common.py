"""Tests for benchmarks/bench_common.py.

OWNER: Meryem
"""

import csv
from pathlib import Path

import pytest

from benchmarks.bench_common import (
    Summary,
    run_series,
    summarize,
    summary_columns,
    write_csv,
)


def test_summarize_mean_and_sample_stdev() -> None:
    s = summarize([2.0, 4.0, 6.0])
    assert s.mean == pytest.approx(4.0)
    assert s.stdev == pytest.approx(2.0)
    assert s.runs == 3


def test_summarize_single_value_has_zero_stdev() -> None:
    assert summarize([5.0]) == Summary(mean=5.0, stdev=0.0, runs=1)


def test_summarize_rejects_empty() -> None:
    with pytest.raises(ValueError):
        summarize([])


def test_run_series_calls_measure_repeats_times() -> None:
    calls: list[int] = []

    def measure() -> float:
        calls.append(1)
        return float(len(calls))

    s = run_series(measure, repeats=4)
    assert len(calls) == 4
    assert s.mean == pytest.approx(2.5)


def test_run_series_rejects_zero_repeats() -> None:
    with pytest.raises(ValueError):
        run_series(lambda: 1.0, repeats=0)


def test_summary_columns_names() -> None:
    cols = summary_columns("latency_ms", Summary(mean=1.5, stdev=0.25, runs=5))
    assert cols == {"latency_ms_mean": 1.5, "latency_ms_std": 0.25, "runs": 5}


def test_write_csv_round_trip(tmp_path: Path) -> None:
    rows = [{"loss": 0.0, "t_mean": 1.0}, {"loss": 0.1, "t_mean": 2.0}]
    path = write_csv("demo", rows, results_dir=tmp_path)
    assert path == tmp_path / "demo.csv"
    with path.open(newline="", encoding="utf-8") as f:
        read = list(csv.DictReader(f))
    assert read == [{"loss": "0.0", "t_mean": "1.0"}, {"loss": "0.1", "t_mean": "2.0"}]


def test_write_csv_rejects_no_rows(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        write_csv("empty", [], results_dir=tmp_path)
