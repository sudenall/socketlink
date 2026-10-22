"""Tests for ChatClient against a small fake server built on TcpListener.

OWNER: Hamit
Scenarios: T-08 (closed server), T-09 (server goes down -> RECONNECTING), handshake,
chat, heartbeat/RTT, silent server, kick, protocol errors, invalid states, and file
transfer (H5) through a fake relay that follows PROTOCOL.md 5.4.

The fake server is defined here (not the real ChatServer) so these tests only depend
on the protocol and transport, which are already on main. Every test listens on port 0
(D-15). Timing constants are shortened with monkeypatch so the suite stays fast.
Shared helpers (event_bus, event_queue, wait_for_event) come from conftest.py.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from socketlink.client import client as client_module
from socketlink.client.client import ChatClient
from socketlink.common import protocol as p
from socketlink.common.config import ClientConfig
from socketlink.common.constants import (
    ByeReason,
    ClientErrorCode,
    ConnectionState,
    DisconnectReason,
    ErrorCode,
    FileFailReason,
    MessageType,
    TransportMode,
)
from socketlink.common.events import Event, EventBus, EventType
from socketlink.common.exceptions import (
    BadChecksumError,
    ConnectionClosedError,
    InvalidStateError,
    MalformedPacketError,
    TransportTimeoutError,
    ValidationError,
)
from socketlink.common.transport import TcpListener, TcpTransport, Transport
from tests.conftest import wait_for_event

pytestmark = pytest.mark.integration

HOST = "127.0.0.1"
USERNAME = "hamit"
EVENT_TIMEOUT = 5.0


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def wait_for(q: queue.Queue[Event], event_type: EventType, timeout: float = EVENT_TIMEOUT,
             predicate: Callable[[Event], bool] | None = None) -> Event:
    return wait_for_event(q, event_type, timeout, predicate)


def wait_for_state(q: queue.Queue[Event], state: ConnectionState,
                   timeout: float = EVENT_TIMEOUT) -> Event:
    return wait_for(q, EventType.STATE_CHANGED, timeout, lambda e: e.data["new"] is state)


def wait_until(condition: Callable[[], bool], timeout: float = EVENT_TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(0.02)


class FakeServer:
    """Minimal server: answers HELLO, echoes CHAT, answers PING (unless silent) and
    relays FILE_* like PROTOCOL.md 5.4 (FILE_START to `to`, adds "from"; FILE_CHUNK and
    FILE_END follow the transfer_id recorded at FILE_START).

    `reject_code` makes it answer HELLO with ERROR; `answer_hello=False` makes it
    never answer; `silent=True` makes it ignore PINGs after the handshake.
    `drop_sender_after_chunks=n` closes the sender's connection when its n-th chunk
    arrives; `drop_target_after_chunks=n` closes the receiver's connection instead of
    forwarding the n-th chunk.
    """

    def __init__(self, reject_code: str | None = None, answer_hello: bool = True,
                 silent: bool = False, drop_sender_after_chunks: int | None = None,
                 drop_target_after_chunks: int | None = None) -> None:
        self.reject_code = reject_code
        self.answer_hello = answer_hello
        self.silent = silent
        self.drop_sender_after_chunks = drop_sender_after_chunks
        self.drop_target_after_chunks = drop_target_after_chunks
        self.listener = TcpListener()
        self.received: list[p.Packet] = []
        self.connections: list[Transport] = []
        self.accepted = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._next_client_id = 7
        self._users: dict[str, Transport] = {}         # lower-cased username -> transport
        self._names: dict[Transport, str] = {}
        self._routes: dict[int, Transport] = {}        # transfer_id -> receiver
        self._chunks_seen: dict[int, int] = {}         # transfer_id -> chunks relayed

    @property
    def port(self) -> int:
        return self.listener.bound_address[1]

    def start(self) -> FakeServer:
        self.listener.start(HOST, 0)
        threading.Thread(target=self._accept_loop, daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self.listener.close()
        self.drop_clients()

    def drop_clients(self) -> None:
        """Close every client connection but keep listening (server-side crash)."""
        with self._lock:
            connections = list(self.connections)
        for transport in connections:
            transport.close()

    def send_to_all(self, packet: p.Packet) -> None:
        with self._lock:
            connections = list(self.connections)
        for transport in connections:
            transport.send(packet)

    def types_received(self) -> list[MessageType]:
        with self._lock:
            return [packet.type for packet in self.received]

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                transport = self.listener.accept(timeout=0.1)
            except TransportTimeoutError:
                continue
            except ConnectionClosedError:
                return
            with self._lock:
                self.connections.append(transport)
            self.accepted.set()
            threading.Thread(target=self._serve, args=(transport,), daemon=True).start()

    def _serve(self, transport: Transport) -> None:
        while not self._stop.is_set():
            try:
                packet = transport.receive(timeout=0.1)
            except TransportTimeoutError:
                continue
            except Exception:  # the fake server just stops serving this client
                return
            with self._lock:
                self.received.append(packet)
            try:
                self._answer(transport, packet)
            except ConnectionClosedError:
                return

    def _answer(self, transport: Transport, packet: p.Packet) -> None:
        if packet.type is MessageType.HELLO:
            if not self.answer_hello:
                return
            if self.reject_code is not None:
                transport.send(p.make_error(self.reject_code, "rejected by fake server"))
                transport.close()
                return
            username = packet.json_payload()["username"]
            with self._lock:
                client_id = self._next_client_id
                self._next_client_id += 1
                self._users[username.lower()] = transport
                self._names[transport] = username
            transport.send(p.make_welcome(client_id, "Fake", [username]))
            transport.send(p.make_user_list([username]))
        elif packet.type in (MessageType.FILE_START, MessageType.FILE_CHUNK,
                             MessageType.FILE_END):
            self._relay_file_packet(transport, packet)
        elif packet.type is MessageType.CHAT:
            payload = packet.json_payload()
            transport.send(p.make_chat(payload["text"], payload["to"], sender=USERNAME,
                                       timestamp=time.time()))
        elif packet.type is MessageType.PING and not self.silent:
            transport.send(p.make_pong())
        elif packet.type is MessageType.BYE:
            transport.close()

    def _relay_file_packet(self, transport: Transport, packet: p.Packet) -> None:
        if packet.type is MessageType.FILE_START:
            fields = packet.json_payload()
            with self._lock:
                target = self._users.get(str(fields["to"]).lower())
                sender = self._names.get(transport, "")
                if target is not None:
                    self._routes[fields["transfer_id"]] = target
                    self._chunks_seen[fields["transfer_id"]] = 0
            if target is None:
                transport.send(p.make_error(ErrorCode.UNKNOWN_USER.value, "no such user"))
                return
            target.send(p.make_file_start(
                fields["transfer_id"], fields["filename"], fields["size"],
                fields["total_chunks"], fields["checksum"], to=fields["to"], sender=sender,
            ))
            return
        if packet.type is MessageType.FILE_CHUNK:
            transfer_id = p.parse_file_chunk(packet)[0]
        else:
            transfer_id = packet.json_payload()["transfer_id"]
        with self._lock:
            target = self._routes.get(transfer_id)
            if packet.type is MessageType.FILE_CHUNK and target is not None:
                self._chunks_seen[transfer_id] += 1
            seen = self._chunks_seen.get(transfer_id, 0)
            if packet.type is MessageType.FILE_END:
                self._routes.pop(transfer_id, None)
        if target is None:
            return
        if packet.type is MessageType.FILE_CHUNK:
            if seen == self.drop_sender_after_chunks:
                transport.close()
                return
            if seen == self.drop_target_after_chunks:
                target.close()
                return
        try:
            target.send(packet)
        except ConnectionClosedError:
            pass  # receiver already gone


# A connect attempt to a closed localhost port fails at once on Linux/macOS, but Windows
# retries the SYN and reports "refused" only after about 2 s (TcpTransport.connect keeps the
# real CONNECT_TIMEOUT of transport.py; lowering it would turn "refused" into "timeout").
# Tests that wait for failed (re)connect attempts therefore allow this much per attempt.
REFUSED_CONNECT_WORST_CASE = 3.0


def failed_attempts_wait(attempts: int) -> float:
    """Generous wait for `attempts` refused connect attempts plus the event round trip."""
    return attempts * REFUSED_CONNECT_WORST_CASE + EVENT_TIMEOUT


@pytest.fixture(autouse=True)
def fast_timing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Shorten every wait so a full reconnect cycle takes well under a second."""
    monkeypatch.setattr(client_module, "RECONNECT_DELAYS", (0.05, 0.05))
    monkeypatch.setattr(client_module, "CONNECT_TIMEOUT", 1.0)
    monkeypatch.setattr(client_module, "SOCKET_TIMEOUT", 0.05)
    monkeypatch.setattr(client_module, "HEARTBEAT_INTERVAL", 0.1)
    monkeypatch.setattr(client_module, "STATS_UPDATE_INTERVAL", 0.05)
    monkeypatch.setattr(client_module, "CONNECTION_TIMEOUT", 0.5)


