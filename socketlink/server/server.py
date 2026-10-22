"""Multi-client chat server (thread-per-client).

OWNER: Yusuf
USES: common/transport.py (create_listener), common/protocol.py (make_*),
common/events.py (EventBus), common/config.py (ServerConfig)
USED BY: gui/server_gui.py (Tina)

Thread model:
accept thread -> waits in listener.accept(timeout=SOCKET_TIMEOUT), loops until stop
one ClientHandler/client -> loops on transport.receive(), handles packets
heartbeat watchdog -> every second: disconnect clients silent > CONNECTION_TIMEOUT
All threads: daemon=True, name="srv-accept" / "srv-client-<username>" / "srv-watchdog",
and they all stop when `self._stop_event` is set.

Shared state: `self._clients` (lower-cased username -> ClientHandler), `self._handlers`
(every open connection, registered or not) and `self._transfers` (running file transfers)
are ONLY touched while holding `self._clients_lock`. Never send on a socket while holding the lock
(copy the list first, release, then send).
"""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from socketlink.common.config import ServerConfig
from socketlink.common.constants import (
    CONNECT_TIMEOUT,
    CONNECTION_TIMEOUT,
    MAX_CHAT_LENGTH,
    MAX_CONSECUTIVE_MALFORMED,
    MAX_FILE_SIZE,
    MAX_SIMULATED_DELAY_MS,
    MAX_SIMULATED_LOSS,
    SOCKET_TIMEOUT,
    STATS_UPDATE_INTERVAL,
    USERNAME_PATTERN,
    ByeReason,
    DisconnectReason,
    ErrorCode,
    MessageType,
)
from socketlink.common.events import Event, EventBus, EventType
from socketlink.common.exceptions import (
    ConnectionClosedError,
    MalformedPacketError,
    PayloadTooLargeError,
    ProtocolError,
    TransportError,
    TransportTimeoutError,
    ValidationError,
    VersionMismatchError,
)
from socketlink.common.logger import get_logger
from socketlink.common.protocol import (
    Packet,
    make_bye,
    make_chat,
    make_error,
    make_file_start,
    make_pong,
    make_user_list,
    make_welcome,
    parse_file_chunk,
    transfer_id_client,
)
from socketlink.common.stats import TransportStats
from socketlink.common.transport import Address, Transport, TransportListener, create_listener

log = get_logger(__name__)

_USERNAME_RE = re.compile(USERNAME_PATTERN)

# client_id travels in the upper 16 bits of every transfer_id (PROTOCOL.md 4.1), so ids are
# 1..65535 and start again at 1 after that.
_MAX_CLIENT_ID = 0xFFFF


def _require_int(payload: dict[str, Any], key: str) -> int:
    """`payload[key]` as a whole number, or MalformedPacketError (booleans do not count)."""
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise MalformedPacketError(f"The packet needs a whole number '{key}'.")
    return value


