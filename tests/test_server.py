"""Integration tests for ChatServer over real localhost TCP sockets.

OWNER: Yusuf. Scenarios: T-04 (broadcast), T-05 (private / unknown user), T-06 (duplicate
username), T-07 (CHAT without HELLO), plus PING, BYE, abrupt disconnect and stop().
Every server listens on port 0 so parallel runs never collide (D-15).
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

import pytest

import socketlink.server.server as server_module
from socketlink.common.config import ServerConfig
from socketlink.common.constants import (
    ByeReason,
    DisconnectReason,
    ErrorCode,
    MessageType,
    TransportMode,
)
from socketlink.common.events import Event, EventBus, EventType
from socketlink.common.exceptions import (
    ConnectionClosedError,
    TransportTimeoutError,
    ValidationError,
)
from socketlink.common.protocol import (
    Packet,
    make_bye,
    make_chat,
    make_file_chunk,
    make_file_end,
    make_file_start,
    make_hello,
    make_ping,
    make_transfer_id,
    parse_file_chunk,
)
from socketlink.common.transport import TcpTransport, Transport
from socketlink.reliability.reliable_udp import ReliableUdpTransport
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


def receive_type(transport: Transport, wanted: MessageType) -> Packet:
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


def test_bye_survives_unread_client_data(env: Env) -> None:
    """The client still has packets in flight when the server stops: no RST, BYE arrives."""
    alice = env.join("alice")
    for _ in range(50):
        alice.send(make_ping())
    env.server.stop()
    while True:  # ConnectionClosedError here means the BYE was lost
        packet = alice.receive(timeout=WAIT)
        if packet.type is MessageType.BYE:
            assert packet.json_payload()["reason"] == "server_shutdown"
            return


def test_server_waits_for_the_client_to_close_after_bye(env: Env) -> None:
    alice = env.join("alice")
    stopper = threading.Thread(target=env.server.stop)
    stopper.start()
    receive_type(alice, MessageType.BYE)
    deadline = time.monotonic() + 0.3
    while True:  # still open: the server drains, it does not hang up (ConnectionClosedError fails)
        try:
            alice.receive(timeout=max(deadline - time.monotonic(), 0.01))
        except TransportTimeoutError:
            break
    alice.close()
    stopper.join(timeout=WAIT)
    assert not stopper.is_alive()
    wait_for_event(env.events, EventType.SERVER_STOPPED)


def test_welcome_is_the_first_packet_even_during_a_broadcast(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    alice = env.join("alice")
    original = server_module.make_welcome

    def slow_welcome(client_id: int, server_name: str, users: list[str]) -> Packet:
        time.sleep(0.5)  # the newcomer is already registered while its WELCOME is delayed
        return original(client_id, server_name, users)

    monkeypatch.setattr(server_module, "make_welcome", slow_welcome)
    late = env.connect()
    late.send(make_hello("late"))
    deadline = time.monotonic() + WAIT
    while "late" not in [c.username for c in env.server.get_clients()]:
        assert time.monotonic() < deadline, "late was never registered"
        time.sleep(0.01)
    alice.send(make_chat("said while late is joining"))
    receive_type(alice, MessageType.CHAT)
    assert late.receive(timeout=WAIT).type is MessageType.WELCOME
    # late is registered, so it gets the message too, but only after its WELCOME
    said = receive_type(late, MessageType.CHAT).json_payload()["text"]
    assert said == "said while late is joining"


def test_private_message_during_registration_is_not_lost(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A message sent right after the newcomer is registered must arrive, not UNKNOWN_USER."""
    alice = env.join("alice")
    original = server_module.make_welcome

    def slow_welcome(client_id: int, server_name: str, users: list[str]) -> Packet:
        time.sleep(0.5)  # WELCOME is still on its way, the client is already registered
        return original(client_id, server_name, users)

    monkeypatch.setattr(server_module, "make_welcome", slow_welcome)
    late = env.connect()
    late.send(make_hello("late"))
    deadline = time.monotonic() + WAIT
    while "late" not in [c.username for c in env.server.get_clients()]:
        assert time.monotonic() < deadline, "late was never registered"
        time.sleep(0.01)
    alice.send(make_chat("psst", to="late"))
    assert late.receive(timeout=WAIT).type is MessageType.WELCOME
    assert receive_type(late, MessageType.CHAT).json_payload()["text"] == "psst"
    for _ in range(3):  # alice must have gotten her own copy and no UNKNOWN_USER error
        try:
            packet = alice.receive(timeout=QUIET)
        except TransportTimeoutError:
            break
        assert packet.type is not MessageType.ERROR


