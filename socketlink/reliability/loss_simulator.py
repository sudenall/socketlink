"""Artificial packet loss and delay, used ONLY by the reliable UDP transport.

OWNER: Yiğit
Testability rule: pass a seeded `random.Random` so tests are reproducible.
"""

from __future__ import annotations

import random


class LossSimulator:
    def __init__(self, loss_rate: float = 0.0, delay_ms: int = 0,
                 rng: random.Random | None = None) -> None:
        self.loss_rate = loss_rate
        self.delay_ms = delay_ms
        self.rng = rng or random.Random()

    def should_drop(self) -> bool:
        """True with probability loss_rate."""
        raise NotImplementedError("TODO(Yiğit)")

    def delay_seconds(self) -> float:
        """Delay to apply before sending (0 if delay_ms == 0)."""
        raise NotImplementedError("TODO(Yiğit)")
