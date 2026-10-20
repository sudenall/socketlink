"""Message latency: time from send_chat() until the receiver gets MESSAGE_RECEIVED.

OWNER: Meryem
Output: results/latency.csv  (mode, messages, latency_ms_mean, latency_ms_std, runs)

Run from the repo root:  python -m benchmarks.bench_latency
"""

from __future__ import annotations

import argparse
import statistics
import time

from benchmarks.bench_common import REPEATS, run_series, summary_columns, write_csv
from benchmarks.harness import Cluster, run_benchmark, wait_for_event
from socketlink.common.constants import TransportMode
from socketlink.common.events import EventType

MESSAGES = 100


def measure_once(mode: TransportMode, messages: int) -> float:
    """Mean one-way latency in ms over `messages` sequential messages alice -> bob."""
    latencies: list[float] = []
    with Cluster(mode) as cluster:
        alice = cluster.add_client("alice")
        bob = cluster.add_client("bob")
        for i in range(messages):
            text = f"ping {i}"
            start = time.perf_counter()
            alice.client.send_chat(text, to="bob")
            wait_for_event(
                bob.events,
                EventType.MESSAGE_RECEIVED,
                predicate=lambda e, t=text: e.data["text"] == t,
            )
            latencies.append((time.perf_counter() - start) * 1000)
    return statistics.fmean(latencies)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--messages", type=int, default=MESSAGES)
    args = parser.parse_args()

    rows = []
    for mode in (TransportMode.TCP, TransportMode.UDP):
        summary = run_series(lambda m=mode: measure_once(m, args.messages), args.repeats)
        row = {"mode": mode.value, "messages": args.messages}
        rows.append({**row, **summary_columns("latency_ms", summary)})
        print(f"{mode.value}: {summary.mean:.2f} +/- {summary.stdev:.2f} ms")
    print(f"wrote {write_csv('latency', rows)}")


if __name__ == "__main__":
    run_benchmark(main)