def test_five_malformed_packets_in_a_row_close_the_connection(env: Env) -> None:
    alice = env.join("alice")
    for _ in range(5):
        alice.send(Packet(MessageType.CHAT, payload=b"not json"))
    errors = 0
    with pytest.raises(ConnectionClosedError):
        while True:
            if alice.receive(timeout=WAIT).type is MessageType.ERROR:
                errors += 1
    assert errors == 5
    left = wait_for_event(env.events, EventType.CLIENT_LEFT)
    assert left.data["reason"] == DisconnectReason.REJECTED.value


def test_a_valid_packet_resets_the_malformed_counter(env: Env) -> None:
    alice = env.join("alice")
    for _ in range(2):
        for _ in range(4):
            alice.send(Packet(MessageType.CHAT, payload=b"not json"))
        alice.send(make_ping())
        receive_type(alice, MessageType.PONG)
    alice.send(make_ping())
    receive_type(alice, MessageType.PONG)  # 8 bad packets in total, still connected


def test_watchdog_disconnects_a_silent_client(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server_module, "CONNECTION_TIMEOUT", 0.5)
    alice = env.join("alice")
    bye = receive_type(alice, MessageType.BYE)
    assert bye.json_payload()["reason"] == "timeout"
    left = wait_for_event(env.events, EventType.CLIENT_LEFT)
    assert left.data == {"username": "alice", "reason": DisconnectReason.TIMEOUT.value}


def test_watchdog_keeps_a_client_that_sends_pings(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server_module, "CONNECTION_TIMEOUT", 1.0)
    alice = env.join("alice")
    for _ in range(6):
        alice.send(make_ping())
        receive_type(alice, MessageType.PONG)
        time.sleep(0.4)
    assert [c.username for c in env.server.get_clients()] == ["alice"]


def test_kick_sends_bye_and_removes_the_client(env: Env) -> None:
    alice, bob = env.join("alice"), env.join("bob")
    env.server.kick("ALICE")
    bye = receive_type(alice, MessageType.BYE)
    assert bye.json_payload()["reason"] == "kicked_by_admin"
    left = wait_for_event(env.events, EventType.CLIENT_LEFT)
    assert left.data == {"username": "alice", "reason": DisconnectReason.KICKED_BY_ADMIN.value}
    while receive_type(bob, MessageType.USER_LIST).json_payload()["users"] != ["bob"]:
        pass


def test_kick_of_an_unknown_user_is_ignored(env: Env) -> None:
    env.server.kick("nobody")
    assert env.server.get_clients() == []


def test_get_stats_counts_traffic_and_keeps_clients_that_left(env: Env) -> None:
    alice = env.join("alice")
    for _ in range(3):
        alice.send(make_ping())
        receive_type(alice, MessageType.PONG)
    stats = env.server.get_stats()
    assert stats["packets_received"] >= 4  # HELLO and three PINGs
    assert stats["packets_sent"] >= 4      # WELCOME, USER_LIST and PONGs
    assert "avg_rtt_ms" in stats
    alice.send(make_bye())
    wait_for_event(env.events, EventType.CLIENT_LEFT)
    assert env.server.get_stats()["packets_received"] > stats["packets_received"]


def test_stats_updated_is_published_by_the_watchdog(env: Env) -> None:
    event = wait_for_event(env.events, EventType.STATS_UPDATED)
    event.validate()
    assert "packets_sent" in event.data["stats"]


def test_set_network_conditions_is_validated_and_ignored_by_tcp(env: Env) -> None:
    env.join("alice")
    env.server.set_network_conditions(0.2, 50)  # TCP: accepted, nothing to simulate
    for loss_rate, delay_ms in ((0.9, 0), (-0.1, 0), (0.1, 5000), (0.1, -1)):
        with pytest.raises(ValidationError):
            env.server.set_network_conditions(loss_rate, delay_ms)


def test_udp_transports_get_network_conditions_and_window_size() -> None:
    environment = start_env(
        ServerConfig(host=HOST, port=0, mode=TransportMode.UDP, window_size=2)
    )
    clients: list[ReliableUdpTransport] = []
    try:
        alice = ReliableUdpTransport.connect(HOST, environment.port)
        clients.append(alice)
        alice.send(make_hello("alice"))
        receive_type(alice, MessageType.WELCOME)
        environment.server.set_network_conditions(0.25, 20)
        server_side = environment.server._clients["alice"].transport
        assert isinstance(server_side, ReliableUdpTransport)
        assert (server_side.loss_simulator.loss_rate, server_side.loss_simulator.delay_ms) == (
            0.25,
            20,
        )
        assert server_side._window_size == 2
        # A client that connects later gets the current delay (loss reset to keep this fast).
        environment.server.set_network_conditions(0.0, 20)
        bob = ReliableUdpTransport.connect(HOST, environment.port)
        clients.append(bob)
        bob.send(make_hello("bob"))
        receive_type(bob, MessageType.WELCOME)
        later = environment.server._clients["bob"].transport
        assert isinstance(later, ReliableUdpTransport)
        assert later.loss_simulator.delay_ms == 20
        assert later._window_size == 2
    finally:
        for client in clients:
            client.close()
        environment.server.stop()