@pytest.fixture
def server() -> Iterator[FakeServer]:
    fake = FakeServer().start()
    yield fake
    fake.stop()


@pytest.fixture
def chat_client(event_bus: EventBus) -> Iterator[ChatClient]:
    chat = ChatClient(event_bus)
    yield chat
    chat.disconnect()


def make_config(port: int, **overrides: object) -> ClientConfig:
    config = ClientConfig(host=HOST, port=port, mode=TransportMode.TCP, username=USERNAME)
    for name, value in overrides.items():
        setattr(config, name, value)
    return config


def free_port() -> int:
    """A port with nobody listening on it."""
    listener = TcpListener()
    listener.start(HOST, 0)
    port = listener.bound_address[1]
    listener.close()
    return port


def connect(chat: ChatClient, event_queue: queue.Queue[Event], port: int,
            **overrides: object) -> Event:
    chat.connect(make_config(port, **overrides))
    return wait_for(event_queue, EventType.CONNECTED)


# --------------------------------------------------------------------------- #
# State machine
# --------------------------------------------------------------------------- #
def test_set_state_with_illegal_transition_raises(chat_client: ChatClient) -> None:
    with pytest.raises(InvalidStateError):
        chat_client._set_state(ConnectionState.CONNECTED)
    assert chat_client.state is ConnectionState.DISCONNECTED


