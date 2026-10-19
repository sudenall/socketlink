"""Reliable data transfer over UDP: Go-Back-N with cumulative ACKs.

OWNER: Yiğit
SPEC:  docs/PROTOCOL.md section 6
MUST implement the Transport / TransportListener interfaces from
common/transport.py exactly, so ChatServer and ChatClient work unchanged.
"""

from __future__ import annotations

import queue
import select
import socket
import threading
import time
from typing import Any

from socketlink.common.constants import (
    DEFAULT_WINDOW_SIZE,
    MAX_RETRIES,
    RETRANSMIT_TIMEOUT,
    PacketFlag,
)
from socketlink.common.events import Event, EventBus, EventType
from socketlink.common.exceptions import (
    BadChecksumError,
    ConnectionClosedError,
    MalformedPacketError,
    TransportError,
    TransportTimeoutError,
)
from socketlink.common.protocol import Packet, make_ack
from socketlink.common.transport import Address, Transport, TransportListener
from socketlink.reliability.loss_simulator import LossSimulator


class ReliableUdpTransport(Transport):
    """One logical connection to one peer over a UDP socket using Go-Back-N."""

    def __init__(
        self,
        sock: socket.socket,
        peer_address: Address,
        is_server_side: bool = False,
        event_bus: EventBus | None = None,
    ) -> None:
        super().__init__(event_bus)
        self._sock = sock
        self._peer_address = peer_address
        self._is_server_side = is_server_side
        self._is_open = True

        self._window_size = DEFAULT_WINDOW_SIZE
        self._loss_simulator = LossSimulator()

        # Synchronization and State
        self._lock = threading.Lock()
        self._send_cond = threading.Condition(self._lock)
        self._recv_queue: queue.Queue[Packet] = queue.Queue()

        # Go-Back-N Sender State
        self._base = 1
        self._next_seq = 1
        self._unacked_buffer: dict[int, Packet] = {}
        self._retry_count = 0
        self._timer: threading.Timer | None = None

        # Go-Back-N Receiver State
        self._expected_seq = 1
        self._last_ack_sent = 0

        # Background listener/receiver thread (if client-side standalone)
        self._stop_event = threading.Event()
        self._recv_thread: threading.Thread | None = None

        if not self._is_server_side:
            self._recv_thread = threading.Thread(
                target=self._client_receive_loop,
                daemon=True,
                name="udp-client-recv",
            )
            self._recv_thread.start()

    @classmethod
    def connect(
        cls, host: str, port: int, event_bus: EventBus | None = None
    ) -> ReliableUdpTransport:
        """Client side: create own UDP socket, peer = (host, port)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        peer_addr = (host, port)
        transport = cls(sock, peer_addr, is_server_side=False, event_bus=event_bus)
        return transport

    def send(self, packet: Packet) -> None:
        """Blocks while the window is full, assigns seq, and sends via GBN."""
        with self._send_cond:
            while self._is_open and (self._next_seq >= self._base + self._window_size):
                self._send_cond.wait(timeout=0.1)

            if not self._is_open:
                raise ConnectionClosedError("Cannot send: connection is closed.")

            seq = self._next_seq
            self._next_seq += 1

            packet.seq = seq
            packet.flags |= PacketFlag.ACK_REQUIRED

            self._unacked_buffer[seq] = packet

            if self._base == seq:
                self._start_timer()

            self._raw_send(packet)
            self.stats.add(packets_sent=1, bytes_sent=len(packet.encode()))
            self._publish(EventType.PACKET_SENT, {"summary": packet.summary()})

    def receive(self, timeout: float | None = None) -> Packet:
        """Block until one complete, valid packet arrives from application queue."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while self._is_open:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TransportTimeoutError("Receive timed out.")
                wait_time = min(remaining, 0.1)
            else:
                wait_time = 0.1

            try:
                packet = self._recv_queue.get(timeout=wait_time)
                return packet
            except queue.Empty:
                continue

        raise ConnectionClosedError("Connection is closed.")

    def close(self) -> None:
        """Idempotent release of resources."""
        with self._lock:
            if not self._is_open:
                return
            self._is_open = False
            self._stop_event.set()
            self._cancel_timer()
            self._send_cond.notify_all()

        if self._recv_thread is not None:
            is_alive = getattr(self._recv_thread, "is_alive", None)
            if is_alive and is_alive():
                if threading.current_thread() != self._recv_thread:
                    self._recv_thread.join(timeout=0.5)

        if not self._is_server_side:
            try:
                self._sock.close()
            except OSError:
                pass

    @property
    def peer_address(self) -> Address:
        return self._peer_address

    @property
    def is_open(self) -> bool:
        return self._is_open

    def set_network_conditions(
        self, loss_rate: float = 0.0, delay_ms: int = 0
    ) -> None:
        with self._lock:
            self._loss_simulator = LossSimulator(
                loss_rate=loss_rate, delay_ms=delay_ms
            )

    def set_window_size(self, window_size: int) -> None:
        with self._lock:
            self._window_size = max(1, window_size)
            self._send_cond.notify_all()

    # ------------------------------------------------------------------ #
    # Internal GBN and Network Logic
    # ------------------------------------------------------------------ #

    def _raw_send(self, packet: Packet, is_retransmission: bool = False) -> None:
        if is_retransmission:
            packet.flags |= PacketFlag.RETRANSMISSION
        data = packet.encode()

        if self._loss_simulator.should_drop():
            self.stats.add(packets_dropped_simulated=1)
            self._publish(EventType.PACKET_DROPPED, {"summary": packet.summary()})
            return

        delay = self._loss_simulator.delay_seconds()

        def _do_send() -> None:
            try:
                self._sock.sendto(data, self._peer_address)
            except OSError:
                pass

        if delay > 0:
            threading.Timer(delay, _do_send).start()
        else:
            _do_send()

    def _feed_datagram(self, data: bytes) -> None:
        """Called by Listener demux thread or client receive loop."""
        try:
            packet = Packet.decode(data)
        except (BadChecksumError, MalformedPacketError):
            self.stats.add(checksum_errors=1)
            self._publish(EventType.PACKET_CORRUPTED, {"reason": "checksum"})
            return

        self.stats.add(packets_received=1, bytes_received=len(data))
        self._publish(EventType.PACKET_RECEIVED, {"summary": packet.summary()})

        with self._lock:
            # If it's an ACK packet (MessageType.ACK = 4)
            if packet.type.value == 4:
                self._handle_ack(packet.ack)
                return

            # Otherwise, it's a Data packet
            if packet.seq == self._expected_seq:
                self._expected_seq += 1
                self._last_ack_sent = packet.seq
                self._send_ack(packet.seq)
                self._recv_queue.put(packet)
            else:
                if packet.seq < self._expected_seq:
                    self.stats.add(duplicates_received=1)
                if self._last_ack_sent > 0:
                    self._send_ack(self._last_ack_sent)

    def _send_ack(self, ack_num: int) -> None:
        ack_pkt = make_ack(ack_num)
        self._raw_send(ack_pkt)

    def _handle_ack(self, ack_num: int) -> None:
        if ack_num >= self._base:
            while self._base <= ack_num:
                self._unacked_buffer.pop(self._base, None)
                self._base += 1

            self._retry_count = 0
            self._cancel_timer()

            if self._unacked_buffer:
                self._start_timer()

            self._send_cond.notify_all()

    def _start_timer(self) -> None:
        self._cancel_timer()
        self._timer = threading.Timer(RETRANSMIT_TIMEOUT, self._handle_timeout)
        self._timer.daemon = True
        self._timer.start()

    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _handle_timeout(self) -> None:
        with self._lock:
            if not self._is_open or not self._unacked_buffer:
                return

            self._retry_count += 1
            if self._retry_count > MAX_RETRIES:
                self._is_open = False
                self._send_cond.notify_all()
                raise TransportTimeoutError(
                    "Max retries exceeded in Reliable UDP."
                )

            for seq in sorted(self._unacked_buffer.keys()):
                pkt = self._unacked_buffer[seq]
                self.stats.add(retransmissions=1)
                self._publish(
                    EventType.PACKET_RETRANSMITTED,
                    {"summary": pkt.summary(), "attempt": self._retry_count},
                )
                self._raw_send(pkt, is_retransmission=True)

            self._start_timer()

    def _client_receive_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                readable, _, _ = select.select([self._sock], [], [], 0.2)
                if readable:
                    data, addr = self._sock.recvfrom(65535)
                    if addr == self._peer_address:
                        self._feed_datagram(data)
            except OSError:
                break

    def _publish(self, event_type: EventType, data: dict[str, Any]) -> None:
        if self.event_bus is not None:
            self.event_bus.publish(Event(event_type, data, source="transport"))