# ---- file relay (PROTOCOL.md 5.4) ----------------------------------------------------------
FILE_TYPES = (MessageType.FILE_START, MessageType.FILE_CHUNK, MessageType.FILE_END)


def join_as(env: Env, username: str) -> tuple[TcpTransport, int]:
    """Like env.join, but also return the client_id from the WELCOME."""
    transport = env.connect()
    transport.send(make_hello(username))
    welcome = receive_type(transport, MessageType.WELCOME)
    return transport, welcome.json_payload()["client_id"]


def receive_file_packet(transport: Transport) -> Packet:
    """Next FILE_* packet; other packets (USER_LIST updates...) are skipped."""
    deadline = time.monotonic() + WAIT
    while True:
        packet = transport.receive(timeout=max(deadline - time.monotonic(), 0.01))
        if packet.type in FILE_TYPES:
            return packet


def expect_no_file_packet(transport: Transport) -> None:
    deadline = time.monotonic() + QUIET
    while True:
        try:
            packet = transport.receive(timeout=max(deadline - time.monotonic(), 0.01))
        except TransportTimeoutError:
            return
        assert packet.type not in FILE_TYPES


def error_code(transport: Transport) -> str:
    return receive_type(transport, MessageType.ERROR).json_payload()["code"]


def start_transfer(sender: Transport, transfer_id: int, to: str | None) -> None:
    sender.send(make_file_start(transfer_id, "a.txt", 3, 1, 0, to=to))


def test_file_is_relayed_to_the_recipient_with_the_sender_added(env: Env) -> None:
    alice, alice_id = join_as(env, "alice")
    bob, _ = join_as(env, "bob")
    carol, _ = join_as(env, "carol")
    transfer_id = make_transfer_id(alice_id, 1)
    start_transfer(alice, transfer_id, "bob")
    alice.send(make_file_chunk(transfer_id, 0, b"abc"))
    alice.send(make_file_end(transfer_id))
    start = receive_file_packet(bob)
    assert start.type is MessageType.FILE_START
    fields = start.json_payload()
    assert (fields["from"], fields["to"], fields["transfer_id"]) == ("alice", "bob", transfer_id)
    assert (fields["filename"], fields["size"], fields["total_chunks"]) == ("a.txt", 3, 1)
    chunk = receive_file_packet(bob)
    assert parse_file_chunk(chunk) == (transfer_id, 0, b"abc")
    end = receive_file_packet(bob)
    assert end.type is MessageType.FILE_END
    assert end.json_payload()["transfer_id"] == transfer_id
    expect_no_file_packet(carol)  # the server relays to the recipient only
    expect_no_file_packet(alice)


def test_two_senders_to_the_same_recipient_do_not_mix(env: Env) -> None:
    alice, alice_id = join_as(env, "alice")
    carol, carol_id = join_as(env, "carol")
    bob, _ = join_as(env, "bob")
    first, second = make_transfer_id(alice_id, 1), make_transfer_id(carol_id, 1)
    start_transfer(alice, first, "bob")
    start_transfer(carol, second, "bob")
    alice.send(make_file_chunk(first, 0, b"from alice"))
    carol.send(make_file_chunk(second, 0, b"from carol"))
    alice.send(make_file_end(first))
    carol.send(make_file_end(second))
    chunks: dict[int, bytes] = {}
    ends: set[int] = set()
    starters: dict[int, str] = {}
    for _ in range(6):
        packet = receive_file_packet(bob)
        if packet.type is MessageType.FILE_START:
            fields = packet.json_payload()
            starters[fields["transfer_id"]] = fields["from"]
        elif packet.type is MessageType.FILE_CHUNK:
            tid, _index, data = parse_file_chunk(packet)
            chunks[tid] = data
        else:
            ends.add(packet.json_payload()["transfer_id"])
    assert starters == {first: "alice", second: "carol"}
    assert chunks == {first: b"from alice", second: b"from carol"}
    assert ends == {first, second}


def test_file_start_without_a_recipient_is_rejected(env: Env) -> None:
    alice, alice_id = join_as(env, "alice")
    start_transfer(alice, make_transfer_id(alice_id, 1), None)
    assert error_code(alice) == ErrorCode.FILE_REJECTED.value
    start_transfer(alice, make_transfer_id(alice_id, 2), "")
    assert error_code(alice) == ErrorCode.FILE_REJECTED.value