def test_set_state_publishes_state_changed(chat_client: ChatClient,
                                           event_queue: queue.Queue[Event]) -> None:
    chat_client._set_state(ConnectionState.CONNECTING)
    event = wait_for(event_queue, EventType.STATE_CHANGED)
    event.validate()
    assert event.data == {"old": ConnectionState.DISCONNECTED, "new": ConnectionState.CONNECTING}


def test_send_chat_when_disconnected_raises_invalid_state(chat_client: ChatClient) -> None:
    with pytest.raises(InvalidStateError):
        chat_client.send_chat("hello")


def test_connect_with_invalid_username_raises_validation_error(
        chat_client: ChatClient) -> None:
    with pytest.raises(ValidationError):
        chat_client.connect(make_config(free_port(), username="a b"))
    assert chat_client.state is ConnectionState.DISCONNECTED


@pytest.mark.parametrize("field, value", [
    ("host", "not an ip"),
    ("port", 80),
    ("port", 70000),
    ("window_size", 0),
    ("loss_rate", 0.9),
])
def test_connect_with_invalid_config_raises_validation_error(
        chat_client: ChatClient, field: str, value: object) -> None:
    """ClientConfig.validate() (config.py) runs before anything touches the network."""
    config = make_config(free_port())
    setattr(config, field, value)
    with pytest.raises(ValidationError):
        chat_client.connect(config)
    assert chat_client.state is ConnectionState.DISCONNECTED


def test_connect_accepts_mode_as_plain_string(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event]) -> None:
    connected = connect(chat_client, event_queue, server.port, mode="tcp")
    assert connected.data["mode"] is TransportMode.TCP


def test_connect_twice_raises_invalid_state(chat_client: ChatClient, server: FakeServer,
                                            event_queue: queue.Queue[Event]) -> None:
    connect(chat_client, event_queue, server.port)
    with pytest.raises(InvalidStateError):
        chat_client.connect()


def test_disconnect_when_disconnected_does_nothing(chat_client: ChatClient,
                                                  event_queue: queue.Queue[Event]) -> None:
    chat_client.disconnect()
    chat_client.disconnect()
    assert event_queue.empty()


# --------------------------------------------------------------------------- #
# Connecting (T-08 and the handshake)
# --------------------------------------------------------------------------- #
def test_connect_to_closed_server_publishes_error(chat_client: ChatClient,
                                                  event_queue: queue.Queue[Event]) -> None:
    """T-08: nobody listening -> ERROR event, back to DISCONNECTED, no crash."""
    chat_client.connect(make_config(free_port()))
    error = wait_for(event_queue, EventType.ERROR, failed_attempts_wait(1))
    error.validate()
    assert error.data["code"] == ClientErrorCode.CONNECTION_REFUSED
    wait_for_state(event_queue, ConnectionState.DISCONNECTED)
    assert chat_client.state is ConnectionState.DISCONNECTED


def test_connect_handshake_publishes_connected_and_user_list(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event]) -> None:
    connected = connect(chat_client, event_queue, server.port)
    connected.validate()
    assert connected.data["client_id"] == 7
    assert connected.data["username"] == USERNAME
    users = wait_for(event_queue, EventType.USER_LIST_UPDATED)
    assert users.data["users"] == [USERNAME]
    assert chat_client.state is ConnectionState.CONNECTED
    assert server.types_received()[0] is MessageType.HELLO


def test_connect_rejected_by_server_publishes_server_error_code(
        chat_client: ChatClient, event_queue: queue.Queue[Event]) -> None:
    fake = FakeServer(reject_code=ErrorCode.USERNAME_TAKEN.value).start()
    try:
        chat_client.connect(make_config(fake.port))
        error = wait_for(event_queue, EventType.ERROR)
        assert error.data["code"] == ErrorCode.USERNAME_TAKEN.value
        disconnected = wait_for(event_queue, EventType.DISCONNECTED)
        assert disconnected.data["reason"] == DisconnectReason.REJECTED
        assert chat_client.state is ConnectionState.DISCONNECTED
    finally:
        fake.stop()


