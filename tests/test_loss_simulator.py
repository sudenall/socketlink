"""Unit tests for LossSimulator.

OWNER: Yiğit. Every random test uses a seeded random.Random, so results never flake.
"""

from __future__ import annotations

import random

import pytest

from socketlink.reliability.loss_simulator import LossSimulator

DRAWS = 10_000


def test_should_drop_with_zero_loss_never_drops_and_leaves_rng_untouched() -> None:
    rng = random.Random(1)
    simulator = LossSimulator(loss_rate=0.0, rng=rng)
    assert not any(simulator.should_drop() for _ in range(DRAWS))
    assert rng.random() == random.Random(1).random()


def test_should_drop_with_full_loss_always_drops() -> None:
    simulator = LossSimulator(loss_rate=1.0, rng=random.Random(2))
    assert all(simulator.should_drop() for _ in range(DRAWS))


@pytest.mark.parametrize("loss_rate", [0.1, 0.3, 0.5])
def test_should_drop_rate_matches_loss_rate(loss_rate: float) -> None:
    simulator = LossSimulator(loss_rate=loss_rate, rng=random.Random(3))
    dropped = sum(simulator.should_drop() for _ in range(DRAWS))
    assert dropped / DRAWS == pytest.approx(loss_rate, abs=0.02)


def test_should_drop_with_same_seed_is_reproducible() -> None:
    first = LossSimulator(loss_rate=0.3, rng=random.Random(42))
    second = LossSimulator(loss_rate=0.3, rng=random.Random(42))
    assert [first.should_drop() for _ in range(100)] == [
        second.should_drop() for _ in range(100)
    ]


def test_should_drop_follows_a_changed_loss_rate() -> None:
    simulator = LossSimulator(rng=random.Random(4))
    simulator.loss_rate = 1.0
    assert simulator.should_drop()
    simulator.loss_rate = 0.0
    assert not simulator.should_drop()


def test_delay_seconds_is_zero_without_delay() -> None:
    assert LossSimulator().delay_seconds() == 0.0


def test_delay_seconds_converts_milliseconds() -> None:
    assert LossSimulator(delay_ms=250).delay_seconds() == pytest.approx(0.25)


def test_default_simulator_has_no_loss_and_no_delay() -> None:
    simulator = LossSimulator()
    assert simulator.loss_rate == 0.0 and simulator.delay_ms == 0
    assert not simulator.should_drop()
