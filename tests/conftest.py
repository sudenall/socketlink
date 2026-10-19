"""Shared pytest fixtures and helpers.

OWNER: Meryem

Fixtures:
    event_bus       -> a fresh EventBus
    event_queue     -> a queue.Queue subscribed to every event of `event_bus`
    running_server  -> a started ChatServer on 127.0.0.1 with an OS-assigned port (port 0),
                       stopped automatically after the test

Helper:
    wait_for_event(q, EventType, timeout) -> first matching Event, or TimeoutError
"""

from __future__ import annotations

import queue
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest

from socketlink.common.config import ServerConfig
from socketlink.common.constants import TransportMode
from socketlink.common.events import Event, EventBus, EventType
from socketlink.server.server import ChatServer

DEFAULT_EVENT_TIMEOUT = 5.0


def wait_for_event(
    q: queue.Queue[Event],
    event_type: EventType,
    timeout: float = DEFAULT_EVENT_TIMEOUT,
    predicate: Callable[[Event], bool] | None = None,
) -> Event:
    """Return the first event of `event_type` (and passing `predicate`, if given) from `q`.

    Events of other types are discarded while waiting. Raises TimeoutError, naming the
    expected type, if nothing matches within `timeout` seconds.
    """
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"no {event_type.name} event within {timeout} s")
        try:
            event = q.get(timeout=remaining)
        except queue.Empty:
            raise TimeoutError(f"no {event_type.name} event within {timeout} s") from None
        if event.type == event_type and (predicate is None or predicate(event)):
            return event


@dataclass(frozen=True)
class RunningServer:
    """A started server plus the address clients should connect to."""

    server: ChatServer
    host: str
    port: int
    mode: TransportMode
    events: queue.Queue[Event]


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
def event_queue(event_bus: EventBus) -> queue.Queue[Event]:
    return event_bus.subscribe_queue()


@pytest.fixture(params=[TransportMode.TCP], ids=lambda m: m.name)
def running_server(request: pytest.FixtureRequest, event_bus: EventBus) -> Iterator[RunningServer]:
    """Start a ChatServer on localhost with port 0 and yield it.

    Parametrized by transport mode (TCP only until reliable UDP is ready; add
    TransportMode.UDP to `params` then). The real port is read from SERVER_STARTED.
    Skips the test while ChatServer is still a skeleton.
    """
    mode: TransportMode = request.param
    events = event_bus.subscribe_queue()
    config = ServerConfig(host="127.0.0.1", port=0, mode=mode)
    server = ChatServer(event_bus, config)
    try:
        server.start()
    except NotImplementedError:
        pytest.skip("ChatServer.start() is not implemented yet")
    try:
        started = wait_for_event(events, EventType.SERVER_STARTED)
        yield RunningServer(
            server=server,
            host=started.data["host"],
            port=started.data["port"],
            mode=mode,
            events=events,
        )
    finally:
        server.stop()