def test_connect_without_welcome_times_out(chat_client: ChatClient,
                                           event_queue: queue.Queue[Event]) -> None:
    fake = FakeServer(answer_hello=False).start()
    try:
        chat_client.connect(make_config(fake.port))
        error = wait_for(event_queue, EventType.ERROR)
        assert error.data["code"] == ClientErrorCode.CONNECT_TIMEOUT
        wait_for_state(event_queue, ConnectionState.DISCONNECTED)
    finally:
        fake.stop()


def test_disconnect_while_connecting_ends_disconnected(
        chat_client: ChatClient, event_queue: queue.Queue[Event]) -> None:
    fake = FakeServer(answer_hello=False).start()
    try:
        chat_client.connect(make_config(fake.port))
        assert fake.accepted.wait(EVENT_TIMEOUT)
        chat_client.disconnect()
        disconnected = wait_for(event_queue, EventType.DISCONNECTED)
        assert disconnected.data["reason"] == DisconnectReason.USER
        assert chat_client.state is ConnectionState.DISCONNECTED
    finally:
        fake.stop()


# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #
def test_send_chat_publishes_sent_and_receives_echo(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event]) -> None:
    connect(chat_client, event_queue, server.port)
    chat_client.send_chat("merhaba")
    sent = wait_for(event_queue, EventType.MESSAGE_SENT)
    sent.validate()
    assert sent.data["text"] == "merhaba" and sent.data["to"] is None
    received = wait_for(event_queue, EventType.MESSAGE_RECEIVED)
    received.validate()
    assert received.data["from"] == USERNAME and received.data["text"] == "merhaba"


@pytest.mark.parametrize("text", ["", "   ", "x" * (client_module.MAX_CHAT_LENGTH + 1)])
def test_send_chat_with_invalid_text_raises_validation_error(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event],
        text: str) -> None:
    connect(chat_client, event_queue, server.port)
    with pytest.raises(ValidationError):
        chat_client.send_chat(text)


def test_send_chat_with_invalid_recipient_raises_validation_error(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event]) -> None:
    connect(chat_client, event_queue, server.port)
    with pytest.raises(ValidationError):
        chat_client.send_chat("hi", to="../root")


def test_error_packet_from_server_becomes_error_event(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event]) -> None:
    connect(chat_client, event_queue, server.port)
    server.send_to_all(p.make_error(ErrorCode.UNKNOWN_USER.value, "no such user"))
    error = wait_for(event_queue, EventType.ERROR)
    assert error.data == {"code": ErrorCode.UNKNOWN_USER.value, "message": "no such user"}
    assert chat_client.state is ConnectionState.CONNECTED


def test_chat_packet_missing_fields_is_reported_and_connection_kept(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event]) -> None:
    connect(chat_client, event_queue, server.port)
    server.send_to_all(p.make_chat("no sender"))  # server->client CHAT without from/timestamp
    error = wait_for(event_queue, EventType.ERROR)
    assert error.data["code"] == ClientErrorCode.PROTOCOL_ERROR
    assert chat_client.state is ConnectionState.CONNECTED


# --------------------------------------------------------------------------- #
# Disconnecting
# --------------------------------------------------------------------------- #
def test_disconnect_sends_bye_and_publishes_disconnected(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event]) -> None:
    connect(chat_client, event_queue, server.port)
    chat_client.disconnect()
    disconnected = wait_for(event_queue, EventType.DISCONNECTED)
    disconnected.validate()
    assert disconnected.data["reason"] == DisconnectReason.USER
    assert chat_client.state is ConnectionState.DISCONNECTED
    wait_until(lambda: MessageType.BYE in server.types_received())


def test_client_can_connect_again_after_disconnect(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event]) -> None:
    connect(chat_client, event_queue, server.port)
    chat_client.disconnect()
    wait_for(event_queue, EventType.DISCONNECTED)
    connect(chat_client, event_queue, server.port)
    assert chat_client.state is ConnectionState.CONNECTED


def test_kick_from_server_disconnects_without_reconnect(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event]) -> None:
    connect(chat_client, event_queue, server.port)
    server.send_to_all(p.make_bye(ByeReason.KICKED_BY_ADMIN))
    disconnected = wait_for(event_queue, EventType.DISCONNECTED)
    assert disconnected.data["reason"] == DisconnectReason.KICKED_BY_ADMIN
    assert chat_client.state is ConnectionState.DISCONNECTED