def test_file_start_to_an_unknown_user_is_reported(env: Env) -> None:
    alice, alice_id = join_as(env, "alice")
    start_transfer(alice, make_transfer_id(alice_id, 1), "nobody")
    assert error_code(alice) == ErrorCode.UNKNOWN_USER.value
    assert env.server._transfers == {}


def test_file_that_is_too_large_is_rejected(env: Env) -> None:
    alice, alice_id = join_as(env, "alice")
    bob, _ = join_as(env, "bob")
    too_large = server_module.MAX_FILE_SIZE + 1
    alice.send(make_file_start(make_transfer_id(alice_id, 1), "big", too_large, 1, 0, to="bob"))
    assert error_code(alice) == ErrorCode.FILE_REJECTED.value
    expect_no_file_packet(bob)


def test_a_transfer_id_of_another_client_is_rejected(env: Env) -> None:
    alice, alice_id = join_as(env, "alice")
    bob, bob_id = join_as(env, "bob")
    carol, _ = join_as(env, "carol")
    start_transfer(alice, make_transfer_id(bob_id, 1), "carol")  # not alice's id range
    assert error_code(alice) == ErrorCode.FILE_REJECTED.value
    # carol cannot push chunks into alice's running transfer either
    mine = make_transfer_id(alice_id, 1)
    start_transfer(alice, mine, "bob")
    assert receive_file_packet(bob).type is MessageType.FILE_START
    carol.send(make_file_chunk(mine, 0, b"hijack"))
    assert error_code(carol) == ErrorCode.FILE_REJECTED.value
    carol.send(make_file_end(mine))
    assert error_code(carol) == ErrorCode.FILE_REJECTED.value
    expect_no_file_packet(bob)
    assert mine in env.server._transfers  # still running, untouched


def test_chunks_of_an_unknown_transfer_are_dropped_silently(env: Env) -> None:
    alice, alice_id = join_as(env, "alice")
    bob, _ = join_as(env, "bob")
    unknown = make_transfer_id(alice_id, 9)
    alice.send(make_file_chunk(unknown, 0, b"x"))
    alice.send(make_file_end(unknown))
    alice.send(make_ping())
    receive_type(alice, MessageType.PONG)  # the server is still fine and sent no ERROR
    expect_no_file_packet(bob)


def test_a_running_transfer_id_cannot_be_started_twice(env: Env) -> None:
    alice, alice_id = join_as(env, "alice")
    bob, _ = join_as(env, "bob")
    transfer_id = make_transfer_id(alice_id, 1)
    start_transfer(alice, transfer_id, "bob")
    assert receive_file_packet(bob).type is MessageType.FILE_START
    start_transfer(alice, transfer_id, "bob")
    assert error_code(alice) == ErrorCode.FILE_REJECTED.value


def test_file_end_forgets_the_transfer(env: Env) -> None:
    alice, alice_id = join_as(env, "alice")
    bob, _ = join_as(env, "bob")
    transfer_id = make_transfer_id(alice_id, 1)
    start_transfer(alice, transfer_id, "bob")
    alice.send(make_file_end(transfer_id))
    assert receive_file_packet(bob).type is MessageType.FILE_START
    assert receive_file_packet(bob).type is MessageType.FILE_END
    alice.send(make_file_chunk(transfer_id, 1, b"late"))  # no record any more: dropped
    expect_no_file_packet(bob)
    assert env.server._transfers == {}
    start_transfer(alice, transfer_id, "bob")  # the id can be used again
    assert receive_file_packet(bob).type is MessageType.FILE_START


@pytest.mark.parametrize("leaver", ["alice", "bob"])
def test_transfers_are_forgotten_when_the_sender_or_recipient_leaves(
    env: Env, leaver: str
) -> None:
    alice, alice_id = join_as(env, "alice")
    bob, _ = join_as(env, "bob")
    start_transfer(alice, make_transfer_id(alice_id, 1), "bob")
    assert receive_file_packet(bob).type is MessageType.FILE_START
    assert len(env.server._transfers) == 1
    {"alice": alice, "bob": bob}[leaver].send(make_bye(ByeReason.CLIENT_QUIT))
    wait_for_event(env.events, EventType.CLIENT_LEFT, lambda e: e.data["username"] == leaver)
    assert env.server._transfers == {}


def test_client_ids_start_again_at_one_after_65535(env: Env) -> None:
    env.server._next_client_id = 0xFFFF
    _, last = join_as(env, "alice")
    _, wrapped = join_as(env, "bob")
    assert (last, wrapped) == (0xFFFF, 1)
