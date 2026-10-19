"""Integration tests for ChatServer over real localhost TCP sockets.

OWNER: Yusuf. Scenarios: T-04 (broadcast), T-05 (private / unknown user), T-06 (duplicate
username), T-07 (CHAT without HELLO), plus PING, BYE, abrupt disconnect and stop().
Every server listens on port 0 so parallel runs never collide (D-15).
"""

from __future__ import annotations

import queue
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import pytest

from socketlink.common.config import ServerConfig
from socketlink.common.constants import DisconnectReason, ErrorCode, MessageType
from socketlink.common.events import Event, EventBus, EventType
from socketlink.common.exceptions import ConnectionClosedError, TransportTimeoutError
from socketlink.common.protocol import (
    Packet,
    make_bye,
    make_chat,
    make_hello,
    make_ping,
)
from socketlink.common.transport import TcpTransport
from socketlink.server.server import ChatServer

pytestmark = pytest.mark.integration

HOST = "127.0.0.1"
WAIT = 3.0    # seconds to wait for something that must happen
QUIET = 0.5   # seconds to wait when asserting that something does NOT happen


def wait_for_event(
    events: queue.Queue[Event],
    event_type: EventType,
    predicate: Callable[[Event], bool] | None = None,
) -> Event:
    """First event of `event_type` (passing `predicate`); other events are skipped."""
    deadline = time.monotonic() + WAIT
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"no {event_type.name} event within {WAIT} s")
        try:
            event = events.get(timeout=remaining)
        except queue.Empty:
            raise TimeoutError(f"no {event_type.name} event within {WAIT} s") from None
        if event.type is event_type and (predicate is None or predicate(event)):
            return event


def receive_type(transport: TcpTransport, wanted: MessageType) -> Packet:
    """Next packet of type `wanted`; other packets (USER_LIST updates...) are skipped."""
    deadline = time.monotonic() + WAIT
    while True:
        packet = transport.receive(timeout=max(deadline - time.monotonic(), 0.01))
        if packet.type is wanted:
            return packet


def expect_no_chat(transport: TcpTransport) -> None:
    """Assert that no CHAT packet arrives within QUIET seconds."""
    deadline = time.monotonic() + QUIET
    while True:
        try:
            packet = transport.receive(timeout=max(deadline - time.monotonic(), 0.01))
        except TransportTimeoutError:
            return
        assert packet.type is not MessageType.CHAT


@dataclass
class Env:
    """A running server plus helpers to open clients against it."""

    server: ChatServer
    port: int
    events: queue.Queue[Event]
    _opened: list[TcpTransport] = field(default_factory=list)

    def connect(self) -> TcpTransport:
        """A raw TCP connection, no HELLO sent."""
        transport = TcpTransport.connect(HOST, self.port)
        self._opened.append(transport)
        return transport

    def join(self, username: str) -> TcpTransport:
        """Connect, send HELLO and wait for the WELCOME."""
        transport = self.connect()
        transport.send(make_hello(username))
        receive_type(transport, MessageType.WELCOME)
        return transport

    def close_clients(self) -> None:
        for transport in self._opened:
            transport.close()


def start_env(config: ServerConfig) -> Env:
    bus = EventBus()
    events = bus.subscribe_queue()
    server = ChatServer(bus, config)
    server.start()
    port = wait_for_event(events, EventType.SERVER_STARTED).data["port"]
    return Env(server, port, events)


@pytest.fixture
def env() -> Iterator[Env]:
    environment = start_env(ServerConfig(host=HOST, port=0))
    yield environment
    environment.close_clients()
    environment.server.stop()


def test_start_publishes_the_real_port(env: Env) -> None:
    assert env.port != 0
    assert env.server.is_running


def test_hello_gets_welcome_then_user_list(env: Env) -> None:
    alice = env.connect()
    alice.send(make_hello("alice"))
    welcome = alice.receive(timeout=WAIT)
    assert welcome.type is MessageType.WELCOME
    assert welcome.json_payload()["users"] == ["alice"]
    assert isinstance(welcome.json_payload()["client_id"], int)
    assert alice.receive(timeout=WAIT).json_payload()["users"] == ["alice"]
    joined = wait_for_event(env.events, EventType.CLIENT_JOINED)
    assert joined.data["username"] == "alice"
    joined.validate()


def test_existing_clients_get_a_new_user_list_when_someone_joins(env: Env) -> None:
    alice = env.join("alice")
    env.join("bob")
    while True:
        users = receive_type(alice, MessageType.USER_LIST).json_payload()["users"]
        if users == ["alice", "bob"]:
            break


def test_duplicate_username_is_rejected_ignoring_case(env: Env) -> None:
    """T-06."""
    env.join("Alice")
    second = env.connect()
    second.send(make_hello("alice"))
    error = receive_type(second, MessageType.ERROR)
    assert error.json_payload()["code"] == ErrorCode.USERNAME_TAKEN.value
    with pytest.raises(ConnectionClosedError):
        second.receive(timeout=WAIT)


