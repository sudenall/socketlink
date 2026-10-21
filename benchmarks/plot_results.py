"""Draw the report charts from the benchmark CSVs in results/.

OWNER: Meryem
Needs matplotlib (benchmark environment only, not a runtime dependency):
    pip install matplotlib

Reads   results/latency.csv, throughput.csv, loss_sweep.csv, load.csv
Writes  results/latency.png, throughput.png, loss_sweep_duration.png,
        loss_sweep_retransmissions.png, load.png
A chart whose CSV does not exist yet is skipped with a message.

Run from the repo root:  python -m benchmarks.plot_results

Colors are the first three slots of the validated categorical palette, always in this
order. Every mark with more than one series also differs in marker shape, and every
multi-series chart has a legend, so color is never the only cue.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from benchmarks.bench_common import RESULTS_DIR

SERIES_COLORS = ("#2a78d6", "#eb6834", "#1baf7a")  # blue, orange, aqua
MARKERS = ("o", "s", "^")
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#d9d8d3"
SURFACE = "#fcfcfb"

Rows = list[dict[str, str]]


def read_rows(path: Path) -> Rows:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _plt() -> Any:
    """Import pyplot lazily, with the file-only backend (works without a display)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _new_axes(plt: Any, panels: int = 1) -> tuple[Any, Sequence[Any]]:
    fig, axes = plt.subplots(1, panels, figsize=(4.8 * panels, 3.8), dpi=200)
    fig.patch.set_facecolor(SURFACE)
    axes = [axes] if panels == 1 else list(axes)
    for ax in axes:
        ax.set_facecolor(SURFACE)
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(INK_SECONDARY)
        ax.tick_params(colors=INK_SECONDARY, labelsize=9)
        ax.xaxis.label.set_color(INK)
        ax.yaxis.label.set_color(INK)
        ax.title.set_color(INK)
    return fig, axes


def _save(fig: Any, plt: Any, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path, facecolor=fig.get_facecolor())
    plt.close(fig)
    return path


def _bar_labels(
    ax: Any, bars: Any, values: Sequence[float], errors: Sequence[float], fmt: str
) -> None:
    """Print each bar's value above its error bar, so the two never overlap."""
    ax.margins(y=0.15)
    for bar, value, err in zip(bars, values, errors, strict=True):
        ax.annotate(
            format(value, fmt),
            (bar.get_x() + bar.get_width() / 2, value + err),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            fontsize=9,
            color=INK,
        )


def plot_latency(rows: Rows, out: Path) -> Path:
    plt = _plt()
    fig, (ax,) = _new_axes(plt)
    modes = [r["mode"].upper() for r in rows]
    means = [float(r["latency_ms_mean"]) for r in rows]
    stds = [float(r["latency_ms_std"]) for r in rows]
    bars = ax.bar(modes, means, yerr=stds, capsize=4, width=0.45, color=SERIES_COLORS[: len(rows)])
    _bar_labels(ax, bars, means, stds, ".2f")
    ax.set_ylabel("One-way latency (ms)")
    ax.set_title("Message latency, mean ± std")
    return _save(fig, plt, out)


def plot_throughput(rows: Rows, out: Path) -> Path:
    plt = _plt()
    fig, (ax,) = _new_axes(plt)
    sizes = sorted({int(r["size_mb"]) for r in rows})
    modes = sorted({r["mode"] for r in rows})
    width = 0.8 / len(modes)
    for i, mode in enumerate(modes):
        by_size = {int(r["size_mb"]): r for r in rows if r["mode"] == mode}
        xs = [s_index + (i - (len(modes) - 1) / 2) * width for s_index in range(len(sizes))]
        means = [float(by_size[s]["throughput_mbps_mean"]) for s in sizes]
        stds = [float(by_size[s]["throughput_mbps_std"]) for s in sizes]
        bars = ax.bar(
            xs, means, width * 0.9, yerr=stds, capsize=4, color=SERIES_COLORS[i], label=mode.upper()
        )
        _bar_labels(ax, bars, means, stds, ".1f")
    ax.set_xticks(range(len(sizes)), [f"{s} MB" for s in sizes])
    ax.set_ylabel("Throughput (MB/s)")
    ax.set_title("File transfer throughput, mean ± std")
    ax.legend(frameon=False, fontsize=9)
    return _save(fig, plt, out)


