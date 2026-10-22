"""Reliable data transfer over UDP: Go-Back-N with cumulative ACKs.

OWNER: Yiğit
SPEC:  docs/PROTOCOL.md section 6
USES:  common/protocol.py (Packet, make_ack), common/transport.py (interfaces),
       reliability/loss_simulator.py
USED BY: common/transport.py factories -> ChatServer (Yusuf), ChatClient (Hamit)
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

Threads (all daemon, all named):
- udp-retransmit-<port>  one per transport: the Go-Back-N timer.
- udp-receiver-<port>    client side only: reads the transport's own socket.
- udp-demux-<port>       server side only: reads the shared socket, routes by address.
- udp-delay-<port>       started on the first delayed packet; sends them in FIFO order
                         (separate timers could reorder packets and fake losses).

Closing: close() returns at once and send()/receive() fail from then on, but packets
that are still un-ACKed (typically a final BYE or ERROR) keep being retransmitted in
the background until they are ACKed or MAX_RETRIES is reached. Only then is the socket
released. Without this a BYE lost by the simulator would never reach the peer, because
UDP has no FIN of its own.
"""

from __future__ import annotations

import queue
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from socketlink.common.constants import (
    DEFAULT_WINDOW_SIZE,
    HEADER_SIZE,
    MAX_PAYLOAD_SIZE,
    MAX_RETRIES,
    MAX_SIMULATED_DELAY_MS,
    MAX_WINDOW_SIZE,
    RETRANSMIT_TIMEOUT,
    SOCKET_TIMEOUT,
    ErrorCode,
    MessageType,
    PacketFlag,
)
from socketlink.common.events import Event, EventBus, EventType
from socketlink.common.exceptions import (
    BadChecksumError,
    ConnectionClosedError,
    ProtocolError,
    TransportError,
    TransportTimeoutError,
    ValidationError,
)
from socketlink.common.logger import get_logger
from socketlink.common.protocol import Packet, make_ack
from socketlink.common.transport import Address, Transport, TransportListener
from socketlink.reliability.loss_simulator import LossSimulator

log = get_logger(__name__)


def _max_datagram_size() -> int:
    """Largest datagram a peer may legally send: one header plus the biggest payload."""
    return HEADER_SIZE + MAX_PAYLOAD_SIZE


def _listener_linger_seconds() -> float:
    """How long a closed listener keeps serving sessions that are still finishing (a BYE in
    flight): one full retry budget of the Go-Back-N timer."""
    return RETRANSMIT_TIMEOUT * (MAX_RETRIES + 1)


def _enlarge_send_buffer(sock: socket.socket) -> None:
    """Let the socket send a full-size datagram. Best effort.

    macOS lets an application send a datagram only if it fits into SO_SNDBUF, and the
    default is 9216 bytes, so a full-size packet fails there with "[Errno 40] Message too
    long" (Linux and Windows do not have this limit). Room for two full datagrams fixes it.
    """
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 2 * _max_datagram_size())
    except OSError as exc:
        log.debug("Could not enlarge SO_SNDBUF: %s", exc)


@dataclass
class _InFlight:
    """A data packet that was sent but is not ACKed yet."""

    packet: Packet
    first_sent_at: float
    is_retransmitted: bool = False


