"""Tests for the shared helpers in conftest.py.

OWNER: Meryem
"""

import queue

import pytest

from socketlink.common.events import Event, EventBus, EventType
from tests.conftest import wait_for_event


def _log(message: str) -> Event:
    return Event(EventType.LOG, {"level": "INFO", "message": message})


def test_wait_for_event_returns_matching_event(
    event_bus: EventBus, event_queue: queue.Queue
) -> None:
    event_bus.publish(_log("hello"))
    assert wait_for_event(event_queue, EventType.LOG, timeout=1).data["message"] == "hello"


def test_wait_for_event_skips_other_types(event_bus: EventBus, event_queue: queue.Queue) -> None:
    event_bus.publish(Event(EventType.ERROR, {"code": "X", "message": "boom"}))
    event_bus.publish(_log("later"))
    assert wait_for_event(event_queue, EventType.LOG, timeout=1).data["message"] == "later"


def test_wait_for_event_applies_predicate(event_bus: EventBus, event_queue: queue.Queue) -> None:
    event_bus.publish(_log("first"))
    event_bus.publish(_log("second"))
    event = wait_for_event(
        event_queue, EventType.LOG, timeout=1, predicate=lambda e: e.data["message"] == "second"
    )
    assert event.data["message"] == "second"


def test_wait_for_event_times_out(event_queue: queue.Queue) -> None:
    with pytest.raises(TimeoutError, match="LOG"):
        wait_for_event(event_queue, EventType.LOG, timeout=0.1)
