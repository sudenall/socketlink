"""Tests for ReliableUdpTransport / ReliableUdpListener (Go-Back-N), T-11, T-12, T-13.

OWNER: Yiğit. Real localhost sockets on port 0 (D-15). Simulated loss always uses a
seeded random.Random so a run is reproducible. Some tests replace the peer with a plain
UDP socket ("fake peer") to check the exact packets on the wire.
"""

from __future__ import annotations

import random
import socket
import threading
import time
from collections.abc import Iterator

import pytest

from socketlink.common import protocol as p
from socketlink.common.constants import (
    DEFAULT_WINDOW_SIZE,
    HEADER_SIZE,
    MAX_PAYLOAD_SIZE,
    MAX_RETRIES,
    RETRANSMIT_TIMEOUT,
    ErrorCode,
    MessageType,
    PacketFlag,
    TransportMode,
)
from socketlink.common.events import Event, EventBus, EventType
from socketlink.common.exceptions import (
    ConnectionClosedError,
    PayloadTooLargeError,
    TransportError,
    TransportTimeoutError,
    ValidationError,
)
from socketlink.common.transport import create_listener, create_transport
from socketlink.reliability.loss_simulator import LossSimulator
from socketlink.reliability.reliable_udp import ReliableUdpListener, ReliableUdpTransport

HOST = "127.0.0.1"
RECEIVE_TIMEOUT = 5.0
BUFFER = HEADER_SIZE + MAX_PAYLOAD_SIZE
# MAX_RETRIES resends plus the final timeout, with some slack for slow CI machines.
GIVE_UP_TIME = RETRANSMIT_TIMEOUT * (MAX_RETRIES + 1) + 2.0
# Go-Back-N with a 0.5 s timer is slow under heavy loss (up to ~100 s for 200 packets at
# 30 % loss in both directions with window 1), so the full matrix is marked slow.
SLOW_TEST_TIMEOUT = 300

Pair = tuple[ReliableUdpTransport, ReliableUdpTransport]


def set_loss(transport: ReliableUdpTransport, loss_rate: float, seed: int) -> None:
    """Simulated loss with a fixed seed (set_network_conditions uses an unseeded rng)."""
    transport.loss_simulator = LossSimulator(loss_rate=loss_rate, rng=random.Random(seed))


def chat(i: int) -> p.Packet:
    return p.make_chat(text=f"message {i}")


def text_of(packet: p.Packet) -> str:
    return packet.json_payload()["text"]


@pytest.fixture
def listener() -> Iterator[ReliableUdpListener]:
    udp_listener = ReliableUdpListener()
    udp_listener.start(HOST, 0)
    yield udp_listener
    udp_listener.close()


@pytest.fixture
def pair(listener: ReliableUdpListener) -> Iterator[Pair]:
    """(client, server_side) after the client's HELLO arrived."""
    client = ReliableUdpTransport.connect(HOST, listener.bound_address[1])
    client.send(p.make_hello("alice"))
    server_side = listener.accept(timeout=RECEIVE_TIMEOUT)
    assert server_side.receive(timeout=RECEIVE_TIMEOUT).type is MessageType.HELLO
    assert isinstance(server_side, ReliableUdpTransport)
    yield client, server_side
    client.close()
    server_side.close()


