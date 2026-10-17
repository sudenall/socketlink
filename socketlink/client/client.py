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
"""

from __future__ import annotations

import threading

from socketlink.common.config import ClientConfig
from socketlink.common.constants import ConnectionState
from socketlink.common.events import EventBus
from socketlink.common.transport import Transport


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

    # ---- state -----------------------------------------------------------
    @property
    def state(self) -> ConnectionState:
        return self._state

    def _set_state(self, new_state: ConnectionState) -> None:
        """Validate against STATE_TRANSITIONS, update, publish STATE_CHANGED.
        Raises InvalidStateError for an illegal transition."""
        raise NotImplementedError("TODO(Hamit)")

    # ---- public API --------------------------------------------------------
    def connect(self, config: ClientConfig | None = None) -> None:
        """Validate config, then in a background thread: create_transport -> send HELLO
        -> wait for WELCOME or ERROR -> publish CONNECTED or ERROR."""
        raise NotImplementedError("TODO(Hamit)")

    def disconnect(self) -> None:
        """Send BYE, stop threads, close transport, publish DISCONNECTED(reason='user')."""
        raise NotImplementedError("TODO(Hamit)")

    def send_chat(self, text: str, to: str | None = None) -> None:
        """to=None -> everyone. Raises InvalidStateError if not CONNECTED,
        ValidationError if text is empty or longer than MAX_CHAT_LENGTH."""
        raise NotImplementedError("TODO(Hamit)")

    def send_file(self, path: str, to: str | None = None) -> int:
        """Start a FileSender in a background thread. Returns transfer_id."""
        raise NotImplementedError("TODO(Hamit + Tina)")

    def get_stats(self) -> dict[str, int | float]:
        raise NotImplementedError("TODO(Hamit)")

    def set_network_conditions(self, loss_rate: float, delay_ms: int) -> None:
        raise NotImplementedError("TODO(Hamit)")

    # ---- internals ----------------------------------------------------------
    def _receive_loop(self) -> None:
        """Dispatch on packet.type. On ConnectionClosedError / TransportTimeoutError
        -> _handle_connection_lost()."""
        raise NotImplementedError("TODO(Hamit)")

    def _heartbeat_loop(self) -> None:
        raise NotImplementedError("TODO(Hamit)")

    def _handle_connection_lost(self, reason: str) -> None:
        """If config.auto_reconnect: RECONNECTING and retry with RECONNECT_DELAYS,
        else DISCONNECTED. Always publish an event; never raise."""
        raise NotImplementedError("TODO(Hamit)")