# --------------------------------------------------------------------------- #
# Connection loss and reconnecting (T-09)
# --------------------------------------------------------------------------- #
def test_server_down_goes_reconnecting_then_disconnected(
        chat_client: ChatClient, event_queue: queue.Queue[Event]) -> None:
    """T-09: server disappears -> RECONNECTING -> every attempt fails -> DISCONNECTED."""
    fake = FakeServer().start()
    connect(chat_client, event_queue, fake.port)
    fake.stop()
    wait_for_state(event_queue, ConnectionState.RECONNECTING)
    attempts = len(client_module.RECONNECT_DELAYS)
    error = wait_for(event_queue, EventType.ERROR, failed_attempts_wait(attempts))
    assert "reconnect" in error.data["message"].lower()
    disconnected = wait_for(event_queue, EventType.DISCONNECTED)
    assert disconnected.data["reason"] == DisconnectReason.CONNECTION_LOST
    assert chat_client.state is ConnectionState.DISCONNECTED


def test_reconnects_when_server_accepts_again(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event]) -> None:
    connect(chat_client, event_queue, server.port)
    server.drop_clients()  # connection breaks, listener stays up
    wait_for_state(event_queue, ConnectionState.RECONNECTING)
    wait_for(event_queue, EventType.CONNECTED)
    assert chat_client.state is ConnectionState.CONNECTED
    chat_client.send_chat("after reconnect")
    received = wait_for(event_queue, EventType.MESSAGE_RECEIVED)
    assert received.data["text"] == "after reconnect"


def test_connection_lost_without_auto_reconnect_goes_disconnected(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event]) -> None:
    connect(chat_client, event_queue, server.port, auto_reconnect=False)
    server.drop_clients()
    disconnected = wait_for(event_queue, EventType.DISCONNECTED)
    assert disconnected.data["reason"] == DisconnectReason.CONNECTION_LOST
    assert chat_client.state is ConnectionState.DISCONNECTED


def test_disconnect_while_reconnecting_stops_retrying(
        chat_client: ChatClient, event_queue: queue.Queue[Event],
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "RECONNECT_DELAYS", (0.5, 0.5, 0.5))
    fake = FakeServer().start()
    connect(chat_client, event_queue, fake.port)
    fake.stop()
    wait_for_state(event_queue, ConnectionState.RECONNECTING)
    chat_client.disconnect()
    # disconnect() may land while an attempt is running; it ends after at most one refusal
    disconnected = wait_for(event_queue, EventType.DISCONNECTED, failed_attempts_wait(1))
    assert disconnected.data["reason"] == DisconnectReason.USER
    assert chat_client.state is ConnectionState.DISCONNECTED


def test_malformed_header_from_server_drops_connection(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event]) -> None:
    connect(chat_client, event_queue, server.port, auto_reconnect=False)
    with server._lock:
        server_side = server.connections[0]
    server_side._sock.sendall(b"XX" + bytes(20))  # wrong magic bytes
    error = wait_for(event_queue, EventType.ERROR)
    assert error.data["code"] == ClientErrorCode.PROTOCOL_ERROR
    disconnected = wait_for(event_queue, EventType.DISCONNECTED)
    assert disconnected.data["reason"] == DisconnectReason.CONNECTION_LOST


# --------------------------------------------------------------------------- #
# Heartbeat, silence detection, statistics
# --------------------------------------------------------------------------- #
def test_heartbeat_sends_ping_and_measures_rtt(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event]) -> None:
    connect(chat_client, event_queue, server.port)
    wait_until(lambda: chat_client.get_stats()["avg_rtt_ms"] > 0)
    assert MessageType.PING in server.types_received()
    stats_event = wait_for(event_queue, EventType.STATS_UPDATED)
    stats_event.validate()
    assert stats_event.data["stats"]["packets_sent"] >= 1


def test_silent_server_is_detected_as_lost(
        chat_client: ChatClient, event_queue: queue.Queue[Event]) -> None:
    """No packet for CONNECTION_TIMEOUT -> connection treated as dead."""
    fake = FakeServer(silent=True).start()
    try:
        connect(chat_client, event_queue, fake.port, auto_reconnect=False)
        disconnected = wait_for(event_queue, EventType.DISCONNECTED)
        assert disconnected.data["reason"] == DisconnectReason.TIMEOUT
    finally:
        fake.stop()


def test_get_stats_without_connection_returns_zeros(chat_client: ChatClient) -> None:
    stats = chat_client.get_stats()
    assert stats["packets_sent"] == 0 and stats["avg_rtt_ms"] == 0.0


@pytest.mark.parametrize("loss_rate, delay_ms", [(-0.1, 0), (0.9, 0), (0.1, -1), (0.1, 99999)])
def test_set_network_conditions_out_of_range_raises(
        chat_client: ChatClient, loss_rate: float, delay_ms: int) -> None:
    with pytest.raises(ValidationError):
        chat_client.set_network_conditions(loss_rate, delay_ms)


def test_set_network_conditions_is_kept_in_config(chat_client: ChatClient) -> None:
    chat_client.set_network_conditions(0.2, 100)
    assert (chat_client.config.loss_rate, chat_client.config.delay_ms) == (0.2, 100)


