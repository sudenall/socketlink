"""File transfer throughput: send a 1 MB and a 10 MB file alice -> bob.

OWNER: Meryem
Output: results/throughput.csv  (mode, size_mb, throughput_mbps_mean, throughput_mbps_std, runs)

Run from the repo root:  python -m benchmarks.bench_throughput
"""

from __future__ import annotations

import argparse
import os
import tempfile
import time
from pathlib import Path

from benchmarks.bench_common import REPEATS, run_series, summary_columns, write_csv
from benchmarks.harness import Cluster, run_benchmark, wait_for_event
from socketlink.common.constants import TransportMode
from socketlink.common.events import EventType

SIZES_MB = (1, 10)


def measure_once(mode: TransportMode, path: Path, size_mb: int) -> float:
    """Throughput in MB/s for one transfer of `path`."""
    with Cluster(mode) as cluster:
        alice = cluster.add_client("alice")
        bob = cluster.add_client("bob")
        start = time.perf_counter()
        transfer_id = alice.client.send_file(str(path), to="bob")
        wait_for_event(
            bob.events,
            EventType.FILE_COMPLETED,
            timeout=120,
            predicate=lambda e: e.data["transfer_id"] == transfer_id,
        )
        return size_mb / (time.perf_counter() - start)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=REPEATS)
    args = parser.parse_args()

    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for size_mb in SIZES_MB:
            path = Path(tmp) / f"payload_{size_mb}mb.bin"
            path.write_bytes(os.urandom(size_mb * 1024 * 1024))
            for mode in (TransportMode.TCP, TransportMode.UDP):
                summary = run_series(
                    lambda m=mode, p=path, s=size_mb: measure_once(m, p, s), args.repeats
                )
                row = {"mode": mode.value, "size_mb": size_mb}
                rows.append({**row, **summary_columns("throughput_mbps", summary)})
                print(f"{mode.value} {size_mb} MB: {summary.mean:.2f} +/- {summary.stdev:.2f} MB/s")
    print(f"wrote {write_csv('throughput', rows)}")


if __name__ == "__main__":
    run_benchmark(main)
