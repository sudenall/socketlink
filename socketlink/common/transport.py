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

from abc import ABC, abstractmethod

from socketlink.common.constants import TransportMode
from socketlink.common.events import EventBus
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
    """Packet framing over a TCP stream: read HEADER_SIZE bytes, then `length` bytes."""

    @classmethod
    def connect(cls, host: str, port: int, event_bus: EventBus | None = None) -> TcpTransport:
        """Open a client connection (CONNECT_TIMEOUT). Raises ConnectionRefusedError, OSError."""
        raise NotImplementedError("TODO(Sude)")

    def send(self, packet: Packet) -> None:
        raise NotImplementedError("TODO(Sude)")

    def receive(self, timeout: float | None = None) -> Packet:
        raise NotImplementedError("TODO(Sude)")

    def close(self) -> None:
        raise NotImplementedError("TODO(Sude)")

    @property
    def peer_address(self) -> Address:
        raise NotImplementedError("TODO(Sude)")

    @property
    def is_open(self) -> bool:
        raise NotImplementedError("TODO(Sude)")


class TcpListener(TransportListener):
    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus

    def start(self, host: str, port: int) -> None:
        raise NotImplementedError("TODO(Sude)")

    def accept(self, timeout: float | None = None) -> Transport:
        raise NotImplementedError("TODO(Sude)")

    def close(self) -> None:
        raise NotImplementedError("TODO(Sude)")

    @property
    def bound_address(self) -> Address:
        raise NotImplementedError("TODO(Sude)")


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
