"""Fault injection between a real ChatServer and real ChatClients (T-10, README 13.1/13.2).

OWNER: Hamit
T-10: a client that disappears without saying BYE must be removed by the server, and the
rest of the system must notice. Two ways to disappear:
    frozen  -> the socket stays open but nothing arrives (process hangs, laptop sleeps,
               cable pulled): only the server's watchdog (CONNECTION_TIMEOUT) can see it.
    killed  -> the process dies, the OS closes the socket: the server sees EOF/reset at
               once and must not wait for the watchdog.
And the opposite: a healthy client that sends heartbeats must never be dropped.

Timing constants are shortened with monkeypatch (the server's CONNECTION_TIMEOUT and
watchdog period, the client's heartbeat) so every test runs in a few seconds. The
client's own silence timer keeps its 15 s default, so in these tests the server's
watchdog always notices the frozen client first.

Measured once with the real defaults (CONNECTION_TIMEOUT = 15 s, watchdog every 1 s,
client fully frozen): removed after 16.0 s with reason timeout; a killed client was
removed after ~2 ms with reason connection_lost.
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable, Iterator

import pytest

from socketlink.client import client as client_module
from socketlink.client.client import ChatClient
from socketlink.common.config import ClientConfig, ServerConfig
from socketlink.common.constants import ConnectionState, DisconnectReason, TransportMode
from socketlink.common.events import Event, EventBus, EventType
from socketlink.server import server as server_module
from socketlink.server.server import ChatServer
from tests.conftest import wait_for_event

pytestmark = pytest.mark.integration

HOST = "127.0.0.1"
SERVER_TIMEOUT = 1.0    # stands in for CONNECTION_TIMEOUT (15 s) on the server
WATCHDOG_PERIOD = 0.2   # stands in for STATS_UPDATE_INTERVAL, the watchdog's period
HEALTHY_HEARTBEAT = 0.2  # a heartbeat well inside SERVER_TIMEOUT
EVENT_TIMEOUT = 5.0


class Cluster:
    """One running server plus clients, each with its own EventBus and event queue."""

    def __init__(self) -> None:
        self.server_bus = EventBus()
        self.server_events = self.server_bus.subscribe_queue()
        self.server = ChatServer(self.server_bus, ServerConfig(host=HOST, port=0))
        self.port = 0
        self.clients: list[ChatClient] = []

    def start(self) -> Cluster:
        self.server.start()
        started = wait_for_event(self.server_events, EventType.SERVER_STARTED)
        self.port = started.data["port"]
        return self

    def join(self, username: str, auto_reconnect: bool = False,
             wake_up: threading.Event | None = None) -> tuple[ChatClient, queue.Queue[Event]]:
        """Connect a client. With `wake_up`, the client is "frozen": its heartbeat thread
        sends nothing until `wake_up` is set (only this client; others keep pinging)."""
        bus = EventBus()
        events = bus.subscribe_queue()
        chat = ChatClient(bus, ClientConfig(host=HOST, port=self.port, mode=TransportMode.TCP,
                                            username=username, auto_reconnect=auto_reconnect))
        if wake_up is not None:
            heartbeat = chat._heartbeat_loop

            def frozen_heartbeat() -> None:
                wake_up.wait()
                heartbeat()

            chat._heartbeat_loop = frozen_heartbeat
        chat.connect()
        wait_for_event(events, EventType.CONNECTED)
        self.clients.append(chat)
        return chat, events

    def server_usernames(self) -> list[str]:
        return sorted(info.username for info in self.server.get_clients())

    def stop(self) -> None:
        for chat in self.clients:
            chat.disconnect()
        self.server.stop()


@pytest.fixture(autouse=True)
def short_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_module, "CONNECTION_TIMEOUT", SERVER_TIMEOUT)
    monkeypatch.setattr(server_module, "STATS_UPDATE_INTERVAL", WATCHDOG_PERIOD)
    monkeypatch.setattr(client_module, "HEARTBEAT_INTERVAL", HEALTHY_HEARTBEAT)
    monkeypatch.setattr(client_module, "STATS_UPDATE_INTERVAL", 0.05)
    monkeypatch.setattr(client_module, "RECONNECT_DELAYS", (0.1, 0.1, 0.1))


@pytest.fixture
def cluster() -> Iterator[Cluster]:
    running = Cluster().start()
    yield running
    running.stop()


def wait_until(condition: Callable[[], bool], timeout: float = EVENT_TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(0.02)


def test_frozen_client_is_removed_by_the_watchdog(cluster: Cluster) -> None:
    """T-10 (frozen): removed after CONNECTION_TIMEOUT, others get the new user list."""
    alice, alice_events = cluster.join("alice")          # healthy, keeps sending PING
    bob, bob_events = cluster.join("bob", wake_up=threading.Event())  # never wakes up
    joined_at = time.monotonic()

    left = wait_for_event(cluster.server_events, EventType.CLIENT_LEFT,
                          predicate=lambda e: e.data["username"] == "bob")
    elapsed = time.monotonic() - joined_at
    assert left.data["reason"] == DisconnectReason.TIMEOUT.value
    # not before the timeout, and not much later than one watchdog round after it
    assert SERVER_TIMEOUT <= elapsed <= SERVER_TIMEOUT + WATCHDOG_PERIOD + 1.0

    wait_for_event(alice_events, EventType.USER_LIST_UPDATED,
                   predicate=lambda e: e.data["users"] == ["alice"])
    disconnected = wait_for_event(bob_events, EventType.DISCONNECTED)
    assert disconnected.data["reason"] == DisconnectReason.TIMEOUT.value  # got BYE timeout
    assert cluster.server_usernames() == ["alice"]
    assert alice.state is ConnectionState.CONNECTED


def test_frozen_client_with_auto_reconnect_comes_back(cluster: Cluster) -> None:
    """After the timeout BYE the client reconnects by itself and is listed again."""
    alice, alice_events = cluster.join("alice")
    wake_up = threading.Event()
    bob, bob_events = cluster.join("bob", auto_reconnect=True, wake_up=wake_up)

    wait_for_event(bob_events, EventType.STATE_CHANGED,
                   predicate=lambda e: e.data["new"] is ConnectionState.RECONNECTING)
    wake_up.set()  # the client recovers: from now on it sends heartbeats again
    wait_for_event(bob_events, EventType.CONNECTED)
    wait_for_event(alice_events, EventType.USER_LIST_UPDATED,
                   predicate=lambda e: e.data["users"] == ["alice", "bob"])
    assert bob.state is ConnectionState.CONNECTED


def test_killed_client_is_removed_at_once_without_waiting_for_the_watchdog(
        cluster: Cluster, monkeypatch: pytest.MonkeyPatch) -> None:
    """T-10 (killed): no BYE, socket closed by the OS -> CLIENT_LEFT connection_lost fast."""
    monkeypatch.setattr(server_module, "CONNECTION_TIMEOUT", 30.0)  # the watchdog cannot help
    alice, alice_events = cluster.join("alice")
    bob, _ = cluster.join("bob")
    killed_at = time.monotonic()
    bob._stop_event.set()   # its threads stop like a dying process ...
    bob._transport.close()  # ... and the OS closes the socket, without a BYE

    left = wait_for_event(cluster.server_events, EventType.CLIENT_LEFT,
                          predicate=lambda e: e.data["username"] == "bob")
    assert left.data["reason"] == DisconnectReason.CONNECTION_LOST.value
    assert time.monotonic() - killed_at < 2.0
    wait_for_event(alice_events, EventType.USER_LIST_UPDATED,
                   predicate=lambda e: e.data["users"] == ["alice"])


def test_client_with_heartbeat_is_never_dropped(cluster: Cluster) -> None:
    """No false alarm: connected for several CONNECTION_TIMEOUTs, still listed."""
    alice, alice_events = cluster.join("alice")
    time.sleep(SERVER_TIMEOUT * 3)
    assert cluster.server_usernames() == ["alice"]
    assert alice.state is ConnectionState.CONNECTED
    assert alice.get_stats()["avg_rtt_ms"] > 0  # the heartbeats really went out
    left = [e for e in iter_queue(cluster.server_events) if e.type is EventType.CLIENT_LEFT]
    assert left == []


def iter_queue(q: queue.Queue[Event]) -> list[Event]:
    items: list[Event] = []
    while True:
        try:
            items.append(q.get_nowait())
        except queue.Empty:
            return items