def _plot_loss_sweep(rows: Rows, metric: str, ylabel: str, title: str, out: Path) -> Path:
    plt = _plt()
    fig, (ax,) = _new_axes(plt)
    by_window: dict[int, Rows] = defaultdict(list)
    for r in rows:
        by_window[int(r["window"])].append(r)
    for i, window in enumerate(sorted(by_window)):
        points = sorted(by_window[window], key=lambda r: float(r["loss_rate"]))
        xs = [float(r["loss_rate"]) * 100 for r in points]
        ys = [float(r[f"{metric}_mean"]) for r in points]
        errs = [float(r[f"{metric}_std"]) for r in points]
        label = f"Window {window}" + (" (Stop-and-Wait)" if window == 1 else "")
        ax.errorbar(
            xs, ys, yerr=errs, color=SERIES_COLORS[i], marker=MARKERS[i], markersize=7,
            linewidth=2, capsize=3, markeredgecolor=SURFACE, markeredgewidth=1.5, label=label,
        )
        for point, x, y in zip(points, xs, ys, strict=True):
            failed = int(float(point.get("failed_runs") or 0))
            if failed:  # runs whose connection died are not part of the mean: say so
                ax.annotate(
                    f"{failed} failed run(s) not included", (x, y), xytext=(-10, 12),
                    textcoords="offset points", ha="right", fontsize=8, color=INK,
                )
    ax.set_xlabel("Simulated packet loss (%)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(frameon=False, fontsize=9)
    return _save(fig, plt, out)


def plot_loss_sweep_duration(rows: Rows, out: Path) -> Path:
    return _plot_loss_sweep(
        rows, "duration_s", "Time to deliver all messages (s)",
        "Reliable UDP: delivery time vs loss", out,
    )


def plot_loss_sweep_retransmissions(rows: Rows, out: Path) -> Path:
    return _plot_loss_sweep(
        rows, "retransmissions", "Retransmitted packets",
        "Reliable UDP: retransmissions vs loss", out,
    )


def plot_load(rows: Rows, out: Path) -> Path:
    plt = _plt()
    fig, axes = _new_axes(plt, panels=3)
    points = sorted(rows, key=lambda r: int(r["clients"]))
    xs = [int(r["clients"]) for r in points]
    panels = (
        ("broadcast_ms", "Broadcast latency (ms)"),
        ("cpu_percent", "CPU (% of one core)"),
        ("memory_mb", "Memory (MB)"),
    )
    for ax, (metric, ylabel) in zip(axes, panels, strict=True):
        ax.errorbar(
            xs, [float(r[f"{metric}_mean"]) for r in points],
            yerr=[float(r[f"{metric}_std"]) for r in points], color=SERIES_COLORS[0],
            marker=MARKERS[0], markersize=7, linewidth=2, capsize=3,
            markeredgecolor=SURFACE, markeredgewidth=1.5,
        )
        ax.set_xticks(xs)
        ax.set_xlabel("Connected clients")
        ax.set_ylabel(ylabel)
    fig.suptitle("Server load test, mean ± std", color=INK, fontsize=11)
    return _save(fig, plt, out)


# CSV name -> (output PNG, plot function)
CHARTS: tuple[tuple[str, str, Callable[[Rows, Path], Path]], ...] = (
    ("latency", "latency.png", plot_latency),
    ("throughput", "throughput.png", plot_throughput),
    ("loss_sweep", "loss_sweep_duration.png", plot_loss_sweep_duration),
    ("loss_sweep", "loss_sweep_retransmissions.png", plot_loss_sweep_retransmissions),
    ("load", "load.png", plot_load),
)


def plot_all(results_dir: Path = RESULTS_DIR, out_dir: Path | None = None) -> list[Path]:
    """Draw every chart whose CSV exists; return the PNG paths written."""
    out_dir = out_dir or results_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for csv_name, png_name, plot in CHARTS:
        csv_path = results_dir / f"{csv_name}.csv"
        if not csv_path.exists():
            print(f"skipped {png_name}: {csv_path.name} not found")
            continue
        written.append(plot(read_rows(csv_path), out_dir / png_name))
        print(f"wrote {written[-1]}")
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()
    plot_all(args.results_dir, args.out_dir)


if __name__ == "__main__":
    main()