class ReliableUdpTransport(Transport):
    """One logical connection to one peer over a UDP socket."""

    def __init__(self, sock: socket.socket, peer_address: Address,
                 event_bus: EventBus | None = None, *, has_own_socket: bool = True,
                 on_released: Callable[[ReliableUdpTransport], None] | None = None) -> None:
        """Wrap a UDP socket. Use connect() (client) or ReliableUdpListener (server).

        `has_own_socket` is False for server-side transports: they share the listener's
        socket and must not close it. `on_released` is called once when the transport
        has finished (used by the listener to forget the session).
        """
        super().__init__(event_bus)
        self._sock = sock
        self._peer_address: Address = peer_address
        self._has_own_socket = has_own_socket
        self._on_released = on_released
        self.loss_simulator = LossSimulator()  # public so tests can inject a seeded rng
        self._window_size = DEFAULT_WINDOW_SIZE

        self._lock = threading.Lock()
        self._state_changed = threading.Condition(self._lock)
        self._send_lock = threading.Lock()  # keeps the wire order of concurrent send() calls
        self._stop_event = threading.Event()

        # sender state (guarded by _lock)
        self._next_seq = 1
        self._base = 1
        self._unacked: dict[int, _InFlight] = {}  # insertion order == seq order
        self._timer_started_at: float | None = None
        self._retry_count = 0
        self._rtt_samples = 0
        self._rtt_total_ms = 0.0
        # receiver state (guarded by _lock)
        self._expected_seq = 1
        self._inbox: queue.Queue[Packet | None] = queue.Queue()
        # lifecycle (guarded by _lock)
        self._is_open = True
        self._is_released = False
        self._failure: str | None = None
        # simulated delay: one FIFO "delay line" thread, created on first use
        self._delayed: queue.Queue[tuple[float, bytes, Packet]] = queue.Queue()
        self._delay_thread: threading.Thread | None = None

        self._retransmit_thread = threading.Thread(
            target=self._retransmit_loop, name=f"udp-retransmit-{peer_address[1]}", daemon=True
        )
        self._retransmit_thread.start()

    # ------------------------------------------------------------------ #
    # Transport interface
    # ------------------------------------------------------------------ #
    @classmethod
    def connect(cls, host: str, port: int,
                event_bus: EventBus | None = None) -> ReliableUdpTransport:
        """Client side: create own UDP socket, peer = (host, port).

        UDP has no handshake, so this never waits; the application's HELLO is the
        first packet. Raises OSError (e.g. socket.gaierror) if the host is invalid.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            _enlarge_send_buffer(sock)
            sock.connect((host, port))  # only fixes the peer; also lets ICMP errors through
            sock.settimeout(SOCKET_TIMEOUT)
            peer_host, peer_port = sock.getpeername()[:2]
        except OSError:
            sock.close()
            raise
        transport = cls(sock, (peer_host, peer_port), event_bus, has_own_socket=True)
        transport._start_receiver()
        return transport

    def send(self, packet: Packet) -> None:
        """Blocks while the window is full.

        Raises PayloadTooLargeError (connection stays open), TransportTimeoutError if the
        connection died after MAX_RETRIES, ConnectionClosedError if it is closed.
        """
        packet.encode()  # validates the size before a sequence number is used up
        if packet.type is MessageType.ACK:
            self._send_packet(packet)  # ACKs are never ACKed themselves (seq stays 0)
            return
        with self._send_lock:
            with self._state_changed:
                while (self._is_open and self._failure is None
                       and len(self._unacked) >= self._window_size):
                    self._state_changed.wait(SOCKET_TIMEOUT)
                self._raise_if_unusable()
                seq = self._next_seq
                self._next_seq += 1
                outgoing = Packet(type=packet.type, payload=packet.payload, seq=seq,
                                  ack=0, flags=int(packet.flags) | PacketFlag.ACK_REQUIRED)
                now = time.monotonic()
                self._unacked[seq] = _InFlight(outgoing, now)
                if self._timer_started_at is None:
                    self._timer_started_at = now
                self._state_changed.notify_all()  # the timer thread re-computes its deadline
            self._send_packet(outgoing)

    def receive(self, timeout: float | None = None) -> Packet:
        """Return the next in-order data packet.

        Raises TransportTimeoutError on timeout, ConnectionClosedError when the transport
        was closed or the peer stopped answering (MAX_RETRIES exceeded).
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                if not self._is_open:
                    raise ConnectionClosedError(self._closed_message())
            wait = SOCKET_TIMEOUT
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TransportTimeoutError("No packet within the timeout.")
                wait = min(wait, remaining)
            try:
                packet = self._inbox.get(timeout=wait)
            except queue.Empty:
                continue
            if packet is None:  # put by close()/_fail(): the transport ended
                raise ConnectionClosedError(self._closed_message())
            return packet

    def close(self) -> None:
        """Idempotent. Un-ACKed packets are still delivered in the background."""
        with self._state_changed:
            if not self._is_open:
                return
            self._is_open = False
            should_drain = bool(self._unacked) and self._failure is None
            self._state_changed.notify_all()
        self._inbox.put(None)  # wakes up a thread blocked in receive()
        if should_drain:
            log.debug("Closing %s:%d after %d un-ACKed packet(s) are delivered",
                      *self._peer_address, len(self._unacked))
        else:
            self._release()

    @property
    def peer_address(self) -> Address:
        """(host, port) of the peer this transport talks to."""
        return self._peer_address

    @property
    def is_open(self) -> bool:
        """False after close() or after the connection failed (e.g. MAX_RETRIES exceeded)."""
        return self._is_open

    def set_network_conditions(self, loss_rate: float = 0.0, delay_ms: int = 0) -> None:
        """Simulated loss probability (0..1) and one-way delay (0..MAX_SIMULATED_DELAY_MS).

        Applies to every packet this side sends, data and ACKs alike.
        Raises ValidationError for values outside those ranges.
        """
        if not 0.0 <= loss_rate <= 1.0:
            raise ValidationError(f"loss_rate must be between 0 and 1, got {loss_rate}.")
        if not 0 <= delay_ms <= MAX_SIMULATED_DELAY_MS:
            raise ValidationError(
                f"delay_ms must be between 0 and {MAX_SIMULATED_DELAY_MS}, got {delay_ms}."
            )
        self.loss_simulator.loss_rate = loss_rate
        self.loss_simulator.delay_ms = delay_ms

    def set_window_size(self, window_size: int) -> None:
        """Go-Back-N window, 1 (Stop-and-Wait) .. MAX_WINDOW_SIZE. Raises ValidationError.

        A smaller window takes effect as packets in flight are ACKed.
        """
        if not 1 <= window_size <= MAX_WINDOW_SIZE:
            raise ValidationError(
                f"window_size must be between 1 and {MAX_WINDOW_SIZE}, got {window_size}."
            )
        with self._state_changed:
            self._window_size = window_size
            self._state_changed.notify_all()

    # ------------------------------------------------------------------ #
    # Incoming datagrams (receiver thread on the client, udp-demux on the server)
    # ------------------------------------------------------------------ #
    def _handle_datagram(self, data: bytes) -> None:
        """Decode one datagram and run the sender or receiver half of Go-Back-N."""
        try:
            packet = Packet.decode(data)
        except BadChecksumError:
            self.stats.add(checksum_errors=1)
            self._publish(EventType.PACKET_CORRUPTED, {"reason": "checksum"})
            return
        except ProtocolError as exc:
            log.debug("Malformed datagram from %s:%d: %s", *self._peer_address, exc)
            self._publish(EventType.PACKET_CORRUPTED, {"reason": "malformed"})
            return
        self.stats.add(packets_received=1, bytes_received=len(data))
        self._publish(EventType.PACKET_RECEIVED, {"summary": packet.summary()})
        if packet.type is MessageType.ACK:
            self._handle_ack(packet.ack)
        else:
            self._handle_data(packet)

    def _handle_ack(self, ack: int) -> None:
        """Cumulative ACK: every packet up to and including `ack` is delivered."""
        rtt_ms: float | None = None
        with self._state_changed:
            if not self._base <= ack < self._next_seq:
                return  # an old (duplicate) ACK or one for a packet we never sent
            newest = self._unacked.get(ack)
            if newest is not None and not newest.is_retransmitted:  # Karn's algorithm
                elapsed = timedelta(seconds=time.monotonic() - newest.first_sent_at)
                rtt_ms = elapsed / timedelta(milliseconds=1)
            for seq in range(self._base, ack + 1):
                self._unacked.pop(seq, None)
            self._base = ack + 1
            self._retry_count = 0
            self._timer_started_at = time.monotonic() if self._unacked else None
            if rtt_ms is not None:
                old_avg = self._average_rtt_ms()
                self._rtt_samples += 1
                self._rtt_total_ms += rtt_ms
                self.stats.add(avg_rtt_ms=self._average_rtt_ms() - old_avg)
            self._state_changed.notify_all()

    def _handle_data(self, packet: Packet) -> None:
        """Accept only seq == expected_seq; always answer with a cumulative ACK."""
        with self._lock:
            if packet.seq == self._expected_seq and self._is_open:
                self._expected_seq += 1
                self._inbox.put(packet)
            elif 0 < packet.seq < self._expected_seq:
                self.stats.add(duplicates_received=1)  # our ACK was lost: just re-ACK
            # else: out of order (a gap before it) or arrived after close() -> dropped
            ack = self._expected_seq - 1
        self._send_packet(make_ack(ack))

    # ------------------------------------------------------------------ #
    # Outgoing datagrams
    # ------------------------------------------------------------------ #
    def _send_packet(self, packet: Packet) -> None:
        """Apply the loss simulator, then (maybe after a delay) put one datagram on the wire."""
        data = packet.encode()
        if self.loss_simulator.should_drop():
            self.stats.add(packets_dropped_simulated=1)
            self._publish(EventType.PACKET_DROPPED, {"summary": packet.summary()})
            return
        delay = self.loss_simulator.delay_seconds()
        if delay > 0:
            self._start_delay_line()
            self._delayed.put((time.monotonic() + delay, data, packet))
        else:
            self._send_datagram(data, packet)

    def _start_delay_line(self) -> None:
        with self._lock:
            if self._delay_thread is not None:
                return
            self._delay_thread = threading.Thread(
                target=self._delay_loop, name=f"udp-delay-{self._peer_address[1]}", daemon=True
            )
        self._delay_thread.start()

    def _delay_loop(self) -> None:
        """Hold every packet back until its due time, keeping the sending order."""
        while not self._stop_event.is_set():
            try:
                due, data, packet = self._delayed.get(timeout=SOCKET_TIMEOUT)
            except queue.Empty:
                continue
            remaining = due - time.monotonic()
            if remaining > 0 and self._stop_event.wait(remaining):
                return
            self._send_datagram(data, packet)

    def _send_datagram(self, data: bytes, packet: Packet) -> None:
        with self._lock:
            if self._is_released:
                return  # a delayed packet that outlived its transport
        try:
            if self._has_own_socket:
                self._sock.send(data)  # connected socket: macOS refuses sendto() here
            else:
                self._sock.sendto(data, self._peer_address)
        except ConnectionRefusedError:
            self._fail("Nobody is listening on the peer's port.")
            return
        except OSError as exc:
            log.debug("sendto %s:%d failed: %s", *self._peer_address, exc)
            if self._has_own_socket:
                self._fail(f"Socket error while sending: {exc}")
            return  # server side: the shared socket is closing; the retry budget decides
        self.stats.add(packets_sent=1, bytes_sent=len(data))
        if not packet.flags & PacketFlag.RETRANSMISSION:
            self._publish(EventType.PACKET_SENT, {"summary": packet.summary()})

    # ------------------------------------------------------------------ #
    # Threads
    # ------------------------------------------------------------------ #
    def _start_receiver(self) -> None:
        thread = threading.Thread(
            target=self._receiver_loop, name=f"udp-receiver-{self._peer_address[1]}",
            daemon=True,
        )
        thread.start()

    def _receiver_loop(self) -> None:
        """Client side: read the own (connected) socket until the transport is released."""
        while not self._stop_event.is_set():
            try:
                data = self._sock.recv(_max_datagram_size())
            except TimeoutError:
                continue
            except ConnectionRefusedError:  # ICMP port unreachable: no server on that port
                self._fail("Nobody is listening on the peer's port.")
                return
            except OSError as exc:
                if not self._stop_event.is_set():
                    self._fail(f"Socket error while receiving: {exc}")
                return
            try:
                self._handle_datagram(data)
            except Exception as exc:  # noqa: BLE001 - a network thread must never die silently
                log.exception("Unexpected error while handling a datagram")
                self._report_internal_error(exc)
                self._fail(f"Internal error: {exc}")
                return

    def _retransmit_loop(self) -> None:
        """The Go-Back-N timer: resend the whole window when the oldest packet times out."""
        try:
            while not self._stop_event.is_set():
                outcome = self._wait_for_timeout()
                if outcome is None:
                    continue
                if isinstance(outcome, str):
                    self._fail(outcome)
                    return
                attempt, resend = outcome
                if not resend:
                    break  # closed and everything delivered -> release
                for packet in resend:  # outside the lock: never send while holding it
                    self.stats.add(retransmissions=1)
                    self._publish(EventType.PACKET_RETRANSMITTED,
                                  {"summary": packet.summary(), "attempt": attempt})
                    self._send_packet(packet)
        except Exception as exc:  # noqa: BLE001 - a network thread must never die silently
            log.exception("Unexpected error in the retransmission timer")
            self._report_internal_error(exc)
            self._fail(f"Internal error: {exc}")
            return
        self._release()

    def _wait_for_timeout(self) -> tuple[int, list[Packet]] | str | None:
        """Wait (at most SOCKET_TIMEOUT) for the timer of the oldest un-ACKed packet.

        Returns None to keep waiting, (attempt, packets) to resend the window,
        (0, []) when the transport is closed and fully drained, or a failure message
        when MAX_RETRIES is exceeded.
        """
        with self._state_changed:
            if self._stop_event.is_set():
                return None
            if not self._unacked:
                if not self._is_open:
                    return 0, []
                self._state_changed.wait(SOCKET_TIMEOUT)
                return None
            started = self._timer_started_at or time.monotonic()
            remaining = started + RETRANSMIT_TIMEOUT - time.monotonic()
            if remaining > 0:
                self._state_changed.wait(min(remaining, SOCKET_TIMEOUT))
                return None
            if self._retry_count >= MAX_RETRIES:
                return f"Packet seq={self._base} was not ACKed after {MAX_RETRIES} retries."
            self._retry_count += 1
            resend = []
            for in_flight in self._unacked.values():
                in_flight.is_retransmitted = True
                original = in_flight.packet
                resend.append(Packet(
                    type=original.type, payload=original.payload, seq=original.seq, ack=0,
                    flags=int(original.flags) | PacketFlag.RETRANSMISSION,
                ))
            self._timer_started_at = time.monotonic()
            return self._retry_count, resend

    # ------------------------------------------------------------------ #
    # Lifecycle helpers
    # ------------------------------------------------------------------ #
    def _fail(self, reason: str) -> None:
        """The connection is dead (MAX_RETRIES, ICMP refused, socket error): close it."""
        with self._state_changed:
            if self._failure is not None or self._is_released:
                return
            has_been_open = self._is_open
            self._failure = reason
            self._is_open = False
            self._unacked.clear()
            self._state_changed.notify_all()
        if has_been_open:
            log.warning("Reliable UDP connection to %s:%d failed: %s",
                        *self._peer_address, reason)
        else:
            log.debug("Gave up delivering the last packets to %s:%d: %s",
                      *self._peer_address, reason)
        self._inbox.put(None)  # wakes up a thread blocked in receive()
        self._release()

    def _release(self) -> None:
        """Free the socket (or tell the listener) exactly once."""
        with self._state_changed:
            if self._is_released:
                return
            self._is_released = True
            self._is_open = False
            self._stop_event.set()
            self._state_changed.notify_all()
        if self._has_own_socket:
            self._sock.close()
        if self._on_released is not None:
            self._on_released(self)

    def _raise_if_unusable(self) -> None:
        """Caller holds the lock."""
        if self._failure is not None:
            raise TransportTimeoutError(self._failure)
        if not self._is_open:
            raise ConnectionClosedError("Cannot send: the connection is closed.")

    def _closed_message(self) -> str:
        if self._failure is not None:
            return f"The connection is closed: {self._failure}"
        return "The connection is closed."

    def _average_rtt_ms(self) -> float:
        """Caller holds the lock."""
        return self._rtt_total_ms / self._rtt_samples if self._rtt_samples else 0.0

    def _publish(self, event_type: EventType, data: dict[str, Any]) -> None:
        if self.event_bus is not None:
            self.event_bus.publish(Event(event_type, data, source="transport"))

    def _report_internal_error(self, exc: Exception) -> None:
        """Network threads never let an exception escape: tell the GUI through an ERROR event."""
        self._publish(EventType.ERROR, {
            "code": ErrorCode.INTERNAL_ERROR.value,
            "message": f"Reliable UDP internal error: {exc}",
        })


