"""Smoke tests: every module imports and the shared contracts are consistent.

OWNER: Meryem. These must ALWAYS pass on main (CI runs them on every PR).
"""

import importlib
import struct

import pytest

from socketlink.common import constants as c
from socketlink.common.events import EVENT_DATA_KEYS, Event, EventBus, EventType
from socketlink.common.stats import TransportStats

MODULES = [
    "socketlink.common.constants",
    "socketlink.common.exceptions",
    "socketlink.common.events",
    "socketlink.common.stats",
    "socketlink.common.protocol",
    "socketlink.common.transport",
    "socketlink.common.config",
    "socketlink.common.logger",
    "socketlink.server.server",
    "socketlink.client.client",
    "socketlink.reliability.reliable_udp",
    "socketlink.reliability.loss_simulator",
    "socketlink.transfer.file_transfer",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name: str) -> None:
    importlib.import_module(name)


def test_header_size_matches_format() -> None:
    assert struct.calcsize(c.HEADER_FORMAT) == c.HEADER_SIZE


def test_message_type_values_are_unique() -> None:
    values = [m.value for m in c.MessageType]
    assert len(values) == len(set(values))


def test_every_event_type_has_a_data_contract() -> None:
    assert set(EVENT_DATA_KEYS) == set(EventType)


def test_every_state_has_transitions() -> None:
    assert set(c.STATE_TRANSITIONS) == set(c.ConnectionState)


def test_event_bus_delivers_to_queue() -> None:
    bus = EventBus()
    q = bus.subscribe_queue()
    event = Event(EventType.LOG, {"level": "INFO", "message": "hello"})
    event.validate()
    bus.publish(event)
    assert q.get_nowait() is event


def test_stats_snapshot_is_plain_dict() -> None:
    stats = TransportStats()
    stats.add(packets_sent=2, bytes_sent=10)
    snap = stats.snapshot()
    assert snap["packets_sent"] == 2 and "_lock" not in snap