def test_every_published_event_has_required_keys(
        event_bus: EventBus, chat_client: ChatClient, server: FakeServer,
        event_queue: queue.Queue[Event]) -> None:
    published: list[Event] = []
    event_bus.subscribe(None, published.append)
    connect(chat_client, event_queue, server.port)
    chat_client.send_chat("contract")
    wait_for(event_queue, EventType.MESSAGE_RECEIVED)
    wait_for(event_queue, EventType.STATS_UPDATED)
    chat_client.disconnect()
    wait_for(event_queue, EventType.DISCONNECTED)
    assert len(published) >= 6
    for event in list(published):
        event.validate()
        if event.type is EventType.DISCONNECTED:
            # contract: the plain string value of a DisconnectReason, never free text
            assert type(event.data["reason"]) is str
            assert event.data["reason"] in {r.value for r in DisconnectReason}


# --------------------------------------------------------------------------- #
# Enum vocabularies (ByeReason, DisconnectReason, ClientErrorCode)
# --------------------------------------------------------------------------- #
def test_server_shutdown_bye_without_auto_reconnect_reports_server_shutdown(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event]) -> None:
    connect(chat_client, event_queue, server.port, auto_reconnect=False)
    server.send_to_all(p.make_bye(ByeReason.SERVER_SHUTDOWN))
    disconnected = wait_for(event_queue, EventType.DISCONNECTED)
    assert disconnected.data["reason"] == DisconnectReason.SERVER_SHUTDOWN


def test_server_shutdown_bye_with_auto_reconnect_reconnects(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event]) -> None:
    connect(chat_client, event_queue, server.port)
    server.send_to_all(p.make_bye(ByeReason.SERVER_SHUTDOWN))
    wait_for_state(event_queue, ConnectionState.RECONNECTING)
    wait_for(event_queue, EventType.CONNECTED)
    assert chat_client.state is ConnectionState.CONNECTED


def test_bye_with_unknown_reason_is_treated_as_server_shutdown(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event]) -> None:
    connect(chat_client, event_queue, server.port, auto_reconnect=False)
    server.send_to_all(p.make_bye("maintenance"))
    disconnected = wait_for(event_queue, EventType.DISCONNECTED)
    assert disconnected.data["reason"] == DisconnectReason.SERVER_SHUTDOWN


@pytest.mark.parametrize("exc, code", [
    (ConnectionRefusedError("refused"), ClientErrorCode.CONNECTION_REFUSED),
    (TimeoutError("timed out"), ClientErrorCode.CONNECT_TIMEOUT),
    (TransportTimeoutError("no WELCOME"), ClientErrorCode.CONNECT_TIMEOUT),
    (ConnectionClosedError("closed"), ClientErrorCode.CONNECTION_LOST),
    (ConnectionResetError("reset"), ClientErrorCode.CONNECTION_LOST),
    (MalformedPacketError("bad magic"), ClientErrorCode.PROTOCOL_ERROR),
    (BadChecksumError("crc"), ClientErrorCode.PROTOCOL_ERROR),
    (InvalidStateError("not connected"), ClientErrorCode.INVALID_STATE),
    (RuntimeError("bug"), ErrorCode.INTERNAL_ERROR),
])
def test_error_code_maps_exceptions_to_documented_codes(
        exc: BaseException, code: str) -> None:
    assert ChatClient._error_code(exc) == code


# --------------------------------------------------------------------------- #
# window_size (reliable UDP setting, must reach the transport)
# --------------------------------------------------------------------------- #
class _WindowedTcpTransport(TcpTransport):
    """TcpTransport plus the set_window_size() that only ReliableUdpTransport has.

    Records the calls, so the test can check ChatClient forwards ClientConfig.window_size
    without depending on the reliable UDP implementation.
    """

    window_sizes: list[int] = []
    network_conditions: list[tuple[float, int]] = []

    def set_window_size(self, window_size: int) -> None:
        self.window_sizes.append(window_size)

    def set_network_conditions(self, loss_rate: float = 0.0, delay_ms: int = 0) -> None:
        self.network_conditions.append((loss_rate, delay_ms))


def test_window_size_and_network_conditions_reach_the_transport(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event],
        monkeypatch: pytest.MonkeyPatch) -> None:
    _WindowedTcpTransport.window_sizes = []
    _WindowedTcpTransport.network_conditions = []
    monkeypatch.setattr(
        client_module, "create_transport",
        lambda mode, host, port, bus: _WindowedTcpTransport.connect(host, port, bus),
    )
    connect(chat_client, event_queue, server.port, window_size=8, loss_rate=0.1, delay_ms=50)
    assert _WindowedTcpTransport.window_sizes == [8]
    assert _WindowedTcpTransport.network_conditions == [(0.1, 50)]


