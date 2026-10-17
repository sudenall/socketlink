"""Reliable data transfer over UDP: Go-Back-N with cumulative ACKs.

OWNER: Yiğit
SPEC:  docs/PROTOCOL.md section 6
MUST implement the Transport / TransportListener interfaces from
common/transport.py exactly, so ChatServer and ChatClient work unchanged.

Summary of the algorithm (details in the spec):
- Sender keeps a window of at most `window_size` un-ACKed packets (window 1 = Stop-and-Wait).
- Every data packet gets seq = next_seq (starting at 1) and flag ACK_REQUIRED.
- Receiver accepts only seq == expected_seq; it always replies ACK(ack=expected_seq - 1)
  (cumulative). Out-of-order and duplicate packets are discarded and re-ACKed.
- Timer on the oldest un-ACKed packet; on RETRANSMIT_TIMEOUT resend the WHOLE window
  (flag RETRANSMISSION), count `retransmissions`, publish PACKET_RETRANSMITTED.
- After MAX_RETRIES on the same packet -> close and raise TransportTimeoutError.
- ACK packets themselves are never ACKed and use seq = 0.
- Loss/delay simulation happens in LossSimulator just before sendto().
"""

from __future__ import annotations

from socketlink.common.events import EventBus
from socketlink.common.protocol import Packet
from socketlink.common.transport import Address, Transport, TransportListener


class ReliableUdpTransport(Transport):
    """One logical connection to one peer over a UDP socket."""

    @classmethod
    def connect(cls, host: str, port: int,
                event_bus: EventBus | None = None) -> ReliableUdpTransport:
        """Client side: create own UDP socket, peer = (host, port)."""
        raise NotImplementedError("TODO(Yiğit)")

    def send(self, packet: Packet) -> None:
        """Blocks while the window is full."""
        raise NotImplementedError("TODO(Yiğit)")

    def receive(self, timeout: float | None = None) -> Packet:
        raise NotImplementedError("TODO(Yiğit)")

    def close(self) -> None:
        raise NotImplementedError("TODO(Yiğit)")

    @property
    def peer_address(self) -> Address:
        raise NotImplementedError("TODO(Yiğit)")

    @property
    def is_open(self) -> bool:
        raise NotImplementedError("TODO(Yiğit)")

    def set_network_conditions(self, loss_rate: float = 0.0, delay_ms: int = 0) -> None:
        raise NotImplementedError("TODO(Yiğit)")

    def set_window_size(self, window_size: int) -> None:
        raise NotImplementedError("TODO(Yiğit)")


class ReliableUdpListener(TransportListener):
    """Server side. ONE UDP socket for all clients; a 'udp-demux' thread reads every
    datagram and routes it by source address to that client's ReliableUdpTransport.
    A datagram from an unknown address whose packet is HELLO creates a new transport,
    which accept() then returns."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus

    def start(self, host: str, port: int) -> None:
        raise NotImplementedError("TODO(Yiğit)")

    def accept(self, timeout: float | None = None) -> Transport:
        raise NotImplementedError("TODO(Yiğit)")

    def close(self) -> None:
        raise NotImplementedError("TODO(Yiğit)")

    @property
    def bound_address(self) -> Address:
        raise NotImplementedError("TODO(Yiğit)")
