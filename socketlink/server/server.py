"""Multi-client chat server (thread-per-client).

OWNER: Yusuf
USES:  common/transport.py (create_listener), common/protocol.py (make_*),
       common/events.py (EventBus), common/config.py (ServerConfig)
USED BY: gui/server_gui.py (Tina)

Thread model:
    accept thread          -> waits in listener.accept(timeout=SOCKET_TIMEOUT), loops until stop
    one ClientHandler/client -> loops on transport.receive(), handles packets
    heartbeat watchdog     -> every second: disconnect clients silent > CONNECTION_TIMEOUT
All threads: daemon=True, name="srv-accept" / "srv-client-<username>" / "srv-watchdog",
and they all stop when `self._stop_event` is set.

Shared state: `self._clients` (username -> ClientHandler) is ONLY touched while
holding `self._clients_lock`. Never send on a socket while holding the lock
(copy the list first, release, then send).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from socketlink.common.config import ServerConfig
from socketlink.common.events import EventBus
from socketlink.common.protocol import Packet
from socketlink.common.transport import Address, Transport


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
        super().__init__(daemon=True)
        self.server = server
        self.transport = transport
        self.username: str | None = None

    def run(self) -> None:
        raise NotImplementedError("TODO(Yusuf)")

    def send(self, packet: Packet) -> None:
        """Thread-safe send to this client; on failure, disconnect this client."""
        raise NotImplementedError("TODO(Yusuf)")

    def handle_packet(self, packet: Packet) -> None:
        """Dispatch on packet.type: HELLO, CHAT, PING, FILE_*, BYE (see PROTOCOL.md 5)."""
        raise NotImplementedError("TODO(Yusuf)")


class ChatServer:
    """Public API used by the server GUI. All methods are non-blocking."""

    def __init__(self, event_bus: EventBus, config: ServerConfig | None = None) -> None:
        self.event_bus = event_bus
        self.config = config or ServerConfig()
        self._clients: dict[str, ClientHandler] = {}
        self._clients_lock = threading.Lock()
        self._stop_event = threading.Event()

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        """Bind using self.config, start the accept + watchdog threads,
        publish SERVER_STARTED. Raises OSError if the port is busy."""
        raise NotImplementedError("TODO(Yusuf)")

    def stop(self) -> None:
        """Send BYE to everyone, close all transports, join threads, publish SERVER_STOPPED."""
        raise NotImplementedError("TODO(Yusuf)")

    @property
    def is_running(self) -> bool:
        raise NotImplementedError("TODO(Yusuf)")

    # ---- routing (called by ClientHandler) --------------------------------
    def register(self, handler: ClientHandler, username: str) -> None:
        """Validate username, add to _clients, send WELCOME, broadcast USER_LIST,
        publish CLIENT_JOINED. Raise ValidationError for invalid/duplicate names."""
        raise NotImplementedError("TODO(Yusuf)")

    def unregister(self, handler: ClientHandler, reason: str) -> None:
        raise NotImplementedError("TODO(Yusuf)")

    def broadcast(self, packet: Packet, exclude: str | None = None) -> None:
        raise NotImplementedError("TODO(Yusuf)")

    def send_to(self, username: str, packet: Packet) -> bool:
        """Return False if the user is not connected."""
        raise NotImplementedError("TODO(Yusuf)")

    # ---- dashboard helpers -------------------------------------------------
    def get_clients(self) -> list[ClientInfo]:
        raise NotImplementedError("TODO(Yusuf)")

    def kick(self, username: str, reason: str = "kicked_by_admin") -> None:
        raise NotImplementedError("TODO(Yusuf)")

    def get_stats(self) -> dict[str, int | float]:
        """Sum of all client transports' stats.snapshot()."""
        raise NotImplementedError("TODO(Yusuf)")

    def set_network_conditions(self, loss_rate: float, delay_ms: int) -> None:
        """Forward to every transport (UDP only; TCP ignores it)."""
        raise NotImplementedError("TODO(Yusuf)")
