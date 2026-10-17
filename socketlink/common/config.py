"""Runtime configuration objects.

OWNER: Nevin
RULE: Defaults come ONLY from constants.py. GUIs build a config object from their
      input fields and pass it to ChatServer / ChatClient; core code never reads GUI
      widgets.

TODO(Nevin):
- `validate()` for both classes (raise ValidationError): IP format (ipaddress module),
  port 1024-65535, username regex, loss_rate 0..MAX_SIMULATED_LOSS, window 1..MAX_WINDOW_SIZE.
- Optional `from_args()` helper so run_server.py / run_client.py accept --host --port --mode.
"""

from __future__ import annotations

from dataclasses import dataclass

from socketlink.common.constants import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_WINDOW_SIZE,
    DOWNLOAD_DIR,
    MAX_CLIENTS,
    TransportMode,
)


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = DEFAULT_PORT
    mode: TransportMode = TransportMode.TCP
    max_clients: int = MAX_CLIENTS
    server_name: str = "SocketLink Server"
    loss_rate: float = 0.0     # reliable UDP only
    delay_ms: int = 0          # reliable UDP only
    window_size: int = DEFAULT_WINDOW_SIZE

    def validate(self) -> None:
        raise NotImplementedError("TODO(Nevin)")


@dataclass
class ClientConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    mode: TransportMode = TransportMode.TCP
    username: str = ""
    auto_reconnect: bool = True
    download_dir: str = DOWNLOAD_DIR
    loss_rate: float = 0.0
    delay_ms: int = 0
    window_size: int = DEFAULT_WINDOW_SIZE

    def validate(self) -> None:
        raise NotImplementedError("TODO(Nevin)")