class RegistrationError(ValidationError):
    """HELLO was refused. `code` is the ErrorCode to send back to the client."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def _error_code_for(exc: Exception) -> ErrorCode:
    """Map a packet-level exception to the ERROR code of PROTOCOL.md section 7."""
    if isinstance(exc, VersionMismatchError):
        return ErrorCode.VERSION_MISMATCH
    if isinstance(exc, PayloadTooLargeError):
        return ErrorCode.PAYLOAD_TOO_LARGE
    return ErrorCode.MALFORMED_PACKET


@dataclass(frozen=True)
class ClientInfo:
    """Read-only view of a connected client for the dashboard."""

    username: str
    address: Address
    connected_at: float
    last_seen: float
    packets_sent: int
    packets_received: int


class ClientHandler(threading.Thread):
    """Serves ONE connected client. First packet must be HELLO (else ERROR NOT_AUTHENTICATED)."""

    def __init__(self, server: ChatServer, transport: Transport) -> None:
        host, port = transport.peer_address
        super().__init__(name=f"srv-client-{host}:{port}", daemon=True)
        self.server = server
        self.transport = transport
        self.username: str | None = None
        self.client_id = 0  # assigned by register(); the upper 16 bits of its transfer ids
        self.connected_at = time.time()
        self.last_seen = self.connected_at
        self._close_lock = threading.Lock()
        self._is_closed = False  # disconnect() ran: no more routing, no more receiving
        self._transport_closed = False  # the socket itself was closed (after the BYE drain)
        self._bye_sent = False
        self._disconnect_done = threading.Event()  # BYE attempted and client unregistered
        # Held by register() from before the client becomes visible until its WELCOME is sent,
        # and by every send(). Other threads can already route to a registered client, but
        # their packets wait here, so WELCOME is always its first packet (PROTOCOL.md 5.1).
        self.send_lock = threading.RLock()
        # True once the client is registered, i.e. broadcasts and private messages reach it.
        self.ready = False

    # ---- thread body -----------------------------------------------------
    def run(self) -> None:
        """Receive loop. No exception escapes this thread (PROTOCOL.md 7 and 7.1)."""
        reason = DisconnectReason.CONNECTION_LOST
        try:
            self._receive_loop()
        except ConnectionClosedError as exc:
            log.info("%s is gone: %s", self._label, exc)
        except (MalformedPacketError, VersionMismatchError, PayloadTooLargeError) as exc:
            # Raised by transport.receive(): the byte stream can no longer be trusted.
            log.warning("%s sent an unusable packet: %s", self._label, exc)
            self._send_error(_error_code_for(exc), str(exc))
        except Exception as exc:  # no exception may escape a network thread
            log.exception("Unexpected error while serving %s", self._label)
            self.server.report_error(ErrorCode.INTERNAL_ERROR, f"{self._label}: {exc}")
            self._send_error(ErrorCode.INTERNAL_ERROR, "Internal server error.")
            reason = DisconnectReason.INTERNAL_ERROR
        finally:
            self.disconnect(reason)
            self._finish_close()  # no-op if disconnect() already did it in this thread

    def _receive_loop(self) -> None:
        malformed_in_a_row = 0
        while not self._is_closed:
            try:
                packet = self.transport.receive(timeout=SOCKET_TIMEOUT)
            except TransportTimeoutError:
                continue  # PROTOCOL.md 7.1: silence is not an error
            self.last_seen = time.time()
            try:
                self.handle_packet(packet)
            except MalformedPacketError as exc:
                # Raised while reading the payload: the framing is fine, so keep the client,
                # unless it keeps doing this (PROTOCOL.md 7).
                malformed_in_a_row += 1
                log.warning("Bad %s payload from %s: %s", packet.type.name, self._label, exc)
                self._send_error(ErrorCode.MALFORMED_PACKET, str(exc))
                if malformed_in_a_row >= MAX_CONSECUTIVE_MALFORMED:
                    log.warning("Closing %s: %d malformed packets in a row", self._label,
                                malformed_in_a_row)
                    self.disconnect(DisconnectReason.REJECTED)
                    return
            else:
                malformed_in_a_row = 0

    # ---- public API used by ChatServer -----------------------------------
    def send(self, packet: Packet) -> None:
        """Thread-safe send to this client; on failure, disconnect this client.

        Nothing is sent once disconnect() has started: the BYE must be the last packet."""
        if self._is_closed:
            return
        try:
            with self.send_lock:
                self.transport.send(packet)
        except TransportError as exc:
            # Includes ConnectionClosedError and, on reliable UDP, MAX_RETRIES exceeded.
            log.info("Sending %s to %s failed: %s", packet.type.name, self._label, exc)
            self.disconnect(DisconnectReason.CONNECTION_LOST)

    def disconnect(self, reason: DisconnectReason, bye: ByeReason | None = None) -> None:
        """Close this client exactly once; safe from any thread, any number of times.

        If `bye` is given it is sent first. `reason` ends up in the CLIENT_LEFT event,
        but only when the client had completed HELLO.

        The client stops being routed to immediately. The socket is closed by the handler
        thread (see `_finish_close`), after it has drained what the client still sends: closing
        a socket that holds unread data makes the OS send RST instead of FIN, and the client
        could lose our BYE.
        """
        with self._close_lock:
            if self._is_closed:
                return
            self._is_closed = True
        if bye is not None:
            try:
                self.transport.send(make_bye(bye))
                self._bye_sent = True
            except TransportError as exc:
                log.debug("BYE to %s was not delivered: %s", self._label, exc)
        self.server.unregister(self, reason.value)
        self._disconnect_done.set()
        if threading.current_thread() is self or not self.is_alive():
            self._finish_close()
        # Otherwise the handler thread notices _is_closed within SOCKET_TIMEOUT and finishes.

    def _finish_close(self) -> None:
        """Close the transport once, after draining incoming packets if a BYE was sent."""
        # Another thread may still be inside disconnect() sending the BYE: never close under it.
        self._disconnect_done.wait(timeout=CONNECT_TIMEOUT)
        with self._close_lock:
            if self._transport_closed:
                return
            self._transport_closed = True
        if self._bye_sent:
            self._drain_after_bye()
        self.transport.close()

    def _drain_after_bye(self) -> None:
        """Read and discard packets until the client closes, for at most SOCKET_TIMEOUT."""
        deadline = time.monotonic() + SOCKET_TIMEOUT
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                self.transport.receive(timeout=remaining)
            except TransportTimeoutError:
                return
            except (TransportError, ProtocolError):
                return  # closed by the client, or garbage: either way we are done

    def info(self) -> ClientInfo:
        """Snapshot for the dashboard (ChatServer.get_clients)."""
        stats = self.transport.stats.snapshot()
        return ClientInfo(
            username=self.username or "",
            address=self.transport.peer_address,
            connected_at=self.connected_at,
            last_seen=self.last_seen,
            packets_sent=int(stats["packets_sent"]),
            packets_received=int(stats["packets_received"]),
        )

    # ---- packet handling -------------------------------------------------
    def handle_packet(self, packet: Packet) -> None:
        """Dispatch on packet.type: HELLO, CHAT, PING, FILE_*, BYE (see PROTOCOL.md 5)."""
        kind = packet.type
        if self.username is None:
            if kind is MessageType.HELLO:
                self._handle_hello(packet)
            else:
                self._reject(ErrorCode.NOT_AUTHENTICATED, "The first packet must be HELLO.")
        elif kind is MessageType.CHAT:
            self._handle_chat(packet)
        elif kind is MessageType.PING:
            self.send(make_pong())
        elif kind is MessageType.BYE:
            self._handle_bye(packet)
        elif kind in (MessageType.FILE_START, MessageType.FILE_CHUNK, MessageType.FILE_END):
            self._handle_file_packet(packet)
        else:
            log.debug("Ignoring %s from %s", kind.name, self._label)

    def _handle_hello(self, packet: Packet) -> None:
        username = packet.json_payload().get("username")
        if not isinstance(username, str):
            raise MalformedPacketError("HELLO needs a text field 'username'.")
        try:
            self.server.register(self, username)
        except RegistrationError as exc:
            log.info("Rejected %s: %s", self._label, exc)
            self._reject(exc.code, str(exc))

    def _handle_chat(self, packet: Packet) -> None:
        payload = packet.json_payload()
        text, to = payload.get("text"), payload.get("to")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_CHAT_LENGTH:
            raise MalformedPacketError(f"CHAT text must be 1 to {MAX_CHAT_LENGTH} characters.")
        if to is not None and not isinstance(to, str):
            raise MalformedPacketError("CHAT field 'to' must be a username or null.")
        relay = make_chat(text, to=to, sender=self.username, timestamp=time.time())
        if to is None:
            self.server.broadcast(relay)  # everyone, the sender included (PROTOCOL.md 5.2)
        elif not self.server.send_to(to, relay):
            self._send_error(ErrorCode.UNKNOWN_USER, f"User '{to}' is not connected.")
        elif to.lower() != (self.username or "").lower():
            self.send(relay)  # the sender sees its own private message too

    def _handle_bye(self, packet: Packet) -> None:
        try:
            reason = packet.json_payload().get("reason", ByeReason.CLIENT_QUIT.value)
        except MalformedPacketError:
            reason = ByeReason.CLIENT_QUIT.value  # it said goodbye, the details do not matter
        self.disconnect(DisconnectReason.from_bye(reason))

    def _handle_file_packet(self, packet: Packet) -> None:
        """Relay FILE_START, FILE_CHUNK and FILE_END to the recipient (PROTOCOL.md 5.4)."""
        kind = packet.type
        if kind is MessageType.FILE_START:
            self._relay_file_start(packet)
            return
        if kind is MessageType.FILE_CHUNK:
            transfer_id = parse_file_chunk(packet)[0]
        else:
            transfer_id = _require_int(packet.json_payload(), "transfer_id")
        if transfer_id_client(transfer_id) != self.client_id:
            self._send_error(ErrorCode.FILE_REJECTED, "That transfer_id does not belong to you.")
            return
        recipient = self.server.transfer_recipient(
            self, transfer_id, finished=kind is MessageType.FILE_END
        )
        if recipient is None:
            log.debug("Dropping %s of unknown transfer %d from %s", kind.name, transfer_id,
                      self._label)
            return
        recipient.send(packet)

    def _relay_file_start(self, packet: Packet) -> None:
        payload = packet.json_payload()
        transfer_id = _require_int(payload, "transfer_id")
        size = _require_int(payload, "size")
        total_chunks = _require_int(payload, "total_chunks")
        checksum = _require_int(payload, "checksum")
        filename, to = payload.get("filename"), payload.get("to")
        if not isinstance(filename, str) or not filename:
            raise MalformedPacketError("FILE_START needs a text field 'filename'.")
        if transfer_id_client(transfer_id) != self.client_id:
            self._send_error(ErrorCode.FILE_REJECTED, "That transfer_id does not belong to you.")
        elif not isinstance(to, str) or not to:
            self._send_error(ErrorCode.FILE_REJECTED, "A file needs a recipient ('to').")
        elif size > MAX_FILE_SIZE:
            self._send_error(ErrorCode.FILE_REJECTED, f"The file is larger than {MAX_FILE_SIZE} B.")
        else:
            result = self.server.open_transfer(self, transfer_id, to)
            if result is ErrorCode.UNKNOWN_USER:
                self._send_error(ErrorCode.UNKNOWN_USER, f"User '{to}' is not connected.")
            elif isinstance(result, ErrorCode):
                self._send_error(result, "That transfer_id is already in use.")
            else:
                result.send(
                    make_file_start(
                        transfer_id, filename, size, total_chunks, checksum,
                        to=to, sender=self.username,
                    )
                )

    # ---- helpers ---------------------------------------------------------
    @property
    def _label(self) -> str:
        """Who this is, for log lines: the username, or host:port before HELLO."""
        if self.username is not None:
            return self.username
        host, port = self.transport.peer_address
        return f"{host}:{port}"

    def _send_error(self, code: ErrorCode, message: str) -> None:
        """Best-effort ERROR packet. Never disconnects, so it is safe inside error handling."""
        try:
            self.transport.send(make_error(code.value, message))
        except TransportError as exc:
            log.debug("ERROR %s to %s was not delivered: %s", code.value, self._label, exc)

    def _reject(self, code: ErrorCode, message: str) -> None:
        """Tell the client why, then close (HELLO refused / not authenticated)."""
        self._send_error(code, message)
        self.disconnect(DisconnectReason.REJECTED)


class ChatServer:
    """Public API used by the server GUI. All methods are non-blocking."""

    def __init__(self, event_bus: EventBus, config: ServerConfig | None = None) -> None:
        self.event_bus = event_bus
        self.config = config or ServerConfig()
        self._clients: dict[str, ClientHandler] = {}
        self._handlers: set[ClientHandler] = set()
        self._clients_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._listener: TransportListener | None = None
        self._accept_thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._next_client_id = 1
        # transfer_id -> (sender, recipient) of every FILE_START that was accepted and has not
        # ended yet. The server stores no file data, only this routing table.
        self._transfers: dict[int, tuple[ClientHandler, ClientHandler]] = {}
        # Simulated network (reliable UDP only), applied to every transport, old and new.
        self._loss_rate = self.config.loss_rate
        self._delay_ms = self.config.delay_ms
        # Counters of clients that already left, so the dashboard totals never go down.
        self._closed_totals = TransportStats().snapshot()

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        """Bind using self.config, start the accept + watchdog threads,
        publish SERVER_STARTED. Raises OSError if the port is busy."""
        if self.is_running:
            log.warning("start() ignored: the server is already running")
            return
        listener = create_listener(self.config.mode, self.event_bus)
        listener.start(self.config.host, self.config.port)  # OSError / NotImplementedError
        host, port = listener.bound_address  # the real port, also when config.port is 0
        self._stop_event.clear()
        with self._clients_lock:
            self._closed_totals = TransportStats().snapshot()  # a fresh run starts at zero
        self._listener = listener
        self._accept_thread = threading.Thread(
            target=self._accept_loop, args=(listener,), name="srv-accept", daemon=True
        )
        self._accept_thread.start()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, name="srv-watchdog", daemon=True
        )
        self._watchdog_thread.start()
        log.info("Server listening on %s:%d (%s)", host, port, self.config.mode.value)
        self._publish(
            EventType.SERVER_STARTED, {"host": host, "port": port, "mode": self.config.mode.value}
        )

    def stop(self) -> None:
        """Send BYE to everyone, close all transports, join threads, publish SERVER_STOPPED."""
        self._stop_event.set()  # from now on nobody can be accepted or registered
        with self._clients_lock:
            listener, self._listener = self._listener, None
            accept_thread, self._accept_thread = self._accept_thread, None
            watchdog_thread, self._watchdog_thread = self._watchdog_thread, None
            handlers = list(self._handlers)
        if listener is None:
            return  # never started, or already stopped
        for handler in handlers:  # BYE first, the listener is closed afterwards
            handler.disconnect(DisconnectReason.SERVER_SHUTDOWN, bye=ByeReason.SERVER_SHUTDOWN)
        listener.close()
        # Every thread notices within SOCKET_TIMEOUT; CONNECT_TIMEOUT is a generous cap so a
        # stuck thread can never freeze the dashboard.
        if accept_thread is not None:
            accept_thread.join(timeout=CONNECT_TIMEOUT)
        if watchdog_thread is not None:
            watchdog_thread.join(timeout=CONNECT_TIMEOUT)
        for handler in handlers:
            handler.join(timeout=CONNECT_TIMEOUT)
        log.info("Server stopped")
        self._publish(EventType.SERVER_STOPPED, {"reason": DisconnectReason.USER.value})

    @property
    def is_running(self) -> bool:
        return self._listener is not None and not self._stop_event.is_set()

    def _accept_loop(self, listener: TransportListener) -> None:
        """srv-accept: give every new connection its own ClientHandler thread."""
        while not self._stop_event.is_set():
            try:
                transport = listener.accept(timeout=SOCKET_TIMEOUT)
            except TransportTimeoutError:
                continue
            except ConnectionClosedError:
                if not self._stop_event.is_set():
                    self.report_error(ErrorCode.INTERNAL_ERROR, "The listener closed unexpectedly.")
                return
            except Exception as exc:  # no exception may escape a network thread
                log.exception("Accepting a connection failed")
                self.report_error(ErrorCode.INTERNAL_ERROR, f"accept failed: {exc}")
                self._stop_event.wait(SOCKET_TIMEOUT)  # do not spin if it keeps failing
                continue
            self._start_handler(transport)

    def _start_handler(self, transport: Transport) -> None:
        handler = ClientHandler(self, transport)
        with self._clients_lock:
            if self._stop_event.is_set():  # stop() already took its snapshot of the handlers
                transport.close()
                return
            # Configured and registered under ONE lock hold: a concurrent
            # set_network_conditions() either ran before (we read its values) or runs after
            # (it finds this handler in _handlers), so the new transport can never miss it.
            self._configure_transport(transport)
            self._handlers.add(handler)
        log.info("Connection from %s:%d", *transport.peer_address)
        handler.start()

    # ---- routing (called by ClientHandler) --------------------------------
    def register(self, handler: ClientHandler, username: str) -> None:
        """Validate username, add to _clients, publish CLIENT_JOINED, send WELCOME,
        broadcast USER_LIST. Raise RegistrationError (a ValidationError) for invalid or
        duplicate names or a full server; it carries the ErrorCode for the client."""
        if _USERNAME_RE.fullmatch(username) is None:
            raise RegistrationError(
                ErrorCode.INVALID_USERNAME,
                f"Username must match {USERNAME_PATTERN} (3-16 letters, digits or _).",
            )
        key = username.lower()
        # send_lock first: once the client is in _clients other threads may route to it, and
        # their packets must not overtake the WELCOME. Lock order: send_lock, then _clients_lock.
        with handler.send_lock:
            with self._clients_lock:
                if self._stop_event.is_set():
                    raise ConnectionClosedError("The server is stopping.")
                if len(self._clients) >= self.config.max_clients:
                    raise RegistrationError(ErrorCode.SERVER_FULL, "The server is full.")
                if key in self._clients:
                    raise RegistrationError(
                        ErrorCode.USERNAME_TAKEN, f"Username '{username}' is already in use."
                    )
                handler.username = username
                self._clients[key] = handler
                handler.ready = True  # private messages and broadcasts reach it from now on
                client_id = self._next_client_id
                self._next_client_id = client_id % _MAX_CLIENT_ID + 1
                handler.client_id = client_id
                users = self._user_names_locked()
            handler.name = f"srv-client-{username}"
            log.info("%s joined (client_id=%d)", username, client_id)
            # CLIENT_JOINED goes first so that a client that vanishes right away still produces
            # a matching CLIENT_LEFT afterwards.
            self._publish(
                EventType.CLIENT_JOINED,
                {"username": username, "address": handler.transport.peer_address},
            )
            handler.send(make_welcome(client_id, self.config.server_name, users))
        self._broadcast_user_list()

    def unregister(self, handler: ClientHandler, reason: str) -> None:
        """Remove `handler`. `reason` must be a DisconnectReason value. Idempotent: the
        CLIENT_LEFT event and the USER_LIST update happen only the first time."""
        with self._clients_lock:
            if handler in self._handlers:
                self._handlers.discard(handler)
                self._add_to_closed_totals(handler.transport.stats.snapshot())
            for transfer_id in [
                tid for tid, ends in self._transfers.items() if handler in ends
            ]:
                del self._transfers[transfer_id]  # the sender or the recipient is gone
            key = handler.username.lower() if handler.username is not None else None
            was_registered = key is not None and self._clients.get(key) is handler
            if was_registered and key is not None:
                del self._clients[key]
        if not was_registered:
            return  # never completed HELLO, or already removed
        log.info("%s left (%s)", handler.username, reason)
        self._publish(EventType.CLIENT_LEFT, {"username": handler.username, "reason": reason})
        if not self._stop_event.is_set():
            self._broadcast_user_list()

    def broadcast(self, packet: Packet, exclude: str | None = None) -> None:
        with self._clients_lock:
            skip = exclude.lower() if exclude is not None else None
            targets = [h for key, h in self._clients.items() if key != skip and h.ready]
        for handler in targets:  # lock released: a slow client must not block the others
            handler.send(packet)

    def send_to(self, username: str, packet: Packet) -> bool:
        """Return False if the user is not connected."""
        with self._clients_lock:
            handler = self._clients.get(username.lower())
        if handler is None or not handler.ready:
            return False
        handler.send(packet)
        return True

    # ---- file relay (called by ClientHandler) ------------------------------
    def open_transfer(
        self, sender: ClientHandler, transfer_id: int, to: str
    ) -> ClientHandler | ErrorCode:
        """Record `transfer_id` as running from `sender` to the user `to`.

        Return the recipient, UNKNOWN_USER if `to` is not connected, or FILE_REJECTED if the
        id is already in use."""
        with self._clients_lock:
            recipient = self._clients.get(to.lower())
            if recipient is None or not recipient.ready:
                return ErrorCode.UNKNOWN_USER
            if transfer_id in self._transfers:
                return ErrorCode.FILE_REJECTED
            self._transfers[transfer_id] = (sender, recipient)
            return recipient

    def transfer_recipient(
        self, sender: ClientHandler, transfer_id: int, finished: bool = False
    ) -> ClientHandler | None:
        """The recipient of `sender`'s running transfer, or None if there is no such transfer.
        With `finished` the transfer is forgotten (FILE_END)."""
        with self._clients_lock:
            ends = self._transfers.get(transfer_id)
            if ends is None or ends[0] is not sender:
                return None
            if finished:
                del self._transfers[transfer_id]
            return ends[1]

    # ---- dashboard helpers -------------------------------------------------
    def get_clients(self) -> list[ClientInfo]:
        with self._clients_lock:
            handlers = list(self._clients.values())
        return [handler.info() for handler in handlers]

    def kick(self, username: str, reason: str = "kicked_by_admin") -> None:
        """Send BYE(reason) to `username` and remove it. Unknown users are ignored.

        The work runs in a short-lived thread so a stalled client can never freeze the
        dashboard thread that called this.
        """
        with self._clients_lock:
            handler = self._clients.get(username.lower())
        if handler is None:
            log.info("kick(%s) ignored: not connected", username)
            return
        try:
            bye = ByeReason(reason)
        except ValueError:
            bye = ByeReason.KICKED_BY_ADMIN
        log.info("Kicking %s (%s)", handler.username, bye.value)
        threading.Thread(
            target=handler.disconnect,
            args=(DisconnectReason.from_bye(bye.value),),
            kwargs={"bye": bye},
            name=f"srv-kick-{username}",
            daemon=True,
        ).start()

    def get_stats(self) -> dict[str, int | float]:
        """Sum of all client transports' stats.snapshot(), including clients that left.

        `avg_rtt_ms` is the mean over the connected clients that have a measurement.
        """
        with self._clients_lock:
            handlers = list(self._handlers)
            totals = dict(self._closed_totals)
        rtts: list[float] = []
        for handler in handlers:
            for name, value in handler.transport.stats.snapshot().items():
                if name == "avg_rtt_ms":
                    if value:
                        rtts.append(float(value))
                else:
                    totals[name] = totals[name] + value
        totals["avg_rtt_ms"] = sum(rtts) / len(rtts) if rtts else 0.0
        return totals

    def set_network_conditions(self, loss_rate: float, delay_ms: int) -> None:
        """Forward to every transport (UDP only; TCP ignores it). Clients that connect
        later get the same values. Raises ValidationError outside the GUI slider limits."""
        if not 0.0 <= loss_rate <= MAX_SIMULATED_LOSS:
            raise ValidationError(f"loss_rate must be between 0 and {MAX_SIMULATED_LOSS}.")
        if not 0 <= delay_ms <= MAX_SIMULATED_DELAY_MS:
            raise ValidationError(f"delay_ms must be between 0 and {MAX_SIMULATED_DELAY_MS}.")
        with self._clients_lock:
            # Applied under the lock (plain setters, no I/O) so two quick calls can never
            # leave the transports with different values.
            self._loss_rate, self._delay_ms = loss_rate, delay_ms
            for handler in self._handlers:
                handler.transport.set_network_conditions(loss_rate, delay_ms)
        log.info("Network conditions: loss %.0f %%, delay %d ms", loss_rate * 100, delay_ms)

    # ---- internals ---------------------------------------------------------
    def _configure_transport(self, transport: Transport) -> None:
        """Give a new connection the current simulated network and the configured window.

        The caller holds `_clients_lock`."""
        try:
            transport.set_network_conditions(self._loss_rate, self._delay_ms)
            transport.set_window_size(self.config.window_size)  # TCP ignores it
        except ValidationError as exc:  # a bad config value must not kill the accept thread
            log.warning("Transport settings were not applied: %s", exc)

    def _add_to_closed_totals(self, snapshot: dict[str, int | float]) -> None:
        """Caller holds the lock. The average RTT only makes sense for live clients."""
        for name, value in snapshot.items():
            if name != "avg_rtt_ms":
                self._closed_totals[name] = self._closed_totals[name] + value

    def _watchdog_loop(self) -> None:
        """srv-watchdog: every STATS_UPDATE_INTERVAL drop silent clients, publish stats."""
        while not self._stop_event.wait(STATS_UPDATE_INTERVAL):
            try:
                self._expire_silent_clients()
                self._publish(EventType.STATS_UPDATED, {"stats": self.get_stats()})
            except Exception as exc:  # no exception may escape a network thread
                log.exception("Watchdog failed")
                self.report_error(ErrorCode.INTERNAL_ERROR, f"watchdog failed: {exc}")

    def _expire_silent_clients(self) -> None:
        """Disconnect every connection (HELLO or not) silent for CONNECTION_TIMEOUT."""
        now = time.time()
        with self._clients_lock:
            silent = [h for h in self._handlers if now - h.last_seen > CONNECTION_TIMEOUT]
        for handler in silent:  # lock released: sending the BYE may be slow
            log.info("%s was silent for more than %.0f s",
                     handler.username or handler.transport.peer_address, CONNECTION_TIMEOUT)
            handler.disconnect(DisconnectReason.TIMEOUT, bye=ByeReason.TIMEOUT)

    def report_error(self, code: ErrorCode, message: str) -> None:
        """Publish an ERROR event (shown in the dashboard log)."""
        self._publish(EventType.ERROR, {"code": code.value, "message": message})

    def _publish(self, event_type: EventType, data: dict[str, Any]) -> None:
        self.event_bus.publish(Event(event_type, data, source="server"))

    def _user_names_locked(self) -> list[str]:
        """Alphabetical display names of the registered clients. Caller holds the lock."""
        names = [h.username for h in self._clients.values() if h.username is not None]
        return sorted(names, key=str.lower)

    def _broadcast_user_list(self) -> None:
        """Send the current USER_LIST to everyone (a fresh snapshot, taken just now)."""
        with self._clients_lock:
            users = self._user_names_locked()
            targets = [h for h in self._clients.values() if h.ready]
        packet = make_user_list(users)
        for handler in targets:
            handler.send(packet)
