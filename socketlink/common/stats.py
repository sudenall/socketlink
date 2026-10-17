"""Traffic statistics shared by both transports, the GUIs and the benchmarks.

OWNER: Sude (TCP counters) / Yiğit (UDP-only counters)
RULE: Only the transport layer increments these counters. GUIs only read
      `snapshot()`; they never modify a TransportStats object.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, fields


@dataclass
class TransportStats:
    packets_sent: int = 0
    packets_received: int = 0
    bytes_sent: int = 0
    bytes_received: int = 0
    # reliable-UDP only (stay 0 in TCP mode)
    retransmissions: int = 0
    packets_dropped_simulated: int = 0
    duplicates_received: int = 0
    # both modes
    checksum_errors: int = 0
    avg_rtt_ms: float = 0.0  # measured with PING/PONG (TCP) or data/ACK (UDP)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def add(self, **increments: int | float) -> None:
        """Thread-safe increment, e.g. stats.add(packets_sent=1, bytes_sent=42)."""
        with self._lock:
            for name, value in increments.items():
                setattr(self, name, getattr(self, name) + value)

    def snapshot(self) -> dict[str, int | float]:
        """Thread-safe copy as a plain dict (put this into STATS_UPDATED events)."""
        with self._lock:
            return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "_lock"}
