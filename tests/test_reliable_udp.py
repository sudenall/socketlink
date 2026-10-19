"""Unit tests for LossSimulator and ReliableUdpTransport / ReliableUdpListener.

OWNER: Yiğit
"""

from __future__ import annotations

import random

from socketlink.reliability.loss_simulator import LossSimulator


def test_loss_simulator_zero_loss_never_drops() -> None:
    """With loss_rate=0.0, should_drop must always return False."""
    sim = LossSimulator(loss_rate=0.0, rng=random.Random(42))
    for _ in range(100):
        assert sim.should_drop() is False


def test_loss_simulator_full_loss_always_drops() -> None:
    """With loss_rate=1.0, should_drop must always return True."""
    sim = LossSimulator(loss_rate=1.0, rng=random.Random(42))
    for _ in range(100):
        assert sim.should_drop() is True


def test_loss_simulator_seeded_reproducibility() -> None:
    """Two simulators with the same seed and loss_rate must produce identical decisions."""
    sim1 = LossSimulator(loss_rate=0.25, rng=random.Random(12345))
    sim2 = LossSimulator(loss_rate=0.25, rng=random.Random(12345))
    results1 = [sim1.should_drop() for _ in range(200)]
    results2 = [sim2.should_drop() for _ in range(200)]
    assert results1 == results2


def test_loss_simulator_approximate_drop_ratio() -> None:
    """With loss_rate=0.2, roughly 20% of packets should be dropped over a large sample."""
    sim = LossSimulator(loss_rate=0.2, rng=random.Random(99))
    drops = sum(1 for _ in range(1000) if sim.should_drop())
    assert 150 <= drops <= 250


def test_loss_simulator_delay_seconds_zero() -> None:
    """When delay_ms is 0 or negative, delay_seconds must return 0.0."""
    assert LossSimulator(delay_ms=0).delay_seconds() == 0.0
    assert LossSimulator(delay_ms=-10).delay_seconds() == 0.0


def test_loss_simulator_delay_seconds_conversion() -> None:
    """delay_ms should be accurately converted to seconds."""
    sim = LossSimulator(delay_ms=250)
    assert sim.delay_seconds() == 0.25
