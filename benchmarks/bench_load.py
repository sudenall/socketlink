"""Load test: 10 / 25 / 50 clients on one server (TCP).

OWNER: Meryem
Output: results/load.csv
        (clients, broadcast_ms_*, cpu_percent_*, memory_mb_*, runs)

Per run: connect N clients, one client broadcasts ROUNDS messages; a round's latency is
the time until EVERY other client has received it. CPU and memory are those of this
process (server and clients run in-process), sampled with psutil.

Run from the repo root:  python -m benchmarks.bench_load
"""

from __future__ import annotations

import argparse
import statistics
import time

import psutil

from benchmarks.bench_common import REPEATS, collect, summary_columns, write_csv
from benchmarks.harness import Cluster, run_benchmark, wait_for_event
from socketlink.common.constants import TransportMode
from socketlink.common.events import EventType

CLIENT_COUNTS = (10, 25, 50)
ROUNDS = 20


def measure_once(clients: int, rounds: int) -> dict[str, float]:
    process = psutil.Process()
    process.cpu_percent(None)  # first call only primes the counter
    latencies: list[float] = []
    with Cluster(TransportMode.TCP) as cluster:
        peers = [cluster.add_client(f"user{i:02d}") for i in range(clients)]
        sender, receivers = peers[0], peers[1:]
        for r in range(rounds):
            text = f"round {r}"
            start = time.perf_counter()
            sender.client.send_chat(text)
            for peer in receivers:
                wait_for_event(
                    peer.events,
                    EventType.MESSAGE_RECEIVED,
                    predicate=lambda e, t=text: e.data["text"] == t,
                )
            latencies.append((time.perf_counter() - start) * 1000)
        return {
            "broadcast_ms": statistics.fmean(latencies),
            "cpu_percent": process.cpu_percent(None),
            "memory_mb": process.memory_info().rss / (1024 * 1024),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    parser.add_argument("--rounds", type=int, default=ROUNDS)
    args = parser.parse_args()

    rows = []
    for count in CLIENT_COUNTS:
        result = collect(lambda c=count: measure_once(c, args.rounds), args.repeats)
        row: dict[str, float | int] = {"clients": count}
        for metric, summary in result.items():
            row.update({k: v for k, v in summary_columns(metric, summary).items() if k != "runs"})
        row["runs"] = args.repeats
        rows.append(row)
        print(f"{count} clients: {result['broadcast_ms'].mean:.1f} ms per broadcast")
    print(f"wrote {write_csv('load', rows)}")


if __name__ == "__main__":
    run_benchmark(main)