def test_window_size_is_applied_again_after_reconnect(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event],
        monkeypatch: pytest.MonkeyPatch) -> None:
    _WindowedTcpTransport.window_sizes = []
    monkeypatch.setattr(
        client_module, "create_transport",
        lambda mode, host, port, bus: _WindowedTcpTransport.connect(host, port, bus),
    )
    connect(chat_client, event_queue, server.port, window_size=2)
    server.drop_clients()
    wait_for_state(event_queue, ConnectionState.RECONNECTING)
    wait_for(event_queue, EventType.CONNECTED)
    assert _WindowedTcpTransport.window_sizes == [2, 2]


# --------------------------------------------------------------------------- #
# File transfer (H5): send_file + FILE_* to FileReceiver, through the fake relay
# --------------------------------------------------------------------------- #
def write_random_file(folder: Path, name: str, size: int) -> Path:
    path = folder / name
    path.write_bytes(os.urandom(size))
    return path


def connect_named(event_bus: EventBus, port: int, username: str, download_dir: Path,
                  **overrides: object) -> tuple[ChatClient, queue.Queue[Event]]:
    """A second/third client with its own bus (chat_client is "hamit")."""
    events = event_bus.subscribe_queue()
    chat = ChatClient(event_bus)
    chat.connect(make_config(port, username=username, download_dir=str(download_dir),
                             **overrides))
    wait_for(events, EventType.CONNECTED)
    return chat, events


def file_event(q: queue.Queue[Event], event_type: EventType, transfer_id: int,
               direction: str, timeout: float = 20.0) -> Event:
    return wait_for(q, event_type, timeout, lambda e: e.data["transfer_id"] == transfer_id
                    and e.data["direction"] == direction)


@pytest.fixture
def receiver(server: FakeServer, tmp_path: Path) -> Iterator[tuple[ChatClient,
                                                                  queue.Queue[Event]]]:
    """User "bob" connected to `server`, downloading into tmp_path/downloads."""
    chat, events = connect_named(EventBus(), server.port, "bob", tmp_path / "downloads")
    yield chat, events
    chat.disconnect()


def test_send_file_when_disconnected_raises_invalid_state(
        chat_client: ChatClient, tmp_path: Path) -> None:
    path = write_random_file(tmp_path, "a.bin", 10)
    with pytest.raises(InvalidStateError):
        chat_client.send_file(str(path), to="bob")


@pytest.mark.parametrize("to", [None, "", "../bob"])
def test_send_file_without_valid_recipient_raises_validation_error(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event],
        tmp_path: Path, to: str | None) -> None:
    connect(chat_client, event_queue, server.port)
    path = write_random_file(tmp_path, "a.bin", 10)
    with pytest.raises(ValidationError):
        chat_client.send_file(str(path), to=to)
    assert MessageType.FILE_START not in server.types_received()


def test_send_file_with_missing_file_raises_validation_error(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event],
        tmp_path: Path) -> None:
    connect(chat_client, event_queue, server.port)
    with pytest.raises(ValidationError):
        chat_client.send_file(str(tmp_path / "nope.bin"), to="bob")
    assert MessageType.FILE_START not in server.types_received()


def test_transfer_ids_carry_client_id_and_count_up(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event],
        receiver: tuple[ChatClient, queue.Queue[Event]], tmp_path: Path) -> None:
    connected = connect(chat_client, event_queue, server.port)
    client_id = connected.data["client_id"]
    path = write_random_file(tmp_path, "a.bin", 100)
    first = chat_client.send_file(str(path), to="bob")
    second = chat_client.send_file(str(path), to="bob")
    assert first == p.make_transfer_id(client_id, 1)
    assert second == p.make_transfer_id(client_id, 2)
    assert p.transfer_id_client(first) == client_id


def test_transfer_counter_wraps_to_one(chat_client: ChatClient) -> None:
    chat_client._transfer_counter = client_module._MAX_TRANSFER_COUNTER
    assert chat_client._next_transfer_counter() == 1


def test_file_arrives_complete_with_matching_content(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event],
        receiver: tuple[ChatClient, queue.Queue[Event]], tmp_path: Path) -> None:
    """1 MB, TCP: FILE_OFFERED + FILE_COMPLETED on bob, FILE_COMPLETED on the sender."""
    _, bob_events = receiver
    connect(chat_client, event_queue, server.port)
    path = write_random_file(tmp_path, "report.bin", 1024 * 1024)
    transfer_id = chat_client.send_file(str(path), to="bob")
    offered = file_event(bob_events, EventType.FILE_OFFERED, transfer_id, "download")
    assert offered.data["from"] == USERNAME and offered.data["size"] == 1024 * 1024
    done = file_event(bob_events, EventType.FILE_COMPLETED, transfer_id, "download")
    saved = Path(done.data["path"])
    assert saved.parent == tmp_path / "downloads" / "bob"
    assert saved.read_bytes() == path.read_bytes()
    file_event(event_queue, EventType.FILE_COMPLETED, transfer_id, "upload")


