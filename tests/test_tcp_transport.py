"""Unit tests for TcpTransport / TcpListener over real localhost sockets (T-03).

OWNER: Sude. Every test listens on port 0 so parallel runs never collide (D-15).
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import pytest

from socketlink.common import protocol as p
from socketlink.common.constants import MAX_PAYLOAD_SIZE, TransportMode
from socketlink.common.events import EventBus, EventType
from socketlink.common.exceptions import (
    ConnectionClosedError,
    MalformedPacketError,
    PayloadTooLargeError,
    TransportError,
    TransportTimeoutError,
)
from socketlink.common.transport import (
    TcpListener,
    TcpTransport,
    Transport,
    create_listener,
    create_transport,
)

HOST = "127.0.0.1"


@pytest.fixture
def listener() -> Iterator[TcpListener]:
    tcp_listener = TcpListener()
    tcp_listener.start(HOST, 0)
    yield tcp_listener
    tcp_listener.close()


@pytest.fixture
def pair(listener: TcpListener) -> Iterator[tuple[TcpTransport, Transport]]:
    """(client, server_side) transports connected to each other."""
    client = TcpTransport.connect(HOST, listener.bound_address[1])
    server_side = listener.accept(timeout=2)
    yield client, server_side
    client.close()
    server_side.close()


def test_listener_on_port_zero_reports_real_port(listener: TcpListener) -> None:
    host, port = listener.bound_address
    assert host == HOST and port != 0


def test_listener_bound_address_before_start_raises() -> None:
    with pytest.raises(TransportError):
        _ = TcpListener().bound_address


def test_listener_accept_times_out(listener: TcpListener) -> None:
    with pytest.raises(TransportTimeoutError):
        listener.accept(timeout=0.1)


def test_listener_accept_after_close_raises(listener: TcpListener) -> None:
    listener.close()
    listener.close()  # idempotent
    with pytest.raises(ConnectionClosedError):
        listener.accept(timeout=0.1)


def test_listener_start_on_used_port_raises_oserror(listener: TcpListener) -> None:
    other = TcpListener()
    with pytest.raises(OSError):
        other.start(HOST, listener.bound_address[1])


def test_connect_to_closed_port_raises_connection_refused() -> None:
    probe = socket.socket()
    probe.bind((HOST, 0))
    port = probe.getsockname()[1]
    probe.close()
    with pytest.raises(ConnectionRefusedError):
        TcpTransport.connect(HOST, port)


def test_packet_travels_in_both_directions(pair) -> None:
    client, server_side = pair
    client.send(p.make_chat("hello", to=None))
    assert server_side.receive(timeout=2).json_payload()["text"] == "hello"
    server_side.send(p.make_pong())
    assert client.receive(timeout=2).type.name == "PONG"


def test_peer_address_and_is_open(pair, listener: TcpListener) -> None:
    client, server_side = pair
    assert client.peer_address == listener.bound_address
    assert client.is_open and server_side.is_open


def test_many_packets_arrive_in_order(pair) -> None:
    client, server_side = pair
    for i in range(200):
        client.send(p.make_chat(f"msg {i}"))
    texts = [server_side.receive(timeout=2).json_payload()["text"] for _ in range(200)]
    assert texts == [f"msg {i}" for i in range(200)]


def test_packet_sent_one_byte_at_a_time_is_reassembled(pair) -> None:
    client, server_side = pair
    data = p.make_chat("slow à la carte ğ").encode()
    raw = client._sock  # bypass send() to control the byte boundaries

    def trickle() -> None:
        for i in range(len(data)):
            raw.sendall(data[i:i + 1])
            time.sleep(0.001)

    sender = threading.Thread(target=trickle)
    sender.start()
    packet = server_side.receive(timeout=5)
    sender.join()
    assert packet.json_payload()["text"] == "slow à la carte ğ"


def test_two_packets_in_one_segment_are_split_correctly(pair) -> None:
    client, server_side = pair
    client._sock.sendall(p.make_ping().encode() + p.make_pong().encode())
    assert server_side.receive(timeout=2).type.name == "PING"
    assert server_side.receive(timeout=2).type.name == "PONG"


def test_large_payload_roundtrip(pair) -> None:
    client, server_side = pair
    packet = p.Packet(p.MessageType.FILE_CHUNK, payload=b"\xab" * MAX_PAYLOAD_SIZE)
    client.send(packet)
    assert server_side.receive(timeout=5).payload == packet.payload


def test_receive_timeout_in_the_middle_keeps_the_stream_aligned(pair) -> None:
    client, server_side = pair
    data = p.make_chat("split in two").encode()
    client._sock.sendall(data[:10])
    with pytest.raises(TransportTimeoutError):
        server_side.receive(timeout=0.1)
    client._sock.sendall(data[10:])
    assert server_side.receive(timeout=2).json_payload()["text"] == "split in two"


def test_receive_with_no_data_times_out_and_stays_open(pair) -> None:
    _, server_side = pair
    with pytest.raises(TransportTimeoutError):
        server_side.receive(timeout=0.1)
    assert server_side.is_open


def test_corrupted_packet_is_skipped_and_counted(pair) -> None:
    client, server_side = pair
    bad = bytearray(p.make_chat("bad").encode())
    bad[-1] ^= 0xFF
    client._sock.sendall(bytes(bad) + p.make_chat("good").encode())
    assert server_side.receive(timeout=2).json_payload()["text"] == "good"
    assert server_side.stats.checksum_errors == 1
    assert server_side.is_open


def test_wrong_magic_raises_malformed(pair) -> None:
    client, server_side = pair
    client._sock.sendall(b"XX" + bytes(30))
    with pytest.raises(MalformedPacketError):
        server_side.receive(timeout=2)


def test_oversized_length_raises_before_reading_payload(pair) -> None:
    client, server_side = pair
    data = bytearray(p.make_ping().encode())
    data[14:18] = (MAX_PAYLOAD_SIZE + 1).to_bytes(4, "big")
    client._sock.sendall(bytes(data))
    with pytest.raises(PayloadTooLargeError):
        server_side.receive(timeout=2)


def test_send_oversized_payload_raises_and_keeps_connection(pair) -> None:
    client, _ = pair
    with pytest.raises(PayloadTooLargeError):
        client.send(p.Packet(p.MessageType.FILE_CHUNK, payload=bytes(MAX_PAYLOAD_SIZE + 1)))
    assert client.is_open


def test_receive_after_peer_closes_raises_connection_closed(pair) -> None:
    client, server_side = pair
    client.close()
    with pytest.raises(ConnectionClosedError):
        server_side.receive(timeout=2)
    assert not server_side.is_open


def test_packet_sent_before_close_is_still_delivered(pair) -> None:
    client, server_side = pair
    client.send(p.make_bye())
    client.close()
    assert server_side.receive(timeout=2).type.name == "BYE"
    with pytest.raises(ConnectionClosedError):
        server_side.receive(timeout=2)


def test_close_is_idempotent_and_blocks_further_use(pair) -> None:
    client, _ = pair
    client.close()
    client.close()
    assert not client.is_open
    with pytest.raises(ConnectionClosedError):
        client.send(p.make_ping())
    with pytest.raises(ConnectionClosedError):
        client.receive(timeout=0.1)


def test_close_wakes_up_a_blocked_receive(pair) -> None:
    client, _ = pair
    errors: list[Exception] = []

    def wait() -> None:
        try:
            client.receive(timeout=5)
        except ConnectionClosedError as exc:
            errors.append(exc)

    thread = threading.Thread(target=wait)
    thread.start()
    time.sleep(0.1)
    client.close()
    thread.join(timeout=2)
    assert not thread.is_alive() and len(errors) == 1


def test_concurrent_senders_do_not_interleave_packets(pair) -> None:
    client, server_side = pair
    per_thread = 100

    def spam(tag: str) -> None:
        for i in range(per_thread):
            client.send(p.make_chat(f"{tag}-{i}" + "x" * 500))

    threads = [threading.Thread(target=spam, args=(f"t{n}",)) for n in range(4)]
    for t in threads:
        t.start()
    total = 4 * per_thread
    received = [server_side.receive(timeout=5).json_payload()["text"] for _ in range(total)]
    for t in threads:
        t.join()
    assert len(set(received)) == total


def test_short_receive_timeouts_do_not_break_a_concurrent_large_send(pair) -> None:
    client, server_side = pair
    stop = threading.Event()

    def poll() -> None:
        while not stop.is_set():
            try:
                client.receive(timeout=0.001)
            except TransportTimeoutError:
                continue
            except ConnectionClosedError:
                return

    poller = threading.Thread(target=poll)
    poller.start()
    big = p.Packet(p.MessageType.FILE_CHUNK, payload=b"z" * MAX_PAYLOAD_SIZE)
    try:
        for _ in range(30):
            client.send(big)
            assert server_side.receive(timeout=5).payload == big.payload
        assert client.is_open
    finally:
        stop.set()
        poller.join(timeout=2)


def test_set_network_conditions_is_a_noop_for_tcp(pair) -> None:
    client, _ = pair
    client.set_network_conditions(loss_rate=0.3, delay_ms=100)
    assert client.is_open


def test_set_window_size_is_a_noop_for_tcp(pair) -> None:
    client, _ = pair
    client.set_window_size(8)
    assert client.is_open


def test_stats_count_packets_and_bytes(pair) -> None:
    client, server_side = pair
    packet = p.make_chat("count me")
    client.send(packet)
    server_side.receive(timeout=2)
    size = len(packet.encode())
    assert client.stats.packets_sent == 1 and client.stats.bytes_sent == size
    assert server_side.stats.packets_received == 1 and server_side.stats.bytes_received == size


def test_events_are_published_with_required_keys(listener: TcpListener) -> None:
    bus = EventBus()
    events = bus.subscribe_queue()
    client = TcpTransport.connect(HOST, listener.bound_address[1], bus)
    server_side = listener.accept(timeout=2)
    try:
        client.send(p.make_ping())
        server_side.receive(timeout=2)
        event = events.get(timeout=1)
        assert event.type is EventType.PACKET_SENT
        event.validate()
        assert event.data["summary"].startswith("PING")
    finally:
        client.close()
        server_side.close()


def test_create_functions_return_tcp_objects_in_tcp_mode() -> None:
    tcp_listener = create_listener(TransportMode.TCP)
    assert isinstance(tcp_listener, TcpListener)
    tcp_listener.start(HOST, 0)
    try:
        client = create_transport(TransportMode.TCP, HOST, tcp_listener.bound_address[1])
        assert isinstance(client, TcpTransport)
        client.close()
    finally:
        tcp_listener.close()
