"""Tests for benchmarks/plot_results.py (skipped when matplotlib is not installed).

OWNER: Meryem
"""

import csv
from pathlib import Path

import pytest

pytest.importorskip("matplotlib")

from benchmarks.plot_results import CHARTS, plot_all, read_rows  # noqa: E402

CSV_FILES = {
    "latency": [
        {"mode": "tcp", "messages": 100, "latency_ms_mean": 0.4, "latency_ms_std": 0.05, "runs": 5},
        {"mode": "udp", "messages": 100, "latency_ms_mean": 0.9, "latency_ms_std": 0.1, "runs": 5},
    ],
    "throughput": [
        {"mode": m, "size_mb": s, "throughput_mbps_mean": 10.0 + s, "throughput_mbps_std": 1.0,
         "runs": 5}
        for m in ("tcp", "udp")
        for s in (1, 10)
    ],
    "loss_sweep": [
        {"loss_rate": loss, "window": w, "duration_s_mean": 1 + loss * w, "duration_s_std": 0.1,
         "retransmissions_mean": loss * 100 / w, "retransmissions_std": 1.0, "runs": 5}
        for loss in (0.0, 0.1, 0.2, 0.3)
        for w in (1, 4, 8)
    ],
    "load": [
        {"clients": c, "broadcast_ms_mean": c * 0.5, "broadcast_ms_std": 0.2,
         "cpu_percent_mean": c * 1.5, "cpu_percent_std": 0.5,
         "memory_mb_mean": 50 + c, "memory_mb_std": 1.0, "runs": 5}
        for c in (10, 25, 50)
    ],
}


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_read_rows_returns_strings(tmp_path: Path) -> None:
    _write_csv(tmp_path / "x.csv", [{"a": 1, "b": 2.5}])
    assert read_rows(tmp_path / "x.csv") == [{"a": "1", "b": "2.5"}]


def test_plot_all_writes_every_chart(tmp_path: Path) -> None:
    for name, rows in CSV_FILES.items():
        _write_csv(tmp_path / f"{name}.csv", rows)
    out_dir = tmp_path / "png"
    written = plot_all(tmp_path, out_dir)
    assert {p.name for p in written} == {png for _, png, _ in CHARTS}
    assert all(p.stat().st_size > 1000 for p in written)


def test_plot_all_skips_missing_csv(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write_csv(tmp_path / "latency.csv", CSV_FILES["latency"])
    written = plot_all(tmp_path, tmp_path)
    assert [p.name for p in written] == ["latency.png"]
    assert "skipped throughput.png" in capsys.readouterr().out
