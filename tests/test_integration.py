"""End-to-end tests: a real ChatServer and three real ChatClients over localhost.

OWNER: Meryem
Scenarios: T-04 (broadcast), T-05 (private message). Run in TCP and UDP mode.
"""

from __future__ import annotations

import queue
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest

from socketlink.client.client import ChatClient
from socketlink.common.config import ClientConfig
from socketlink.common.constants import TransportMode
from socketlink.common.events import Event, EventBus, EventType
from tests.conftest import RunningServer, wait_for_event

pytestmark = pytest.mark.integration

BOTH_MODES = pytest.mark.parametrize(
    "running_server", [TransportMode.TCP, TransportMode.UDP], indirect=True, ids=["tcp", "udp"]
)
QUIET_PERIOD = 0.5  # seconds to wait when asserting that something does NOT arrive


@dataclass(frozen=True)
class Peer:
    """One connected client with the queue that receives its events."""

    name: str
    client: ChatClient
    events: queue.Queue[Event]


ConnectPeer = Callable[[str], Peer]


@pytest.fixture
def connect_peer(running_server: RunningServer) -> Iterator[ConnectPeer]:
    """Factory: connect_peer("alice") -> Peer, already CONNECTED. Disconnects on teardown."""
    peers: list[Peer] = []

    def _connect(username: str) -> Peer:
        bus = EventBus()
        events = bus.subscribe_queue()
        config = ClientConfig(
            host=running_server.host,
            port=running_server.port,
            mode=running_server.mode,
            username=username,
            auto_reconnect=False,
        )
        client = ChatClient(bus, config)
        client.connect()
        wait_for_event(events, EventType.CONNECTED)
        peer = Peer(username, client, events)
        peers.append(peer)
        return peer

    yield _connect
    for peer in peers:
        try:
            peer.client.disconnect()
        except Exception:  # noqa: BLE001 - teardown must not hide the real test failure
            pass


def _texts_received(peer: Peer, count: int) -> list[str]:
    return [
        wait_for_event(peer.events, EventType.MESSAGE_RECEIVED).data["text"] for _ in range(count)
    ]


def _wait_until_listed(*peers: Peer) -> None:
    """Wait until every peer has seen the full user list.

    The server lists a user only once it can receive messages, and it skips users that are
    not ready yet when it broadcasts. A message sent right after connect() could otherwise
    be rejected (UNKNOWN_USER) or silently not delivered.
    """
    everyone = {peer.name for peer in peers}
    for peer in peers:
        wait_for_event(
            peer.events,
            EventType.USER_LIST_UPDATED,
            predicate=lambda e: set(e.data["users"]) == everyone,
        )


@BOTH_MODES
def test_three_clients_see_each_other(connect_peer: ConnectPeer) -> None:
    alice, bob, carol = (connect_peer(n) for n in ("alice", "bob", "carol"))
    everyone = {"alice", "bob", "carol"}
    for peer in (alice, bob, carol):
        event = wait_for_event(
            peer.events,
            EventType.USER_LIST_UPDATED,
            predicate=lambda e: set(e.data["users"]) == everyone,
        )
        assert set(event.data["users"]) == everyone


@BOTH_MODES
def test_broadcast_reaches_everyone_in_order(connect_peer: ConnectPeer) -> None:
    """T-04: all clients receive the same messages in the same order."""
    alice, bob, carol = (connect_peer(n) for n in ("alice", "bob", "carol"))
    _wait_until_listed(alice, bob, carol)
    sent = [f"message {i}" for i in range(5)]
    for text in sent:
        alice.client.send_chat(text)
    assert _texts_received(bob, len(sent)) == sent
    assert _texts_received(carol, len(sent)) == sent


@BOTH_MODES
def test_private_message_reaches_only_the_target(connect_peer: ConnectPeer) -> None:
    """T-05 (first half): only the addressed user receives a private message."""
    alice, bob, carol = (connect_peer(n) for n in ("alice", "bob", "carol"))
    _wait_until_listed(alice, bob, carol)
    alice.client.send_chat("secret", to="bob")
    event = wait_for_event(bob.events, EventType.MESSAGE_RECEIVED)
    assert event.data["text"] == "secret"
    with pytest.raises(TimeoutError):
        wait_for_event(carol.events, EventType.MESSAGE_RECEIVED, timeout=QUIET_PERIOD)