def test_invalid_username_is_rejected(env: Env) -> None:
    client = env.connect()
    client.send(make_hello("a!"))
    error = receive_type(client, MessageType.ERROR)
    assert error.json_payload()["code"] == ErrorCode.INVALID_USERNAME.value


def test_chat_without_hello_is_rejected_and_closed(env: Env) -> None:
    """T-07."""
    client = env.connect()
    client.send(make_chat("hi"))
    error = receive_type(client, MessageType.ERROR)
    assert error.json_payload()["code"] == ErrorCode.NOT_AUTHENTICATED.value
    with pytest.raises(ConnectionClosedError):
        client.receive(timeout=WAIT)


def test_server_full_is_reported() -> None:
    environment = start_env(ServerConfig(host=HOST, port=0, max_clients=1))
    try:
        environment.join("alice")
        second = environment.connect()
        second.send(make_hello("bob"))
        error = receive_type(second, MessageType.ERROR)
        assert error.json_payload()["code"] == ErrorCode.SERVER_FULL.value
    finally:
        environment.close_clients()
        environment.server.stop()


def test_broadcast_reaches_everyone_in_order(env: Env) -> None:
    """T-04: all clients, the sender included, receive the same messages in the same order."""
    alice, bob, carol = env.join("alice"), env.join("bob"), env.join("carol")
    sent = [f"message {i}" for i in range(5)]
    for text in sent:
        alice.send(make_chat(text))
    for client in (alice, bob, carol):
        received = [receive_type(client, MessageType.CHAT).json_payload() for _ in sent]
        assert [chat["text"] for chat in received] == sent
        assert all(chat["from"] == "alice" and "timestamp" in chat for chat in received)


def test_private_message_reaches_only_target_and_sender(env: Env) -> None:
    """T-05 (first half)."""
    alice, bob, carol = env.join("alice"), env.join("bob"), env.join("carol")
    alice.send(make_chat("secret", to="bob"))
    assert receive_type(bob, MessageType.CHAT).json_payload()["text"] == "secret"
    assert receive_type(alice, MessageType.CHAT).json_payload()["text"] == "secret"
    expect_no_chat(carol)


def test_private_message_to_unknown_user_is_reported(env: Env) -> None:
    """T-05 (second half)."""
    alice = env.join("alice")
    alice.send(make_chat("hello?", to="nobody"))
    error = receive_type(alice, MessageType.ERROR)
    assert error.json_payload()["code"] == ErrorCode.UNKNOWN_USER.value


def test_private_message_to_yourself_arrives_once(env: Env) -> None:
    alice = env.join("alice")
    alice.send(make_chat("note to self", to="ALICE"))
    receive_type(alice, MessageType.CHAT)
    expect_no_chat(alice)


def test_ping_is_answered_with_pong(env: Env) -> None:
    alice = env.join("alice")
    alice.send(make_ping())
    assert receive_type(alice, MessageType.PONG).type is MessageType.PONG


def test_bad_chat_payload_is_reported_and_the_client_stays(env: Env) -> None:
    alice = env.join("alice")
    alice.send(Packet(MessageType.CHAT, payload=b"this is not json"))
    error = receive_type(alice, MessageType.ERROR)
    assert error.json_payload()["code"] == ErrorCode.MALFORMED_PACKET.value
    alice.send(make_ping())
    receive_type(alice, MessageType.PONG)


def test_bye_removes_the_client_with_reason_user(env: Env) -> None:
    alice, bob = env.join("alice"), env.join("bob")
    bob.send(make_bye())
    left = wait_for_event(env.events, EventType.CLIENT_LEFT)
    assert left.data == {"username": "bob", "reason": DisconnectReason.USER.value}
    while True:
        if receive_type(alice, MessageType.USER_LIST).json_payload()["users"] == ["alice"]:
            break


def test_connection_drop_without_bye_is_connection_lost(env: Env) -> None:
    bob = env.join("bob")
    wait_for_event(env.events, EventType.CLIENT_JOINED)
    bob.close()
    left = wait_for_event(env.events, EventType.CLIENT_LEFT)
    assert left.data["reason"] == DisconnectReason.CONNECTION_LOST.value
    assert env.server.get_clients() == []


def test_get_clients_lists_registered_clients(env: Env) -> None:
    env.join("alice")
    env.join("bob")
    wait_for_event(env.events, EventType.CLIENT_JOINED, lambda e: e.data["username"] == "bob")
    assert sorted(c.username for c in env.server.get_clients()) == ["alice", "bob"]


def test_stop_says_bye_to_everyone_and_publishes_server_stopped(env: Env) -> None:
    alice, bob = env.join("alice"), env.join("bob")
    env.server.stop()
    for client in (alice, bob):
        bye = receive_type(client, MessageType.BYE)
        assert bye.json_payload()["reason"] == "server_shutdown"
    stopped = wait_for_event(env.events, EventType.SERVER_STOPPED)
    assert stopped.data["reason"] == DisconnectReason.USER.value
    assert not env.server.is_running
    assert env.server.get_clients() == []


def test_stop_is_idempotent_and_safe_before_start() -> None:
    server = ChatServer(EventBus(), ServerConfig(host=HOST, port=0))
    server.stop()
    server.stop()
    assert not server.is_running
