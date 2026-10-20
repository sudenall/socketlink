"""Reliable UDP under packet loss: loss rate (0-30 %) x Go-Back-N window (1 / 4 / 8).

OWNER: Meryem
Output: results/loss_sweep.csv
        (loss_rate, window, duration_s_*, retransmissions_*, runs)

Each run sends MESSAGES messages alice -> bob and measures the time until all arrived,
plus alice's retransmission counter. Window 1 is Stop-and-Wait.

Run from the repo root:  python -m benchmarks.bench_loss_sweep
"""

from __future__ import annotations

import argparse
import time

from benchmarks.bench_common import REPEATS, collect, summary_columns, write_csv
from benchmarks.harness import Cluster, run_benchmark, wait_for_event
from socketlink.common.constants import TransportMode
from socketlink.common.events import EventType

LOSS_RATES = (0.0, 0.1, 0.2, 0.3)
WINDOWS = (1, 4, 8)
MESSAGES = 200


def measure_once(loss_rate: float, window: int, messages: int) -> dict[str, float]:
    with Cluster(TransportMode.UDP, loss_rate=loss_rate, window_size=window) as cluster:
        alice = cluster.add_client("alice")
        bob = cluster.add_client("bob")
        start = time.perf_counter()
        for i in range(messages):
            alice.client.send_chat(f"msg {i}", to="bob")
        for _ in range(messages):
            wait_for_event(bob.events, EventType.MESSAGE_RECEIVED, timeout=120)
        duration = time.perf_counter() - start
        return {
            "duration_s": duration,
            "retransmissions": float(alice.client.get_stats()["retransmissions"]),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--messages", type=int, default=MESSAGES)
    args = parser.parse_args()

    rows = []
    for loss in LOSS_RATES:
        for window in WINDOWS:
            result = collect(
                lambda rate=loss, w=window: measure_once(rate, w, args.messages), args.repeats
            )
            row = {"loss_rate": loss, "window": window}
            row.update(summary_columns("duration_s", result["duration_s"]))
            row.update(summary_columns("retransmissions", result["retransmissions"]))
            rows.append(row)
            print(f"loss {loss:.0%} window {window}: {result['duration_s'].mean:.2f} s")
    print(f"wrote {write_csv('loss_sweep', rows)}")


if __name__ == "__main__":
    run_benchmark(main)