def test_two_senders_at_once_to_the_same_receiver_do_not_collide(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event],
        receiver: tuple[ChatClient, queue.Queue[Event]], tmp_path: Path) -> None:
    """Both counters start at 1, but transfer_id also holds client_id (PROTOCOL 4.1)."""
    _, bob_events = receiver
    connect(chat_client, event_queue, server.port)
    carol, _ = connect_named(EventBus(), server.port, "carol", tmp_path / "carol_dl")
    try:
        file_a = write_random_file(tmp_path, "from_hamit.bin", 300 * 1024)
        file_b = write_random_file(tmp_path, "from_carol.bin", 300 * 1024)
        id_a = chat_client.send_file(str(file_a), to="bob")
        id_b = carol.send_file(str(file_b), to="bob")
        assert id_a != id_b
        # the two downloads finish in any order, so collect both before checking
        saved: dict[int, Path] = {}
        while len(saved) < 2:
            done = wait_for(bob_events, EventType.FILE_COMPLETED, 20.0,
                            lambda e: e.data["transfer_id"] in (id_a, id_b))
            saved[done.data["transfer_id"]] = Path(done.data["path"])
        assert saved[id_a].read_bytes() == file_a.read_bytes()
        assert saved[id_b].read_bytes() == file_b.read_bytes()
    finally:
        carol.disconnect()


def test_sender_connection_lost_mid_transfer_fails_the_upload(
        chat_client: ChatClient, event_queue: queue.Queue[Event], tmp_path: Path) -> None:
    """Part of T-16: the sender's link breaks -> FILE_FAILED(send_error), no crash."""
    fake = FakeServer(drop_sender_after_chunks=50).start()
    bob, _ = connect_named(EventBus(), fake.port, "bob", tmp_path / "downloads")
    try:
        connect(chat_client, event_queue, fake.port, auto_reconnect=False)
        # larger than the OS socket buffers, so the sender really notices the break
        path = write_random_file(tmp_path, "big.bin", 16 * 1024 * 1024)
        transfer_id = chat_client.send_file(str(path), to="bob")
        failed = file_event(event_queue, EventType.FILE_FAILED, transfer_id, "upload")
        assert failed.data["reason"] == FileFailReason.SEND_ERROR
        # DISCONNECTED may come before or after FILE_FAILED (two threads), so check state
        wait_until(lambda: chat_client.state is ConnectionState.DISCONNECTED)
    finally:
        bob.disconnect()
        fake.stop()


def test_receiver_connection_lost_mid_transfer_fails_the_download(
        chat_client: ChatClient, event_queue: queue.Queue[Event], tmp_path: Path) -> None:
    """Part of T-16: the receiver's link breaks -> FILE_FAILED(connection_lost) and the
    half-written .part file is removed."""
    fake = FakeServer(drop_target_after_chunks=20).start()
    downloads = tmp_path / "downloads"
    bob, bob_events = connect_named(EventBus(), fake.port, "bob", downloads,
                                    auto_reconnect=False)
    try:
        connect(chat_client, event_queue, fake.port)
        path = write_random_file(tmp_path, "big.bin", 1024 * 1024)
        transfer_id = chat_client.send_file(str(path), to="bob")
        failed = file_event(bob_events, EventType.FILE_FAILED, transfer_id, "download")
        assert failed.data["reason"] == FileFailReason.CONNECTION_LOST
        assert list((downloads / "bob").iterdir()) == []
    finally:
        bob.disconnect()
        fake.stop()


def test_user_disconnect_cancels_running_uploads(
        chat_client: ChatClient, server: FakeServer, event_queue: queue.Queue[Event],
        receiver: tuple[ChatClient, queue.Queue[Event]], tmp_path: Path) -> None:
    connect(chat_client, event_queue, server.port)
    path = write_random_file(tmp_path, "big.bin", 16 * 1024 * 1024)
    transfer_id = chat_client.send_file(str(path), to="bob")
    chat_client.disconnect()
    failed = file_event(event_queue, EventType.FILE_FAILED, transfer_id, "upload")
    assert failed.data["reason"] in (FileFailReason.CANCELLED, FileFailReason.SEND_ERROR)


def test_file_events_follow_the_event_contract(
        event_bus: EventBus, chat_client: ChatClient, server: FakeServer,
        event_queue: queue.Queue[Event], receiver: tuple[ChatClient, queue.Queue[Event]],
        tmp_path: Path) -> None:
    published: list[Event] = []
    event_bus.subscribe(None, published.append)
    connect(chat_client, event_queue, server.port)
    path = write_random_file(tmp_path, "a.bin", 50 * 1024)
    transfer_id = chat_client.send_file(str(path), to="bob")
    file_event(event_queue, EventType.FILE_COMPLETED, transfer_id, "upload")
    file_events = [e for e in published if e.type.name.startswith("FILE_")]
    assert file_events
    for event in file_events:
        event.validate()
