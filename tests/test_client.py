"""Tests for ChatClient against a small fake server built on TcpListener.

OWNER: Hamit
Scenarios: T-08 (closed server), T-09 (server goes down -> RECONNECTING), handshake,
chat, heartbeat/RTT, silent server, kick, protocol errors, invalid states.

The fake server is defined here (not the real ChatServer) so these tests only depend
on the protocol and transport, which are already on main. Every test listens on port 0
(D-15). Timing constants are shortened with monkeypatch so the suite stays fast.
Shared helpers (event_bus, event_queue, wait_for_event) come from conftest.py.
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable, Iterator

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
    """Minimal server: answers HELLO, echoes CHAT, answers PING (unless silent).

    `reject_code` makes it answer HELLO with ERROR; `answer_hello=False` makes it
    never answer; `silent=True` makes it ignore PINGs after the handshake.
    """

    def __init__(self, reject_code: str | None = None, answer_hello: bool = True,
                 silent: bool = False) -> None:
        self.reject_code = reject_code
        self.answer_hello = answer_hello
        self.silent = silent
        self.listener = TcpListener()
        self.received: list[p.Packet] = []
        self.connections: list[Transport] = []
        self.accepted = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()

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
            transport.send(p.make_welcome(7, "Fake", [username]))
            transport.send(p.make_user_list([username]))
        elif packet.type is MessageType.CHAT:
            payload = packet.json_payload()
            transport.send(p.make_chat(payload["text"], payload["to"], sender=USERNAME,
                                       timestamp=time.time()))
        elif packet.type is MessageType.PING and not self.silent:
            transport.send(p.make_pong())
        elif packet.type is MessageType.BYE:
            transport.close()


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
    error = wait_for(event_queue, EventType.ERROR)
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
    error = wait_for(event_queue, EventType.ERROR)
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
    disconnected = wait_for(event_queue, EventType.DISCONNECTED)
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