class ReliableUdpListener(TransportListener):
    """Server side: ONE UDP socket for all clients with a demux thread."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus
        self._sock: socket.socket | None = None
        self._bound_address: Address | None = None
        self._sessions: dict[Address, ReliableUdpTransport] = {}
        self._accept_queue: queue.Queue[ReliableUdpTransport] = queue.Queue()
        self._stop_event = threading.Event()
        self._demux_thread: threading.Thread | None = None

    def start(self, host: str, port: int) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((host, port))
        self._sock = sock
        self._bound_address = sock.getsockname()[:2]

        self._demux_thread = threading.Thread(
            target=self._demux_loop, daemon=True, name="udp-demux"
        )
        self._demux_thread.start()

    def accept(self, timeout: float | None = None) -> Transport:
        if self._sock is None:
            raise ConnectionClosedError("Listener is not running.")
        try:
            return self._accept_queue.get(timeout=timeout)
        except queue.Empty:
            raise TransportTimeoutError(
                "No client connected within timeout."
            ) from None

    def close(self) -> None:
        self._stop_event.set()
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

        if self._demux_thread and self._demux_thread.is_alive():
            self._demux_thread.join(timeout=0.5)

        for transport in list(self._sessions.values()):
            transport.close()
        self._sessions.clear()

    @property
    def bound_address(self) -> Address:
        if self._bound_address is None:
            raise TransportError("Listener has not been started.")
        return self._bound_address

    def _demux_loop(self) -> None:
        while not self._stop_event.is_set() and self._sock is not None:
            try:
                readable, _, _ = select.select([self._sock], [], [], 0.2)
                if not readable or self._sock is None:
                    continue
                data, addr = self._sock.recvfrom(65535)

                try:
                    packet = Packet.decode(data)
                except Exception:
                    if addr in self._sessions:
                        self._sessions[addr]._feed_datagram(data)
                    continue

                if addr in self._sessions:
                    self._sessions[addr]._feed_datagram(data)
                else:
                    if packet.type.value == 1:  # MessageType.HELLO = 1
                        new_transport = ReliableUdpTransport(
                            self._sock,
                            addr,
                            is_server_side=True,
                            event_bus=self.event_bus,
                        )
                        self._sessions[addr] = new_transport
                        self._accept_queue.put(new_transport)
                        new_transport._feed_datagram(data)
            except OSError:
                break
