"""Artificial packet loss and delay, used ONLY by the reliable UDP transport.

OWNER: Yiğit
USED BY: reliability/reliable_udp.py, right before every sendto() (data and ACK packets).
Testability rule: pass a seeded `random.Random` so tests are reproducible.
"""

from __future__ import annotations

import random
from datetime import timedelta


class LossSimulator:
    """Decides, packet by packet, whether to drop it and how long to hold it back.

    `loss_rate` is a probability in [0, 1]; `delay_ms` is a fixed one-way delay.
    The transport validates both values before storing them here, so this class
    stays a plain, easily testable decision object.
    """

    def __init__(self, loss_rate: float = 0.0, delay_ms: int = 0,
                 rng: random.Random | None = None) -> None:
        """`rng` defaults to an unseeded generator; tests pass a seeded `random.Random`."""
        self.loss_rate = loss_rate
        self.delay_ms = delay_ms
        self.rng = rng or random.Random()

    def should_drop(self) -> bool:
        """True with probability loss_rate.

        The random generator is not consulted when loss_rate is 0, so a run without
        simulated loss never changes the sequence of a seeded generator.
        """
        if self.loss_rate <= 0.0:
            return False
        return self.rng.random() < self.loss_rate

    def delay_seconds(self) -> float:
        """Delay to apply before sending (0 if delay_ms == 0)."""
        if self.delay_ms <= 0:
            return 0.0
        return timedelta(milliseconds=self.delay_ms).total_seconds()
