"""Artificial packet loss and delay, used ONLY by the reliable UDP transport.

OWNER: Yiğit
Testability rule: pass a seeded `random.Random` so tests are reproducible.
"""

from __future__ import annotations

import random


class LossSimulator:
    """Simulates configurable packet loss and network delay for UDP transport."""

    def __init__(
        self,
        loss_rate: float = 0.0,
        delay_ms: int = 0,
        rng: random.Random | None = None,
    ) -> None:
        self.loss_rate = loss_rate
        self.delay_ms = delay_ms
        self.rng = rng if rng is not None else random.Random()

    def should_drop(self) -> bool:
        """Return True with probability loss_rate."""
        if self.loss_rate <= 0.0:
            return False
        if self.loss_rate >= 1.0:
            return True
        return self.rng.random() < self.loss_rate

    def delay_seconds(self) -> float:
        """Return delay in seconds to apply before sending (0.0 if delay_ms <= 0)."""
        if self.delay_ms <= 0:
            return 0.0
        return self.delay_ms / 1000.0
