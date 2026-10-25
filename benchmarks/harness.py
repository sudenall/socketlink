"""In-process server + clients for the benchmark scripts.

OWNER: Meryem

`Cluster` starts a ChatServer on 127.0.0.1 (OS-assigned port) and connects named
clients to it. Use it as a context manager so everything is stopped afterwards.

Not runnable until ChatServer / ChatClient are implemented: `run_benchmark` turns
the resulting NotImplementedError into a clear message and exit code 2.
"""

from __future__ import annotations

import queue
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType

from socketlink.client.client import ChatClient
from socketlink.common.config import ClientConfig, ServerConfig
from socketlink.common.constants import DEFAULT_WINDOW_SIZE, TransportMode
from socketlink.common.events import Event, EventBus, EventType
from socketlink.server.server import ChatServer

EVENT_TIMEOUT = 10.0


def wait_for_event(
    q: queue.Queue[Event],
    event_type: EventType,
    timeout: float = EVENT_TIMEOUT,
    predicate: Callable[[Event], bool] | None = None,
) -> Event:
    """First event of `event_type` (passing `predicate`) from `q`; TimeoutError otherwise."""
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
class Peer:
    name: str
    client: ChatClient
    events: queue.Queue[Event]


class Cluster:
    """One server plus any number of connected clients."""

    def __init__(
        self,
        mode: TransportMode = TransportMode.TCP,
        loss_rate: float = 0.0,
        delay_ms: int = 0,
        window_size: int = DEFAULT_WINDOW_SIZE,
    ) -> None:
        self.mode = mode
        self.loss_rate = loss_rate
        self.delay_ms = delay_ms
        self.window_size = window_size
        self.server_bus = EventBus()
        self.server = ChatServer(
            self.server_bus,
            ServerConfig(
                host="127.0.0.1",
                port=0,
                mode=mode,
                loss_rate=loss_rate,
                delay_ms=delay_ms,
                window_size=window_size,
            ),
        )
        self.peers: list[Peer] = []
        self._host = "127.0.0.1"
        self._port = 0

    def __enter__(self) -> Cluster:
        events = self.server_bus.subscribe_queue()
        self.server.start()
        started = wait_for_event(events, EventType.SERVER_STARTED)
        self._host, self._port = started.data["host"], started.data["port"]
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        for peer in self.peers:
            try:
                peer.client.disconnect()
            except Exception:  # noqa: BLE001 - cleanup must not mask the real error
                pass
        self.server.stop()

    def add_client(
        self,
        username: str,
        download_dir: str | None = None,
        auto_reconnect: bool = False,
    ) -> Peer:
        bus = EventBus()
        events = bus.subscribe_queue()
        extra = {} if download_dir is None else {"download_dir": download_dir}
        client = ChatClient(
            bus,
            ClientConfig(
                host=self._host,
                port=self._port,
                mode=self.mode,
                username=username,
                auto_reconnect=auto_reconnect,
                loss_rate=self.loss_rate,
                delay_ms=self.delay_ms,
                window_size=self.window_size,
                **extra,
            ),
        )
        client.connect()
        wait_for_event(events, EventType.CONNECTED)
        # The server lists a user only once it can receive messages. Wait until every
        # earlier client has seen the new user, so a message sent right after this call is
        # never rejected with UNKNOWN_USER (a GUI user cannot pick a user before the list
        # shows it either).
        for other in self.peers:
            wait_for_event(
                other.events,
                EventType.USER_LIST_UPDATED,
                predicate=lambda e, name=username: name in e.data["users"],
            )
        peer = Peer(username, client, events)
        self.peers.append(peer)
        return peer


def run_benchmark(main: Callable[[], None]) -> None:
    """Run a benchmark's main(); explain clearly if the core is not implemented yet."""
    try:
        main()
    except NotImplementedError as err:
        print(f"Benchmark cannot run yet: {err}", file=sys.stderr)
        sys.exit(2)
