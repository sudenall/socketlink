"""Transport abstraction (Strategy pattern) + the TCP implementation.

OWNER: Sude (interfaces + TCP). The reliable UDP implementation lives in
       socketlink/reliability/reliable_udp.py (owner: Yiğit) and MUST implement
       the same two interfaces below.

Why: ChatServer and ChatClient only talk to `Transport` / `TransportListener`.
They never call socket.send/recv themselves and never check which mode is active.
Switching TCP <-> UDP is therefore a one-line change in `create_transport()` /
`create_listener()`.
"""

from __future__ import annotations

import select
import socket
import sys
import threading
import time
from abc import ABC, abstractmethod
from typing import Any

from socketlink.common.constants import (
    CONNECT_TIMEOUT,
    HEADER_SIZE,
    LISTEN_BACKLOG,
    SOCKET_TIMEOUT,
    TransportMode,
)
from socketlink.common.events import Event, EventBus, EventType
from socketlink.common.exceptions import (
    BadChecksumError,
    ConnectionClosedError,
    TransportError,
    TransportTimeoutError,
)
from socketlink.common.protocol import Packet
from socketlink.common.stats import TransportStats

Address = tuple[str, int]  # (ip, port)


class Transport(ABC):
    """A bidirectional, packet-oriented connection to ONE peer."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus
        self.stats = TransportStats()

    @abstractmethod
    def send(self, packet: Packet) -> None:
        """Send one packet. Thread-safe. Raises ConnectionClosedError, TransportError."""

    @abstractmethod
    def receive(self, timeout: float | None = None) -> Packet:
        """Block until one complete, valid packet arrives.

        Raises TransportTimeoutError on timeout, ConnectionClosedError when the peer
        is gone. Corrupted packets are counted, published as PACKET_CORRUPTED and
        skipped (never returned).
        """

    @abstractmethod
    def close(self) -> None:
        """Idempotent. Release the socket; further send/receive raise ConnectionClosedError."""

    @property
    @abstractmethod
    def peer_address(self) -> Address: ...

    @property
    @abstractmethod
    def is_open(self) -> bool: ...

    def set_network_conditions(self, loss_rate: float = 0.0, delay_ms: int = 0) -> None:
        """Configure simulated loss/delay. TCP ignores it (no-op); reliable UDP overrides."""
        return None

    def set_window_size(self, window_size: int) -> None:
        """Configure the sliding window. TCP ignores it (no-op); reliable UDP overrides."""
        return None


class TransportListener(ABC):
    """Server-side object that produces one Transport per connecting client."""

    @abstractmethod
    def start(self, host: str, port: int) -> None:
        """Bind and start listening. Raises OSError if the port is in use."""

    @abstractmethod
    def accept(self, timeout: float | None = None) -> Transport:
        """Block until a new client connects. Raises TransportTimeoutError on timeout."""

    @abstractmethod
    def close(self) -> None:
        """Stop listening and release the socket. Idempotent."""

    @property
    @abstractmethod
    def bound_address(self) -> Address:
        """Actual (ip, port) after start(). Tests start on port 0 (OS picks a free port)
        and read the real port from here, so parallel test runs never collide."""


# ---------------------------------------------------------------------- #
# TCP implementation (owner: Sude)
# ---------------------------------------------------------------------- #
class TcpTransport(Transport):
    """Packet framing over a TCP stream: read HEADER_SIZE bytes, then `length` bytes.

    Bytes that arrive before a packet is complete stay in an internal buffer, so a
    receive() timeout in the middle of a packet never desynchronises the stream.
    """

    def __init__(self, sock: socket.socket, peer_address: Address,
                 event_bus: EventBus | None = None) -> None:
        super().__init__(event_bus)
        self._sock = sock
        self._peer_address = peer_address
        self._buffer = bytearray()
        self._is_open = True
        self._send_lock = threading.Lock()
        self._recv_lock = threading.Lock()
        self._close_lock = threading.Lock()

    @classmethod
    def connect(cls, host: str, port: int, event_bus: EventBus | None = None) -> TcpTransport:
        """Open a client connection (CONNECT_TIMEOUT). Raises ConnectionRefusedError, OSError."""
        sock = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
        sock.settimeout(None)  # blocking from now on; receive() waits with select()
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return cls(sock, (host, port), event_bus)

    def send(self, packet: Packet) -> None:
        data = packet.encode()
        with self._send_lock:
            if not self._is_open:
                raise ConnectionClosedError("Cannot send: the connection is closed.")
            try:
                self._sock.sendall(data)
            except OSError as exc:
                self.close()
                raise ConnectionClosedError(f"Connection lost while sending: {exc}") from exc
        self.stats.add(packets_sent=1, bytes_sent=len(data))
        self._publish(EventType.PACKET_SENT, {"summary": packet.summary()})

    def receive(self, timeout: float | None = None) -> Packet:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._recv_lock:
            while True:
                self._fill(HEADER_SIZE, deadline)
                _, _, _, _, length, _ = Packet.parse_header(bytes(self._buffer[:HEADER_SIZE]))
                total = HEADER_SIZE + length
                self._fill(total, deadline)
                data = bytes(self._buffer[:total])
                del self._buffer[:total]
                try:
                    packet = Packet.decode(data)
                except BadChecksumError:
                    # The whole packet was consumed, so the stream is still aligned.
                    self.stats.add(checksum_errors=1)
                    self._publish(EventType.PACKET_CORRUPTED, {"reason": "checksum"})
                    continue
                self.stats.add(packets_received=1, bytes_received=total)
                self._publish(EventType.PACKET_RECEIVED, {"summary": packet.summary()})
                return packet

    def close(self) -> None:
        with self._close_lock:
            if not self._is_open:
                return
            self._is_open = False
        try:
            self._sock.shutdown(socket.SHUT_RDWR)  # wakes up a thread blocked in recv()
        except OSError:
            pass
        self._sock.close()

    @property
    def peer_address(self) -> Address:
        return self._peer_address

    @property
    def is_open(self) -> bool:
        return self._is_open

    def _fill(self, size: int, deadline: float | None) -> None:
        """Grow the buffer to at least `size` bytes without consuming anything.

        The socket stays in blocking mode so a concurrent send() is never affected by a
        receive() timeout; waiting is done with select() in slices of SOCKET_TIMEOUT so
        close() from another thread is noticed.
        """
        while len(self._buffer) < size:
            if not self._is_open:
                raise ConnectionClosedError("The connection is closed.")
            wait = SOCKET_TIMEOUT
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TransportTimeoutError("No complete packet within the timeout.")
                wait = min(wait, remaining)
            try:
                readable, _, _ = select.select([self._sock], [], [], wait)
                if not readable:
                    continue
                chunk = self._sock.recv(size - len(self._buffer))
            except (OSError, ValueError) as exc:  # ValueError: socket closed under select()
                self.close()
                raise ConnectionClosedError(f"Connection lost while receiving: {exc}") from exc
            if not chunk:
                self.close()
                raise ConnectionClosedError("The peer closed the connection.")
            self._buffer.extend(chunk)

    def _publish(self, event_type: EventType, data: dict[str, Any]) -> None:
        if self.event_bus is not None:
            self.event_bus.publish(Event(event_type, data, source="transport"))


class TcpListener(TransportListener):
    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus
        self._sock: socket.socket | None = None
        self._bound_address: Address | None = None

    def start(self, host: str, port: int) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if sys.platform != "win32":  # on Windows SO_REUSEADDR lets two servers share a port
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            sock.listen(LISTEN_BACKLOG)
        except OSError:
            sock.close()
            raise
        self._sock = sock
        self._bound_address = sock.getsockname()[:2]

    def accept(self, timeout: float | None = None) -> Transport:
        sock = self._sock
        if sock is None:
            raise ConnectionClosedError("The listener is not running.")
        try:
            sock.settimeout(timeout)
            client_sock, address = sock.accept()
        except TimeoutError:
            raise TransportTimeoutError("No client connected within the timeout.") from None
        except OSError as exc:
            raise ConnectionClosedError(f"The listener was closed: {exc}") from exc
        client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return TcpTransport(client_sock, address[:2], self.event_bus)

    def close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is not None:
            sock.close()

    @property
    def bound_address(self) -> Address:
        if self._bound_address is None:
            raise TransportError("The listener has not been started.")
        return self._bound_address


# ---------------------------------------------------------------------- #
# Factories: the ONLY place where the mode is checked
# ---------------------------------------------------------------------- #
def create_transport(mode: TransportMode, host: str, port: int,
                     event_bus: EventBus | None = None) -> Transport:
    """Client side: return a connected Transport for the chosen mode."""
    if mode is TransportMode.TCP:
        return TcpTransport.connect(host, port, event_bus)
    from socketlink.reliability.reliable_udp import ReliableUdpTransport

    return ReliableUdpTransport.connect(host, port, event_bus)


def create_listener(mode: TransportMode, event_bus: EventBus | None = None) -> TransportListener:
    """Server side: return a (not yet started) listener for the chosen mode."""
    if mode is TransportMode.TCP:
        return TcpListener(event_bus)
    from socketlink.reliability.reliable_udp import ReliableUdpListener

    return ReliableUdpListener(event_bus)