class ReliableUdpListener(TransportListener):
    """Server side. ONE UDP socket for all clients; a 'udp-demux' thread reads every
    datagram and routes it by source address to that client's ReliableUdpTransport.
    A datagram from an unknown address whose packet is HELLO creates a new transport,
    which accept() then returns."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        """Create a listener that is not bound yet; call start()."""
        self.event_bus = event_bus
        self._sock: socket.socket | None = None
        self._bound_address: Address | None = None
        self._sessions: dict[Address, ReliableUdpTransport] = {}
        self._lock = threading.Lock()
        self._pending: queue.Queue[ReliableUdpTransport] = queue.Queue()
        self._stop_event = threading.Event()   # set by close(): no new sessions
        self._closed_at: float | None = None
        self._demux_thread: threading.Thread | None = None

    def start(self, host: str, port: int) -> None:
        """Bind the shared UDP socket and start the udp-demux thread. Raises OSError."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            _enlarge_send_buffer(sock)
            sock.bind((host, port))
            sock.settimeout(SOCKET_TIMEOUT)
            if hasattr(socket, "SIO_UDP_CONNRESET"):  # Windows: no WSAECONNRESET on recvfrom
                sock.ioctl(socket.SIO_UDP_CONNRESET, False)
        except OSError:
            sock.close()
            raise
        self._sock = sock
        self._bound_address = sock.getsockname()[:2]
        self._demux_thread = threading.Thread(
            target=self._demux_loop, args=(sock,), name=f"udp-demux-{self._bound_address[1]}",
            daemon=True,
        )
        self._demux_thread.start()

    def accept(self, timeout: float | None = None) -> Transport:
        """Return the transport of the next client that sent HELLO.

        Raises TransportTimeoutError on timeout, ConnectionClosedError if not running.
        """
        if self._sock is None:
            raise ConnectionClosedError("The listener is not running.")
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            if self._stop_event.is_set():
                raise ConnectionClosedError("The listener was closed.")
            wait = SOCKET_TIMEOUT
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TransportTimeoutError("No client connected within the timeout.")
                wait = min(wait, remaining)
            try:
                return self._pending.get(timeout=wait)
            except queue.Empty:
                continue

    def close(self) -> None:
        """Stop accepting new clients. Idempotent.

        Sessions that were already accepted keep working until they are closed (like
        accepted TCP sockets), so ChatServer can still send its BYE. The shared socket is
        released when the last session is gone, or at the latest after one full retry
        budget.
        """
        with self._lock:
            if self._stop_event.is_set():
                return
            self._stop_event.set()
            self._closed_at = time.monotonic()
        while True:  # transports nobody accepted would otherwise never be closed
            try:
                self._pending.get_nowait().close()
            except queue.Empty:
                break
        if self._sock is None:
            return
        log.debug("UDP listener on %s:%d closing", *self.bound_address)

    @property
    def bound_address(self) -> Address:
        """Actual (host, port) after start(). Raises TransportError before start()."""
        if self._bound_address is None:
            raise TransportError("The listener has not been started.")
        return self._bound_address

    # ------------------------------------------------------------------ #
    def _demux_loop(self, sock: socket.socket) -> None:
        """Read every datagram and hand it to the transport of its source address."""
        try:
            while not self._should_stop_demux():
                try:
                    data, source = sock.recvfrom(_max_datagram_size())
                except TimeoutError:
                    continue
                except ConnectionResetError:  # Windows: ICMP from an earlier sendto()
                    continue
                except OSError as exc:
                    log.debug("UDP listener socket closed: %s", exc)
                    break
                self._route(data, (source[0], source[1]))
        except Exception as exc:  # noqa: BLE001 - a network thread must never die silently
            log.exception("Unexpected error in the UDP demultiplexer")
            self._publish_error(exc)
        finally:
            self._shutdown_sessions()
            sock.close()

    def _route(self, data: bytes, source: Address) -> None:
        with self._lock:
            transport = self._sessions.get(source)
            if transport is None and self._stop_event.is_set():
                return
        if transport is None:
            if not self._is_new_session(data):
                return  # unknown sender that is not starting a session: drop
            with self._lock:
                transport = self._sessions.get(source)
                if transport is None:
                    if self._stop_event.is_set():
                        return
                    transport = ReliableUdpTransport(
                        self._sock_or_fail(), source, self.event_bus,
                        has_own_socket=False, on_released=self._forget,
                    )
                    self._sessions[source] = transport
                    self._pending.put(transport)
                    log.debug("New reliable UDP session from %s:%d", *source)
        transport._handle_datagram(data)

    @staticmethod
    def _is_new_session(data: bytes) -> bool:
        """Only an intact HELLO with seq 1 may open a session."""
        try:
            packet = Packet.decode(data)
        except ProtocolError:
            return False
        return packet.type is MessageType.HELLO and packet.seq == 1

    def _publish_error(self, exc: Exception) -> None:
        if self.event_bus is not None:
            self.event_bus.publish(Event(EventType.ERROR, {
                "code": ErrorCode.INTERNAL_ERROR.value,
                "message": f"Reliable UDP listener internal error: {exc}",
            }, source="transport"))

    def _forget(self, transport: ReliableUdpTransport) -> None:
        with self._lock:
            if self._sessions.get(transport.peer_address) is transport:
                del self._sessions[transport.peer_address]

    def _should_stop_demux(self) -> bool:
        if not self._stop_event.is_set():
            return False
        with self._lock:
            has_sessions = bool(self._sessions)
        has_lingered = self._closed_at is not None and (
            time.monotonic() - self._closed_at >= _listener_linger_seconds()
        )
        return not has_sessions or has_lingered

    def _shutdown_sessions(self) -> None:
        """Socket is going away: sessions that are still around cannot work any more."""
        with self._lock:
            sessions = list(self._sessions.values())
        for transport in sessions:
            transport._fail("The server socket was closed.")

    def _sock_or_fail(self) -> socket.socket:
        if self._sock is None:
            raise TransportError("The listener has not been started.")
        return self._sock
