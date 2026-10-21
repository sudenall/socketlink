"""Reliable UDP under packet loss: loss rate (0-30 %) x Go-Back-N window (1 / 4 / 8).

OWNER: Meryem
Output: results/loss_sweep.csv
        (loss_rate, window, failed_runs, duration_s_*, retransmissions_*, runs)

Each run sends MESSAGES messages alice -> bob and measures the time until all arrived,
plus alice's retransmission counter. Window 1 is Stop-and-Wait. Loss and window are applied
on the server side and on every client, so both legs (alice -> server -> bob) are lossy.

At high loss a connection can fail for real: a packet that is not acknowledged after
MAX_RETRIES retransmissions ends the connection. Such a run is counted in `failed_runs`
and repeated, up to as many failures as repeats; it is not part of the means. The CSV is
rewritten after every parameter combination, so an interrupted sweep keeps its results.

Run from the repo root:  python -m benchmarks.bench_loss_sweep
"""

from __future__ import annotations

import argparse
import queue
import time

from benchmarks.bench_common import REPEATS, summarize, summary_columns, write_csv
from benchmarks.harness import Cluster, Peer, run_benchmark
from socketlink.common.constants import ErrorCode, TransportMode
from socketlink.common.events import Event, EventType
from socketlink.common.exceptions import SocketLinkError

LOSS_RATES = (0.0, 0.1, 0.2, 0.3)
WINDOWS = (1, 4, 8)
MESSAGES = 200
RUN_TIMEOUT = 120.0  # seconds one run may take before it counts as failed
METRICS = ("duration_s", "retransmissions")


class RunFailedError(Exception):
    """The connection ended, or the messages did not arrive, before the run was complete."""


def _drain(q: queue.Queue[Event], wait: float) -> list[Event]:
    """All events currently in `q`; blocks up to `wait` seconds for the first one."""
    events: list[Event] = []
    try:
        events.append(q.get(timeout=wait) if wait > 0 else q.get_nowait())
        while True:
            events.append(q.get_nowait())
    except queue.Empty:
        return events


def _deliver_all(alice: Peer, bob: Peer, messages: int) -> None:
    """Return when bob has received `messages` messages; raise RunFailedError if the run dies."""
    received = 0
    deadline = time.monotonic() + RUN_TIMEOUT
    while received < messages:
        if time.monotonic() > deadline:
            raise RunFailedError(
                f"only {received} of {messages} messages after {RUN_TIMEOUT:.0f} s"
            )
        for event in _drain(bob.events, wait=0.2):
            if event.type is EventType.MESSAGE_RECEIVED:
                received += 1
            elif event.type is EventType.DISCONNECTED:
                raise RunFailedError(f"receiver disconnected ({event.data['reason']})")
        for event in _drain(alice.events, wait=0):
            if event.type is EventType.DISCONNECTED:
                raise RunFailedError(f"sender disconnected ({event.data['reason']})")
            if event.type is EventType.ERROR and event.data["code"] == ErrorCode.UNKNOWN_USER.value:
                raise RunFailedError("receiver is no longer connected to the server")


def measure_once(loss_rate: float, window: int, messages: int) -> dict[str, float]:
    with Cluster(TransportMode.UDP, loss_rate=loss_rate, window_size=window) as cluster:
        alice = cluster.add_client("alice")
        bob = cluster.add_client("bob")
        start = time.perf_counter()
        try:
            for i in range(messages):
                alice.client.send_chat(f"msg {i}", to="bob")
        except SocketLinkError as exc:  # e.g. the sender's own connection already failed
            raise RunFailedError(f"send failed: {exc}") from exc
        _deliver_all(alice, bob, messages)
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

    rows: list[dict[str, object]] = []
    for loss in LOSS_RATES:
        for window in WINDOWS:
            runs: list[dict[str, float]] = []
            failures = 0
            while len(runs) < args.repeats and failures < args.repeats:
                try:
                    runs.append(measure_once(loss, window, args.messages))
                except RunFailedError as exc:
                    failures += 1
                    print(f"  loss {loss:.0%} window {window}: run failed, {exc}", flush=True)
            row: dict[str, object] = {"loss_rate": loss, "window": window,
                                      "failed_runs": failures}
            for metric in METRICS:
                if runs:
                    row.update(summary_columns(metric, summarize([r[metric] for r in runs])))
                else:  # every run failed: keep the columns, leave the values empty
                    row.update({f"{metric}_mean": "", f"{metric}_std": "", "runs": 0})
            rows.append(row)
            write_csv("loss_sweep", rows)
            mean = f"{row['duration_s_mean']:.2f} s" if runs else "no successful run"
            print(f"loss {loss:.0%} window {window}: {mean} ({failures} failed)", flush=True)
    print(f"wrote {write_csv('loss_sweep', rows)}")


if __name__ == "__main__":
    run_benchmark(main)