@pytest.fixture
def fake_peer() -> Iterator[socket.socket]:
    """A plain UDP socket playing the other side, to inspect raw packets."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, 0))
    sock.settimeout(RECEIVE_TIMEOUT)
    yield sock
    sock.close()


def read_packet(sock: socket.socket) -> tuple[p.Packet, tuple[str, int]]:
    data, address = sock.recvfrom(BUFFER)
    return p.Packet.decode(data), address


def wait_until(condition, timeout: float = RECEIVE_TIMEOUT) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


# --------------------------------------------------------------------------- #
# Listener basics
# --------------------------------------------------------------------------- #
def test_listener_on_port_zero_reports_real_port(listener: ReliableUdpListener) -> None:
    host, port = listener.bound_address
    assert host == HOST and port != 0


def test_listener_bound_address_before_start_raises() -> None:
    with pytest.raises(TransportError):
        _ = ReliableUdpListener().bound_address


def test_listener_accept_before_start_raises() -> None:
    with pytest.raises(ConnectionClosedError):
        ReliableUdpListener().accept(timeout=0.1)


def test_listener_accept_times_out(listener: ReliableUdpListener) -> None:
    with pytest.raises(TransportTimeoutError):
        listener.accept(timeout=0.2)


def test_listener_accept_after_close_raises(listener: ReliableUdpListener) -> None:
    listener.close()
    listener.close()  # idempotent
    with pytest.raises(ConnectionClosedError):
        listener.accept(timeout=0.2)


def test_listener_start_on_used_port_raises_oserror(listener: ReliableUdpListener) -> None:
    with pytest.raises(OSError):
        ReliableUdpListener().start(HOST, listener.bound_address[1])


def test_listener_ignores_unknown_sender_that_is_not_hello(
    listener: ReliableUdpListener, fake_peer: socket.socket
) -> None:
    stray = p.make_chat(text="hi")
    stray.seq = 1
    fake_peer.sendto(stray.encode(), listener.bound_address)
    with pytest.raises(TransportTimeoutError):
        listener.accept(timeout=0.5)


def test_listener_creates_one_session_per_address(
    listener: ReliableUdpListener, fake_peer: socket.socket
) -> None:
    hello = p.make_hello("bob")
    hello.seq, hello.flags = 1, PacketFlag.ACK_REQUIRED
    fake_peer.sendto(hello.encode(), listener.bound_address)
    fake_peer.sendto(hello.encode(), listener.bound_address)  # retransmitted HELLO
    server_side = listener.accept(timeout=RECEIVE_TIMEOUT)
    assert server_side.peer_address == fake_peer.getsockname()
    with pytest.raises(TransportTimeoutError):
        listener.accept(timeout=0.5)
    assert server_side.receive(timeout=RECEIVE_TIMEOUT).type is MessageType.HELLO
    assert wait_until(lambda: server_side.stats.duplicates_received == 1)
    server_side.close()


def test_create_functions_return_udp_objects_in_udp_mode() -> None:
    udp_listener = create_listener(TransportMode.UDP)
    assert isinstance(udp_listener, ReliableUdpListener)
    udp_listener.start(HOST, 0)
    try:
        transport = create_transport(TransportMode.UDP, HOST, udp_listener.bound_address[1])
        assert isinstance(transport, ReliableUdpTransport)
        transport.close()
    finally:
        udp_listener.close()


# --------------------------------------------------------------------------- #
# Basic delivery
# --------------------------------------------------------------------------- #
def test_packet_travels_in_both_directions(pair) -> None:
    client, server_side = pair
    client.send(p.make_chat(text="ping"))
    assert text_of(server_side.receive(timeout=RECEIVE_TIMEOUT)) == "ping"
    server_side.send(p.make_chat(text="pong", sender="bob"))
    assert text_of(client.receive(timeout=RECEIVE_TIMEOUT)) == "pong"


def test_peer_address_and_is_open(pair, listener: ReliableUdpListener) -> None:
    client, server_side = pair
    assert client.peer_address == listener.bound_address
    assert server_side.peer_address[1] != 0
    assert client.is_open and server_side.is_open


def test_send_does_not_modify_the_callers_packet(pair) -> None:
    client, _ = pair
    packet = p.make_ping()
    client.send(packet)
    assert packet.seq == 0 and packet.flags == PacketFlag.NONE


def test_receive_with_no_data_times_out_and_stays_open(pair) -> None:
    client, _ = pair
    with pytest.raises(TransportTimeoutError):
        client.receive(timeout=0.2)
    assert client.is_open


def test_send_oversized_payload_raises_and_keeps_connection(pair) -> None:
    client, server_side = pair
    with pytest.raises(PayloadTooLargeError):
        client.send(p.Packet(type=MessageType.CHAT, payload=b"x" * (MAX_PAYLOAD_SIZE + 1)))
    client.send(p.make_chat(text="still works"))
    assert text_of(server_side.receive(timeout=RECEIVE_TIMEOUT)) == "still works"


def test_large_payload_roundtrip(pair) -> None:
    client, server_side = pair
    data = bytes(range(256)) * (MAX_PAYLOAD_SIZE // 256)
    client.send(p.make_file_chunk(7, 0, data))
    assert p.parse_file_chunk(server_side.receive(timeout=RECEIVE_TIMEOUT)) == (7, 0, data)


def test_sockets_can_send_a_full_size_datagram(pair, listener: ReliableUdpListener) -> None:
    """macOS refuses datagrams bigger than SO_SNDBUF (default 9216 bytes): the socket buffers
    must hold one full packet, on the client socket and on the server's shared socket."""
    client, _ = pair
    for sock in (client._sock, listener._sock):
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF) >= BUFFER


