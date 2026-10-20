"""Chat client core (no GUI code here).

OWNER: Hamit
USES:  common/transport.py (create_transport), common/protocol.py (make_*),
       common/events.py, common/config.py (ClientConfig),
       transfer/file_transfer.py (FileSender / FileReceiver, owner: Tina)
USED BY: gui/client_gui.py (İlayda)

Thread model:
    connect() starts "cli-connect" thread (so the GUI never freezes)
    after WELCOME:  "cli-receiver"  loops on transport.receive()
                    "cli-heartbeat" sends PING every HEARTBEAT_INTERVAL
All threads daemon=True and stop on self._stop_event.

State machine (State pattern): use `_set_state()` for EVERY change; it checks
STATE_TRANSITIONS (constants.py) and publishes STATE_CHANGED.

Ownership of state changes:
    - connect() / disconnect() run on the caller's (GUI) thread.
    - Leaving CONNECTING is done by "cli-connect"; leaving RECONNECTING is done by
      "cli-receiver". disconnect() in those states only sets the stop event and closes
      the transport; the background thread then finishes with DISCONNECTED.
    - Every connection attempt gets a fresh `_stop_event`, so threads of an old
      session can never keep running in a new one.

Error events: an ERROR packet from the server is published with the server's `code`
(ErrorCode). Failures the client detects itself use ClientErrorCode (CONNECTION_REFUSED,
CONNECT_TIMEOUT, CONNECTION_LOST, PROTOCOL_ERROR, INVALID_STATE).
DISCONNECTED events always carry a DisconnectReason value (docs/ARCHITECTURE.md).
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any

from socketlink.common.config import ClientConfig
from socketlink.common.constants import (
    CONNECT_TIMEOUT,
    CONNECTION_TIMEOUT,
    HEARTBEAT_INTERVAL,
    MAX_CHAT_LENGTH,
    MAX_SIMULATED_DELAY_MS,
    MAX_SIMULATED_LOSS,
    RECONNECT_DELAYS,
    SOCKET_TIMEOUT,
    STATE_TRANSITIONS,
    STATS_UPDATE_INTERVAL,
    USERNAME_PATTERN,
    ByeReason,
    ClientErrorCode,
    ConnectionState,
    DisconnectReason,
    ErrorCode,
    MessageType,
)
from socketlink.common.events import Event, EventBus, EventType
from socketlink.common.exceptions import (
    ConnectionClosedError,
    InvalidStateError,
    MalformedPacketError,
    ProtocolError,
    SocketLinkError,
    TransportError,
    TransportTimeoutError,
    ValidationError,
)
from socketlink.common.logger import get_logger
from socketlink.common.protocol import Packet, make_bye, make_chat, make_hello, make_ping
from socketlink.common.stats import TransportStats
from socketlink.common.transport import Transport, create_transport

log = get_logger(__name__)


class _HandshakeError(SocketLinkError):
    """The server answered HELLO with an ERROR packet (e.g. USERNAME_TAKEN)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ChatClient:
    """Public API used by the client GUI. Every public method returns immediately;
    results arrive as events (CONNECTED, MESSAGE_RECEIVED, ERROR, ...)."""

    def __init__(self, event_bus: EventBus, config: ClientConfig | None = None) -> None:
        self.event_bus = event_bus
        self.config = config or ClientConfig()
        self._transport: Transport | None = None
        self._state = ConnectionState.DISCONNECTED
        self._state_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._client_id: int | None = None
        self._last_received = time.monotonic()
        # RTT measured with PING/PONG (perf_counter: fine resolution on every OS)
        self._rtt_lock = threading.Lock()
        self._ping_sent_at: float | None = None
        self._rtt_samples = 0
        self._avg_rtt_ms = 0.0

    # ---- state -----------------------------------------------------------
    @property
    def state(self) -> ConnectionState:
        return self._state

    def _set_state(self, new_state: ConnectionState) -> None:
        """Validate against STATE_TRANSITIONS, update, publish STATE_CHANGED.
        Raises InvalidStateError for an illegal transition."""
        with self._state_lock:
            old_state = self._state
            if new_state not in STATE_TRANSITIONS[old_state]:
                raise InvalidStateError(
                    f"Illegal state change {old_state.name} -> {new_state.name}."
                )
            self._state = new_state
        log.debug("State %s -> %s", old_state.name, new_state.name)
        self._publish(EventType.STATE_CHANGED, {"old": old_state, "new": new_state})

    # ---- public API --------------------------------------------------------
    def connect(self, config: ClientConfig | None = None) -> None:
        """Validate config, then in a background thread: create_transport -> send HELLO
        -> wait for WELCOME or ERROR -> publish CONNECTED or ERROR.

        Raises ValidationError for an invalid config and InvalidStateError when the
        client is not DISCONNECTED. Both are raised before anything touches the network.
        """
        new_config = config or self.config
        if self._state is not ConnectionState.DISCONNECTED:
            raise InvalidStateError(f"connect() is not allowed in state {self._state.name}.")
        self._validate_config(new_config)
        self.config = new_config
        self._set_state(ConnectionState.CONNECTING)
        self._stop_event = threading.Event()
        threading.Thread(target=self._connect_worker, name="cli-connect", daemon=True).start()

    def disconnect(self) -> None:
        """Send BYE, stop threads, close transport, publish DISCONNECTED(reason=USER).

        Idempotent: does nothing when already DISCONNECTED or DISCONNECTING.
        """
        state = self._state
        if state in (ConnectionState.DISCONNECTED, ConnectionState.DISCONNECTING):
            return
        self._stop_event.set()
        if state is ConnectionState.CONNECTED and self._finish_user_disconnect():
            return
        # CONNECTING / RECONNECTING: the owning thread notices the stop event and
        # finishes with DISCONNECTED. Closing the transport wakes it up sooner.
        self._close_transport()

    def send_chat(self, text: str, to: str | None = None) -> None:
        """to=None -> everyone. Raises InvalidStateError if not CONNECTED,
        ValidationError if text is empty or longer than MAX_CHAT_LENGTH."""
        if self._state is not ConnectionState.CONNECTED:
            raise InvalidStateError(f"send_chat() is not allowed in state {self._state.name}.")
        if not isinstance(text, str) or not text.strip():
            raise ValidationError("Message text must not be empty.")
        if len(text) > MAX_CHAT_LENGTH:
            raise ValidationError(
                f"Message is {len(text)} characters; the limit is {MAX_CHAT_LENGTH}."
            )
        if to is not None and not re.fullmatch(USERNAME_PATTERN, to):
            raise ValidationError(f"Invalid recipient username: {to!r}.")
        # Published BEFORE sending, so the GUI always sees MESSAGE_SENT before the
        # server's echo (MESSAGE_RECEIVED). A failed send is reported as an ERROR event.
        self._publish(
            EventType.MESSAGE_SENT, {"to": to, "text": text, "timestamp": time.time()}
        )
        self._send_packet(make_chat(text, to))

    def send_file(self, path: str, to: str | None = None) -> int:
        """Start a FileSender in a background thread. Returns transfer_id."""
        raise NotImplementedError("TODO(Hamit + Tina)")

    def get_stats(self) -> dict[str, int | float]:
        """Counters of the current transport plus the PING/PONG round-trip time.

        Counters restart from zero after a reconnect (new transport). Returns all-zero
        counters when there is no transport.
        """
        transport = self._transport
        stats = transport.stats.snapshot() if transport else TransportStats().snapshot()
        with self._rtt_lock:
            if self._rtt_samples:
                stats["avg_rtt_ms"] = self._avg_rtt_ms
        return stats

    def set_network_conditions(self, loss_rate: float, delay_ms: int) -> None:
        """Set simulated loss/delay (reliable UDP only; TCP ignores it).

        The values are kept in the config so they survive a reconnect.
        Raises ValidationError for values outside the GUI slider limits.
        """
        if not 0.0 <= loss_rate <= MAX_SIMULATED_LOSS:
            raise ValidationError(f"loss_rate must be between 0 and {MAX_SIMULATED_LOSS}.")
        if not 0 <= delay_ms <= MAX_SIMULATED_DELAY_MS:
            raise ValidationError(f"delay_ms must be between 0 and {MAX_SIMULATED_DELAY_MS}.")
        self.config.loss_rate = loss_rate
        self.config.delay_ms = delay_ms
        transport = self._transport
        if transport is not None:
            transport.set_network_conditions(loss_rate, delay_ms)

    # ---- internals ----------------------------------------------------------
    def _receive_loop(self) -> None:
        """Dispatch on packet.type. On ConnectionClosedError / TransportTimeoutError
        -> _handle_connection_lost()."""
        stop_event = self._stop_event
        try:
            while not stop_event.is_set():
                transport = self._transport
                if transport is None:
                    break
                lost_reason = self._receive_one(transport)
                if lost_reason is None or stop_event.is_set():
                    continue
                self._handle_connection_lost(lost_reason)
                if self._state is not ConnectionState.CONNECTED:
                    break
        except Exception as exc:  # last-resort guard: a network thread must never die silently
            log.exception("Receiver thread crashed")
            self._publish_error(exc)
            self._end_session(DisconnectReason.INTERNAL_ERROR)
            return
        # disconnect() may have read CONNECTING just before this session went CONNECTED;
        # then it only set the stop event, and finishing the disconnect is our job.
        if stop_event is self._stop_event and self._state is ConnectionState.CONNECTED:
            self._finish_user_disconnect()

    def _heartbeat_loop(self) -> None:
        """Every STATS_UPDATE_INTERVAL publish STATS_UPDATED; every HEARTBEAT_INTERVAL
        send PING. Silence is detected by the receiver (CONNECTION_TIMEOUT)."""
        stop_event = self._stop_event
        next_ping = time.monotonic() + HEARTBEAT_INTERVAL
        while not stop_event.wait(STATS_UPDATE_INTERVAL):
            if self._state is not ConnectionState.CONNECTED:
                continue
            self._publish(EventType.STATS_UPDATED, {"stats": self.get_stats()})
            if time.monotonic() < next_ping:
                continue
            next_ping = time.monotonic() + HEARTBEAT_INTERVAL
            with self._rtt_lock:
                self._ping_sent_at = time.perf_counter()
            self._send_packet(make_ping(), publish_failure=False)

    def _handle_connection_lost(self, reason: str) -> None:
        """If config.auto_reconnect: RECONNECTING and retry with RECONNECT_DELAYS,
        else DISCONNECTED. Always publish an event; never raise.

        `reason` is a DisconnectReason; it becomes the DISCONNECTED reason if every
        reconnect attempt fails.
        """
        stop_event = self._stop_event
        if stop_event.is_set():
            return
        log.warning("Connection lost: %s", DisconnectReason(reason).value)
        self._close_transport()
        if not self.config.auto_reconnect:
            self._end_session(reason)
            return
        try:
            self._set_state(ConnectionState.RECONNECTING)
        except InvalidStateError:
            return  # the user is disconnecting at the same moment
        last_error: Exception | None = None
        for attempt, delay in enumerate(RECONNECT_DELAYS, start=1):
            if stop_event.wait(delay):
                break
            log.info("Reconnect attempt %d/%d", attempt, len(RECONNECT_DELAYS))
            try:
                transport, welcome = self._open_session(stop_event)
            except (SocketLinkError, OSError) as exc:
                log.info("Reconnect attempt %d failed: %s", attempt, exc)
                last_error = exc
                continue
            self._transport = transport
            self._activate_session(welcome)
            if stop_event.is_set():
                self._finish_user_disconnect()
            return
        self._close_transport()
        self._set_state(ConnectionState.DISCONNECTED)
        if stop_event.is_set():
            reason = DisconnectReason.USER
        elif last_error is not None:
            self._publish_error(
                last_error,
                f"Could not reconnect after {len(RECONNECT_DELAYS)} attempts: {last_error}",
            )
        stop_event.set()
        self._publish(EventType.DISCONNECTED, {"reason": DisconnectReason(reason).value})

    # ---- connection helpers --------------------------------------------------
    def _connect_worker(self) -> None:
        """Body of "cli-connect": handshake, then start receiver + heartbeat threads."""
        stop_event = self._stop_event
        try:
            transport, welcome = self._open_session(stop_event)
        except (SocketLinkError, OSError) as exc:
            reason = self._failure_reason(exc, stop_event)  # before stop_event.set() below
            if reason is not DisconnectReason.USER:
                log.warning("Connect to %s:%d failed: %s",
                            self.config.host, self.config.port, exc)
                self._publish_error(exc)
            stop_event.set()
            self._set_state(ConnectionState.DISCONNECTED)
            self._publish(EventType.DISCONNECTED, {"reason": reason.value})
            return
        except Exception as exc:  # last-resort guard: a network thread must never die silently
            log.exception("Connect thread crashed")
            self._publish_error(exc)
            stop_event.set()
            self._set_state(ConnectionState.DISCONNECTED)
            self._publish(EventType.DISCONNECTED,
                          {"reason": DisconnectReason.INTERNAL_ERROR.value})
            return
        self._transport = transport
        self._activate_session(welcome)
        # Checked BEFORE the receiver starts: until then only disconnect() can set the
        # stop event, so a set event here really means "the user cancelled".
        if stop_event.is_set():
            self._finish_user_disconnect()
            return
        threading.Thread(target=self._receive_loop, name="cli-receiver", daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, name="cli-heartbeat", daemon=True).start()

    def _open_session(self, stop_event: threading.Event) -> tuple[Transport, dict[str, Any]]:
        """Connect, send HELLO and wait up to CONNECT_TIMEOUT for WELCOME.

        Returns (transport, WELCOME payload). Raises ConnectionRefusedError / OSError
        (no server), TransportTimeoutError (no answer), _HandshakeError (server sent
        ERROR), ProtocolError / TransportError (bad answer or lost connection).
        The transport is closed on every failure.
        """
        config = self.config
        transport = create_transport(config.mode, config.host, config.port, self.event_bus)
        try:
            transport.set_network_conditions(config.loss_rate, config.delay_ms)
            transport.send(make_hello(config.username))
            deadline = time.monotonic() + CONNECT_TIMEOUT
            while True:
                if stop_event.is_set():
                    raise ConnectionClosedError("Connection attempt cancelled by the user.")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TransportTimeoutError(
                        f"No WELCOME from the server within {CONNECT_TIMEOUT} s."
                    )
                try:
                    packet = transport.receive(timeout=min(SOCKET_TIMEOUT, remaining))
                except TransportTimeoutError:
                    continue
                if packet.type is MessageType.WELCOME:
                    welcome = packet.json_payload()
                    self._require_keys(welcome, ("client_id", "users"), packet)
                    return transport, welcome
                if packet.type is MessageType.ERROR:
                    error = packet.json_payload()
                    raise _HandshakeError(str(error.get("code", "")),
                                          str(error.get("message", "")))
                log.debug("Ignoring %s before WELCOME", packet.type.name)
        except (SocketLinkError, OSError):
            transport.close()
            raise

    def _activate_session(self, welcome: dict[str, Any]) -> None:
        """Called once a WELCOME arrived and self._transport is set: go CONNECTED."""
        self._client_id = int(welcome["client_id"])
        self._last_received = time.monotonic()
        self._set_state(ConnectionState.CONNECTED)
        config = self.config
        log.info("Connected to %s:%d as %s", config.host, config.port, config.username)
        self._publish(EventType.CONNECTED, {
            "host": config.host,
            "port": config.port,
            "mode": config.mode,
            "username": config.username,
            "client_id": self._client_id,
        })
        self._publish(EventType.USER_LIST_UPDATED, {"users": list(welcome["users"])})

    def _finish_user_disconnect(self) -> bool:
        """CONNECTED -> DISCONNECTING -> DISCONNECTED with BYE. Returns False when the
        state was not CONNECTED any more (another thread is already handling it)."""
        try:
            self._set_state(ConnectionState.DISCONNECTING)
        except InvalidStateError:
            return False
        self._stop_event.set()
        if self._send_packet(make_bye(), publish_failure=False):
            self._wait_for_server_close()
        self._close_transport()
        self._set_state(ConnectionState.DISCONNECTED)
        log.info("Disconnected by the user")
        self._publish(EventType.DISCONNECTED, {"reason": DisconnectReason.USER.value})
        return True

    def _end_session(self, reason: DisconnectReason) -> None:
        """Final disconnect without reconnecting (kicked, auto_reconnect off, crash)."""
        stop_event = self._stop_event
        stop_event.set()
        self._close_transport()
        if self._state is ConnectionState.CONNECTED:
            try:
                self._set_state(ConnectionState.DISCONNECTING)
            except InvalidStateError:
                return
        try:
            self._set_state(ConnectionState.DISCONNECTED)
        except InvalidStateError:
            return  # already DISCONNECTED (another thread finished first)
        self._publish(EventType.DISCONNECTED, {"reason": DisconnectReason(reason).value})

    def _wait_for_server_close(self) -> None:
        """After BYE, read and discard packets until the server closes (max SOCKET_TIMEOUT).

        Closing a socket that still has unread received data makes the OS send RST
        instead of FIN (always on Windows), and an RST can make the server lose the BYE
        we just sent. Draining first gives a clean close.
        """
        transport = self._transport
        if transport is None:
            return
        deadline = time.monotonic() + SOCKET_TIMEOUT
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                transport.receive(timeout=remaining)
            except (SocketLinkError, OSError):
                return  # closed by the server (expected), timeout, or broken stream

    def _close_transport(self) -> None:
        transport = self._transport
        if transport is not None:
            transport.close()  # idempotent

    # ---- receiving ------------------------------------------------------------
    def _receive_one(self, transport: Transport) -> DisconnectReason | None:
        """Receive and dispatch one packet. Returns a DisconnectReason when the
        connection must be treated as lost, otherwise None."""
        try:
            packet = transport.receive(timeout=SOCKET_TIMEOUT)
        except TransportTimeoutError:
            if time.monotonic() - self._last_received > CONNECTION_TIMEOUT:
                return DisconnectReason.TIMEOUT
            return None
        except ConnectionClosedError:
            return DisconnectReason.CONNECTION_LOST
        except ProtocolError as exc:
            # Malformed header / wrong version / oversized: the TCP stream can no
            # longer be trusted (PROTOCOL.md section 7), so drop this connection.
            log.warning("Protocol error from server: %s", exc)
            self._publish_error(exc)
            return DisconnectReason.CONNECTION_LOST
        except TransportError as exc:
            log.warning("Transport error: %s", exc)
            return DisconnectReason.CONNECTION_LOST
        self._last_received = time.monotonic()
        try:
            return self._dispatch(packet)
        except MalformedPacketError as exc:
            # Header and checksum were fine, only the JSON was wrong: the stream is
            # still aligned, so report and keep the connection.
            log.warning("Bad %s payload: %s", packet.type.name, exc)
            self._publish_error(exc)
            return None

    def _dispatch(self, packet: Packet) -> DisconnectReason | None:
        """Handle one valid packet. Returns a reason when the server ended the session."""
        message_type = packet.type
        if message_type is MessageType.CHAT:
            payload = packet.json_payload()
            self._require_keys(payload, ("text", "from", "timestamp"), packet)
            self._publish(EventType.MESSAGE_RECEIVED, {
                "from": payload["from"],
                "to": payload.get("to"),
                "text": payload["text"],
                "timestamp": payload["timestamp"],
            })
        elif message_type is MessageType.USER_LIST:
            payload = packet.json_payload()
            self._require_keys(payload, ("users",), packet)
            self._publish(EventType.USER_LIST_UPDATED, {"users": list(payload["users"])})
        elif message_type is MessageType.PONG:
            self._record_pong()
        elif message_type is MessageType.ERROR:
            payload = packet.json_payload()
            code = str(payload.get("code", ""))
            message = str(payload.get("message", ""))
            log.warning("Server error %s: %s", code, message)
            self._publish(EventType.ERROR, {"code": code, "message": message})
        elif message_type is MessageType.BYE:
            bye_reason = str(packet.json_payload().get("reason", ""))
            log.info("Server said BYE: %s", bye_reason)
            reason = DisconnectReason.from_bye(bye_reason)
            if bye_reason == ByeReason.KICKED_BY_ADMIN.value:
                self._end_session(reason)  # kicked: never reconnect
                return None
            return reason
        elif message_type in (MessageType.FILE_START, MessageType.FILE_CHUNK,
                              MessageType.FILE_END):
            self._handle_file_packet(packet)
        else:
            log.debug("Ignoring unexpected %s from server", message_type.name)
        return None

    def _handle_file_packet(self, packet: Packet) -> None:
        """Forward FILE_* packets to the FileReceiver (H5, waits for Tina's module)."""
        log.warning("File transfer is not available yet; ignoring %s", packet.type.name)

    def _record_pong(self) -> None:
        with self._rtt_lock:
            if self._ping_sent_at is None:
                return
            rtt_ms = (time.perf_counter() - self._ping_sent_at) * 1000.0
            self._ping_sent_at = None
            self._rtt_samples += 1
            self._avg_rtt_ms += (rtt_ms - self._avg_rtt_ms) / self._rtt_samples
        log.debug("RTT %.2f ms", rtt_ms)

    # ---- small helpers ----------------------------------------------------------
    def _send_packet(self, packet: Packet, publish_failure: bool = True) -> bool:
        """Send on the current transport. Returns False instead of raising; the
        receiver thread notices the broken connection and handles it."""
        transport = self._transport
        if transport is None:
            return False
        try:
            transport.send(packet)
        except (SocketLinkError, OSError) as exc:
            log.warning("Could not send %s: %s", packet.type.name, exc)
            if publish_failure:
                self._publish_error(exc)
            return False
        return True

    @staticmethod
    def _validate_config(config: ClientConfig) -> None:
        """Raise ValidationError for a bad config (rules live in ClientConfig.validate)."""
        try:
            config.validate()
        except NotImplementedError:
            # TODO(Hamit): remove once Nevin's ClientConfig.validate() is merged.
            if not re.fullmatch(USERNAME_PATTERN, config.username or ""):
                raise ValidationError(f"Invalid username: {config.username!r}.") from None

    @staticmethod
    def _require_keys(payload: dict[str, Any], keys: tuple[str, ...], packet: Packet) -> None:
        missing = [key for key in keys if key not in payload]
        if missing:
            raise MalformedPacketError(f"{packet.type.name} payload is missing {missing}.")

    @staticmethod
    def _failure_reason(exc: BaseException, stop_event: threading.Event) -> DisconnectReason:
        """DISCONNECTED reason for a connection attempt that did not reach WELCOME."""
        if stop_event.is_set():
            return DisconnectReason.USER
        if isinstance(exc, _HandshakeError):
            return DisconnectReason.REJECTED  # the server's code travels in the ERROR event
        return DisconnectReason.CONNECT_FAILED

    @staticmethod
    def _error_code(exc: BaseException) -> str:
        """`code` of the ERROR event for `exc` (most specific class first)."""
        if isinstance(exc, _HandshakeError):
            return exc.code
        if isinstance(exc, ConnectionRefusedError):
            return ClientErrorCode.CONNECTION_REFUSED.value
        if isinstance(exc, (TimeoutError, TransportTimeoutError)):
            return ClientErrorCode.CONNECT_TIMEOUT.value
        if isinstance(exc, ProtocolError):
            return ClientErrorCode.PROTOCOL_ERROR.value
        if isinstance(exc, InvalidStateError):
            return ClientErrorCode.INVALID_STATE.value
        if isinstance(exc, (TransportError, OSError)):
            # ConnectionClosedError, ConnectionResetError and other socket errors
            return ClientErrorCode.CONNECTION_LOST.value
        return ErrorCode.INTERNAL_ERROR.value

    def _publish_error(self, exc: BaseException, message: str | None = None) -> None:
        code = self._error_code(exc)
        self._publish(EventType.ERROR, {"code": code, "message": message or str(exc)})

    def _publish(self, event_type: EventType, data: dict[str, Any]) -> None:
        self.event_bus.publish(Event(event_type, data, source="client"))