def test_concurrent_senders_all_arrive_once(pair) -> None:
    client, server_side = pair

    def send_many(start: int) -> None:
        for i in range(start, start + 50):
            client.send(chat(i))

    threads = [threading.Thread(target=send_many, args=(k * 100,)) for k in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    received = [text_of(server_side.receive(timeout=RECEIVE_TIMEOUT)) for _ in range(150)]
    expected = {f"message {k * 100 + i}" for k in range(3) for i in range(50)}
    assert len(received) == 150 and set(received) == expected


def test_three_clients_are_routed_to_their_own_session(listener: ReliableUdpListener) -> None:
    clients = [ReliableUdpTransport.connect(HOST, listener.bound_address[1]) for _ in range(3)]
    sessions = {}
    try:
        for index, client in enumerate(clients):
            client.send(p.make_hello(f"user{index}"))
            server_side = listener.accept(timeout=RECEIVE_TIMEOUT)
            username = server_side.receive(timeout=RECEIVE_TIMEOUT).json_payload()["username"]
            sessions[username] = server_side
        for index, client in enumerate(clients):
            for i in range(20):
                client.send(p.make_chat(text=f"user{index}-{i}"))
        for index in range(3):
            server_side = sessions[f"user{index}"]
            texts = [text_of(server_side.receive(timeout=RECEIVE_TIMEOUT)) for _ in range(20)]
            assert texts == [f"user{index}-{i}" for i in range(20)]
    finally:
        for transport in [*clients, *sessions.values()]:
            transport.close()


# --------------------------------------------------------------------------- #
# T-11: everything, in order, exactly once, despite loss
# --------------------------------------------------------------------------- #
def send_through_lossy_link(listener: ReliableUdpListener, count: int, loss_rate: float,
                            window_size: int) -> tuple[list[str], Pair]:
    """Open a session, apply seeded loss on BOTH sides, send `count` packets."""
    client = ReliableUdpTransport.connect(HOST, listener.bound_address[1])
    client.send(p.make_hello("alice"))
    server_side = listener.accept(timeout=RECEIVE_TIMEOUT)
    assert isinstance(server_side, ReliableUdpTransport)
    server_side.receive(timeout=RECEIVE_TIMEOUT)
    set_loss(client, loss_rate, seed=11)       # data packets are lost ...
    set_loss(server_side, loss_rate, seed=12)  # ... and so are ACKs
    client.set_window_size(window_size)

    sender = threading.Thread(target=lambda: [client.send(chat(i)) for i in range(count)])
    sender.start()
    received = [text_of(server_side.receive(timeout=GIVE_UP_TIME)) for _ in range(count)]
    sender.join(timeout=GIVE_UP_TIME)
    return received, (client, server_side)


def check_exactly_once_in_order(received: list[str], pair: Pair, count: int,
                                loss_rate: float) -> None:
    client, server_side = pair
    try:
        assert received == [f"message {i}" for i in range(count)]
        with pytest.raises(TransportTimeoutError):  # and nothing extra
            server_side.receive(timeout=RETRANSMIT_TIMEOUT * 2)
        if loss_rate > 0:
            assert client.stats.retransmissions > 0
            assert client.stats.packets_dropped_simulated > 0
        else:
            assert client.stats.retransmissions == 0
    finally:
        client.close()
        server_side.close()


@pytest.mark.parametrize("window_size", [1, DEFAULT_WINDOW_SIZE])
def test_all_packets_arrive_in_order_once_without_loss(
    listener: ReliableUdpListener, window_size: int
) -> None:
    received, pair = send_through_lossy_link(listener, 200, 0.0, window_size)
    check_exactly_once_in_order(received, pair, 200, 0.0)


def test_all_packets_arrive_in_order_once_with_loss_quick(listener: ReliableUdpListener) -> None:
    """Fast CI version of T-11: 40 packets, 20 % loss both ways, window 4."""
    received, pair = send_through_lossy_link(listener, 40, 0.2, DEFAULT_WINDOW_SIZE)
    check_exactly_once_in_order(received, pair, 40, 0.2)


@pytest.mark.slow
@pytest.mark.timeout(SLOW_TEST_TIMEOUT)
@pytest.mark.parametrize("window_size", [1, DEFAULT_WINDOW_SIZE])
@pytest.mark.parametrize("loss_rate", [0.1, 0.3])
def test_all_packets_arrive_in_order_once_despite_loss(
    listener: ReliableUdpListener, loss_rate: float, window_size: int
) -> None:
    """T-11: 200 packets, 10 % / 30 % loss in both directions, window 1 and 4."""
    received, pair = send_through_lossy_link(listener, 200, loss_rate, window_size)
    check_exactly_once_in_order(received, pair, 200, loss_rate)


@pytest.mark.timeout(SLOW_TEST_TIMEOUT)
@pytest.mark.parametrize("loss_rate", [
    0.0,
    pytest.param(0.1, marks=pytest.mark.slow),
    pytest.param(0.2, marks=pytest.mark.slow),
    pytest.param(0.3, marks=pytest.mark.slow),
])
def test_500_packets_arrive_in_order_once_despite_loss(
    listener: ReliableUdpListener, loss_rate: float
) -> None:
    """T-11 as in README section 13.2: 500 packets, 0 / 10 / 20 / 30 % loss, default window."""
    received, pair = send_through_lossy_link(listener, 500, loss_rate, DEFAULT_WINDOW_SIZE)
    check_exactly_once_in_order(received, pair, 500, loss_rate)


# --------------------------------------------------------------------------- #
# T-12: Stop-and-Wait vs Go-Back-N
# --------------------------------------------------------------------------- #
def test_window_four_is_faster_than_stop_and_wait_with_delay(
    listener: ReliableUdpListener,
) -> None:
    durations = {}
    for window_size in (1, 4):
        client = ReliableUdpTransport.connect(HOST, listener.bound_address[1])
        client.send(p.make_hello(f"w{window_size}"))
        server_side = listener.accept(timeout=RECEIVE_TIMEOUT)
        server_side.receive(timeout=RECEIVE_TIMEOUT)
        client.set_network_conditions(delay_ms=20)
        client.set_window_size(window_size)
        start = time.monotonic()
        for i in range(30):
            client.send(chat(i))
        for _ in range(30):
            server_side.receive(timeout=RECEIVE_TIMEOUT)
        durations[window_size] = time.monotonic() - start
        client.close()
        server_side.close()
    assert durations[4] < durations[1] / 2


@pytest.mark.slow
@pytest.mark.timeout(SLOW_TEST_TIMEOUT)
def test_larger_window_is_faster_but_retransmits_more_under_loss(
    listener: ReliableUdpListener,
) -> None:
    """T-12: 100 packets at 10 % loss (both directions) with window 1, 4 and 8.

    Go-Back-N resends the whole window after a timeout, so a bigger window finishes sooner
    but sends more retransmissions (D-07). Measured: window 1 needs about twice the time of
    window 4 or 8, and retransmissions grow with the window on every seed that was tried.
    """
    count = 100
    durations: dict[int, float] = {}
    retransmissions: dict[int, int] = {}
    for window_size in (1, 4, 8):
        start = time.monotonic()
        received, (client, server_side) = send_through_lossy_link(
            listener, count, 0.1, window_size
        )
        durations[window_size] = time.monotonic() - start
        retransmissions[window_size] = client.stats.retransmissions
        client.close()
        server_side.close()
        assert received == [f"message {i}" for i in range(count)]
    assert durations[4] < durations[1] * 0.8
    assert durations[8] < durations[1] * 0.8
    assert retransmissions[1] < retransmissions[4] < retransmissions[8]


def test_send_blocks_while_the_window_is_full(pair) -> None:
    client, server_side = pair
    client.set_window_size(2)
    set_loss(server_side, 1.0, seed=1)  # no ACK reaches the client
    client.send(chat(0))
    client.send(chat(1))
    third_sent = threading.Event()
    sender = threading.Thread(target=lambda: (client.send(chat(2)), third_sent.set()))
    sender.start()
    assert not third_sent.wait(RETRANSMIT_TIMEOUT / 2)
    set_loss(server_side, 0.0, seed=1)  # ACKs flow again after the next retransmission
    assert third_sent.wait(RECEIVE_TIMEOUT)
    sender.join()
    texts = [text_of(server_side.receive(timeout=RECEIVE_TIMEOUT)) for _ in range(3)]
    assert texts == ["message 0", "message 1", "message 2"]


def test_set_window_size_and_network_conditions_validate_their_input(pair) -> None:
    client, _ = pair
    for bad_window in (0, 33):
        with pytest.raises(ValidationError):
            client.set_window_size(bad_window)
    with pytest.raises(ValidationError):
        client.set_network_conditions(loss_rate=1.5)
    with pytest.raises(ValidationError):
        client.set_network_conditions(delay_ms=-1)
    client.set_network_conditions(loss_rate=0.2, delay_ms=100)
    assert client.loss_simulator.loss_rate == 0.2
    assert client.loss_simulator.delay_ms == 100


# --------------------------------------------------------------------------- #
# T-13: MAX_RETRIES exceeded, peer gone
# --------------------------------------------------------------------------- #
def test_max_retries_exceeded_raises_timeout_and_closes(pair) -> None:
    client, _ = pair
    set_loss(client, 1.0, seed=1)  # 100 % loss: nothing gets through
    client.send(chat(0))
    assert wait_until(lambda: not client.is_open, timeout=GIVE_UP_TIME)
    assert client.stats.retransmissions == MAX_RETRIES
    with pytest.raises(TransportTimeoutError):
        client.send(chat(1))
    with pytest.raises(ConnectionClosedError):
        client.receive(timeout=0.1)
    client.close()  # still idempotent after a failure


def test_blocked_receive_ends_when_the_peer_stops_answering(pair) -> None:
    client, server_side = pair
    server_side.close()  # the server forgets the session: the client gets no ACKs
    errors: list[Exception] = []

    def receive() -> None:
        try:
            client.receive()
        except TransportError as exc:
            errors.append(exc)

    receiver = threading.Thread(target=receive)
    receiver.start()
    client.send(chat(0))
    receiver.join(timeout=GIVE_UP_TIME)
    assert not receiver.is_alive()
    assert isinstance(errors[0], ConnectionClosedError)


def test_connect_to_port_without_server_fails_fast() -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind((HOST, 0))
    free_port = probe.getsockname()[1]
    probe.close()
    client = ReliableUdpTransport.connect(HOST, free_port)  # UDP: no handshake, no error yet
    client.send(p.make_hello("alice"))
    with pytest.raises(ConnectionClosedError):
        client.receive(timeout=GIVE_UP_TIME)
    client.close()


# --------------------------------------------------------------------------- #
# Closing
# --------------------------------------------------------------------------- #
def test_close_is_idempotent_and_blocks_further_use(pair) -> None:
    client, _ = pair
    client.close()
    client.close()
    assert not client.is_open
    with pytest.raises(ConnectionClosedError):
        client.send(chat(0))
    with pytest.raises(ConnectionClosedError):
        client.receive(timeout=0.1)


def test_close_wakes_up_a_blocked_receive(pair) -> None:
    client, _ = pair
    errors: list[Exception] = []

    def receive() -> None:
        try:
            client.receive()
        except ConnectionClosedError as exc:
            errors.append(exc)

    receiver = threading.Thread(target=receive)
    receiver.start()
    time.sleep(0.1)
    start = time.monotonic()
    client.close()
    receiver.join(timeout=RECEIVE_TIMEOUT)
    assert errors and time.monotonic() - start < RETRANSMIT_TIMEOUT


def test_bye_sent_right_before_close_is_delivered_despite_loss(pair) -> None:
    client, server_side = pair
    set_loss(client, 0.5, seed=5)
    client.send(p.make_bye())
    client.close()
    assert server_side.receive(timeout=GIVE_UP_TIME).type is MessageType.BYE


def test_closed_listener_still_delivers_bye_to_accepted_clients(pair, listener) -> None:
    client, server_side = pair
    listener.close()  # ChatServer.stop() closes the listener first, then sends BYE
    server_side.send(p.make_bye("server_shutdown"))
    server_side.close()
    assert client.receive(timeout=RECEIVE_TIMEOUT).type is MessageType.BYE


# --------------------------------------------------------------------------- #
# Wire level: the exact Go-Back-N behaviour, checked with a fake peer
# --------------------------------------------------------------------------- #
def test_sender_numbers_packets_and_resends_the_whole_window(fake_peer: socket.socket) -> None:
    client = ReliableUdpTransport.connect(HOST, fake_peer.getsockname()[1])
    try:
        for i in range(3):
            client.send(chat(i))
        first = [read_packet(fake_peer)[0] for _ in range(3)]
        assert [packet.seq for packet in first] == [1, 2, 3]
        assert all(packet.flags & PacketFlag.ACK_REQUIRED for packet in first)
        assert not any(packet.flags & PacketFlag.RETRANSMISSION for packet in first)

        _, client_address = read_packet(fake_peer)  # first retransmission of seq 1
        fake_peer.sendto(p.make_ack(1).encode(), client_address)  # only seq 1 arrived
        resent = [read_packet(fake_peer)[0] for _ in range(4)]
        seqs = [packet.seq for packet in resent]
        assert seqs[-2:] == [2, 3]  # Go-Back-N: everything after base, again
        assert all(packet.flags & PacketFlag.RETRANSMISSION for packet in resent)
        fake_peer.sendto(p.make_ack(3).encode(), client_address)  # cumulative: 2 and 3 too
        client.send(chat(3))
        while True:  # stale retransmissions may still be in the socket buffer
            packet, _ = read_packet(fake_peer)
            if not packet.flags & PacketFlag.RETRANSMISSION:
                break
        assert packet.seq == 4
    finally:
        client.close()


def test_receiver_acks_cumulatively_and_drops_out_of_order(fake_peer: socket.socket) -> None:
    bus = EventBus()
    events = bus.subscribe_queue()
    client = ReliableUdpTransport.connect(HOST, fake_peer.getsockname()[1], bus)
    try:
        client.send(p.make_hello("alice"))
        hello, client_address = read_packet(fake_peer)
        fake_peer.sendto(p.make_ack(hello.seq).encode(), client_address)

        def deliver(seq: int, text: str) -> int:
            packet = p.make_chat(text=text, sender="bob")
            packet.seq, packet.flags = seq, PacketFlag.ACK_REQUIRED
            fake_peer.sendto(packet.encode(), client_address)
            ack, _ = read_packet(fake_peer)
            assert ack.type is MessageType.ACK and ack.seq == 0
            return ack.ack

        assert deliver(1, "one") == 1
        assert deliver(3, "three") == 1      # gap: seq 3 dropped, re-ACK 1
        assert deliver(1, "one") == 1        # duplicate: dropped, counted, re-ACKed
        assert deliver(2, "two") == 2
        assert deliver(3, "three") == 3
        texts = [text_of(client.receive(timeout=RECEIVE_TIMEOUT)) for _ in range(3)]
        assert texts == ["one", "two", "three"]
        assert client.stats.duplicates_received == 1

        corrupted = bytearray(p.make_chat(text="x").encode())
        corrupted[-1] ^= 0xFF
        fake_peer.sendto(bytes(corrupted), client_address)
        assert wait_until(lambda: client.stats.checksum_errors == 1)
    finally:
        client.close()
    seen = []
    while not events.empty():
        event: Event = events.get_nowait()
        event.validate()
        seen.append(event.type)
    assert EventType.PACKET_CORRUPTED in seen
    assert {EventType.PACKET_SENT, EventType.PACKET_RECEIVED} <= set(seen)


def test_internal_error_in_a_network_thread_is_reported_and_closes(pair) -> None:
    client, server_side = pair
    bus = EventBus()
    events = bus.subscribe_queue()
    client.event_bus = bus

    def explode(data: bytes) -> None:
        raise RuntimeError("boom")

    client._handle_datagram = explode  # type: ignore[method-assign]
    server_side.send(chat(0))
    with pytest.raises(ConnectionClosedError):
        client.receive(timeout=RECEIVE_TIMEOUT)
    errors = []
    while not events.empty():
        event = events.get_nowait()
        if event.type is EventType.ERROR:
            event.validate()
            errors.append(event)
    assert [e.data["code"] for e in errors] == [ErrorCode.INTERNAL_ERROR.value]
    assert "boom" in errors[0].data["message"]


def test_loss_and_retransmission_events_and_stats(pair) -> None:
    client, server_side = pair
    bus = EventBus()
    events = bus.subscribe_queue()
    client.event_bus = bus
    set_loss(client, 0.3, seed=3)
    for i in range(10):
        client.send(chat(i))
    for _ in range(10):
        server_side.receive(timeout=GIVE_UP_TIME)
    by_type: dict[EventType, list[Event]] = {}
    while not events.empty():
        event = events.get_nowait()
        event.validate()
        by_type.setdefault(event.type, []).append(event)
    stats = client.stats.snapshot()
    assert len(by_type[EventType.PACKET_DROPPED]) == stats["packets_dropped_simulated"] > 0
    assert len(by_type[EventType.PACKET_RETRANSMITTED]) == stats["retransmissions"] > 0
    assert all(event.data["attempt"] >= 1 for event in by_type[EventType.PACKET_RETRANSMITTED])
    assert stats["packets_sent"] > 0 and stats["bytes_sent"] > 0
    assert server_side.stats.packets_received >= 10
