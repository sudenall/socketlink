"""Runtime configuration objects.

OWNER: Nevin
RULE: Defaults come ONLY from constants.py. GUIs build a config object from their
      input fields and pass it to ChatServer / ChatClient; core code never reads GUI
      widgets.
"""

from __future__ import annotations

import argparse
import ipaddress
import re
from dataclasses import dataclass

from socketlink.common.constants import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_WINDOW_SIZE,
    DOWNLOAD_DIR,
    MAX_CLIENTS,
    MAX_SIMULATED_DELAY_MS,
    MAX_SIMULATED_LOSS,
    MAX_WINDOW_SIZE,
    USERNAME_PATTERN,
    TransportMode,
)
from socketlink.common.exceptions import ValidationError


def _validate_ip_or_host(host: str) -> None:
    """Validate that host is a valid IPv4/IPv6 address or 'localhost'."""
    if not host or not isinstance(host, str):
        raise ValidationError("Host must be a non-empty string.")
    if host.lower() == "localhost":
        return
    try:
        ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValidationError(f"Invalid IP address format: {host}") from exc


def _validate_port(port: int) -> None:
    """Validate that port is an integer between 1024 and 65535."""
    if isinstance(port, bool) or not isinstance(port, int):
        raise ValidationError(f"Port must be an integer, got {type(port).__name__}.")
    if not (1024 <= port <= 65535):
        raise ValidationError(f"Port must be between 1024 and 65535, got {port}.")


def _validate_udp_params(loss_rate: float, delay_ms: int, window_size: int) -> None:
    """Validate reliable UDP simulation parameters."""
    if isinstance(loss_rate, bool) or not isinstance(loss_rate, (int, float)):
        raise ValidationError(f"loss_rate must be a float, got {type(loss_rate).__name__}.")
    if not (0.0 <= loss_rate <= MAX_SIMULATED_LOSS):
        raise ValidationError(
            f"loss_rate must be between 0.0 and {MAX_SIMULATED_LOSS}, got {loss_rate}."
        )

    if isinstance(delay_ms, bool) or not isinstance(delay_ms, int):
        raise ValidationError(f"delay_ms must be an integer, got {type(delay_ms).__name__}.")
    if not (0 <= delay_ms <= MAX_SIMULATED_DELAY_MS):
        raise ValidationError(
            f"delay_ms must be between 0 and {MAX_SIMULATED_DELAY_MS}, got {delay_ms}."
        )

    if isinstance(window_size, bool) or not isinstance(window_size, int):
        raise ValidationError(f"window_size must be an integer, got {type(window_size).__name__}.")
    if not (1 <= window_size <= MAX_WINDOW_SIZE):
        raise ValidationError(
            f"window_size must be between 1 and {MAX_WINDOW_SIZE}, got {window_size}."
        )


def _normalize_mode(mode: TransportMode | str) -> TransportMode:
    """Ensure mode is an instance of TransportMode."""
    if isinstance(mode, TransportMode):
        return mode
    try:
        return TransportMode(mode.lower())
    except (ValueError, AttributeError) as exc:
        raise ValidationError(f"Invalid transport mode: {mode}. Must be 'tcp' or 'udp'.") from exc


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
        """Validate server configuration parameters. Raises ValidationError on invalid values."""
        _validate_ip_or_host(self.host)
        _validate_port(self.port)
        self.mode = _normalize_mode(self.mode)

        if isinstance(self.max_clients, bool) or not isinstance(self.max_clients, int):
            raise ValidationError(
                f"max_clients must be an integer, got {type(self.max_clients).__name__}."
            )
        if not (1 <= self.max_clients <= MAX_CLIENTS):
            raise ValidationError(
                f"max_clients must be between 1 and {MAX_CLIENTS}, got {self.max_clients}."
            )

        if not self.server_name or not isinstance(self.server_name, str):
            raise ValidationError("server_name must be a non-empty string.")

        _validate_udp_params(self.loss_rate, self.delay_ms, self.window_size)

    @classmethod
    def from_args(cls, args: list[str] | None = None) -> ServerConfig:
        """Parse CLI arguments into a validated ServerConfig instance."""
        parser = argparse.ArgumentParser(description="SocketLink Server Configuration")
        parser.add_argument("--host", default="0.0.0.0", help="Host IP to bind (default: 0.0.0.0)")
        parser.add_argument(
            "--port", type=int, default=DEFAULT_PORT, help=f"Port number (default: {DEFAULT_PORT})"
        )
        parser.add_argument(
            "--mode",
            choices=["tcp", "udp"],
            default=TransportMode.TCP.value,
            help="Transport mode (default: tcp)",
        )
        parser.add_argument(
            "--max-clients",
            type=int,
            default=MAX_CLIENTS,
            help=f"Max concurrent clients (default: {MAX_CLIENTS})",
        )
        parser.add_argument(
            "--name",
            dest="server_name",
            default="SocketLink Server",
            help="Server display name",
        )
        parser.add_argument(
            "--loss-rate",
            type=float,
            default=0.0,
            help=f"Simulated packet loss rate 0.0..{MAX_SIMULATED_LOSS}",
        )
        parser.add_argument(
            "--delay-ms",
            type=int,
            default=0,
            help=f"Simulated delay in ms 0..{MAX_SIMULATED_DELAY_MS}",
        )
        parser.add_argument(
            "--window-size",
            type=int,
            default=DEFAULT_WINDOW_SIZE,
            help=f"Reliable UDP window size 1..{MAX_WINDOW_SIZE}",
        )

        parsed = parser.parse_args(args)
        config = cls(
            host=parsed.host,
            port=parsed.port,
            mode=TransportMode(parsed.mode),
            max_clients=parsed.max_clients,
            server_name=parsed.server_name,
            loss_rate=parsed.loss_rate,
            delay_ms=parsed.delay_ms,
            window_size=parsed.window_size,
        )
        config.validate()
        return config


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
        """Validate client configuration parameters. Raises ValidationError on invalid values."""
        _validate_ip_or_host(self.host)
        _validate_port(self.port)
        self.mode = _normalize_mode(self.mode)

        if not isinstance(self.username, str) or not re.match(USERNAME_PATTERN, self.username):
            raise ValidationError(
                f"Invalid username '{self.username}': must match regex {USERNAME_PATTERN} "
                "(3-16 alphanumeric characters or underscores)."
            )

        if not self.download_dir or not isinstance(self.download_dir, str):
            raise ValidationError("download_dir must be a non-empty string.")

        if not isinstance(self.auto_reconnect, bool):
            raise ValidationError(
                f"auto_reconnect must be a boolean, got {type(self.auto_reconnect).__name__}."
            )

        _validate_udp_params(self.loss_rate, self.delay_ms, self.window_size)

    @classmethod
    def from_args(cls, args: list[str] | None = None) -> ClientConfig:
        """Parse CLI arguments into a ClientConfig instance. Validates if username is provided."""
        parser = argparse.ArgumentParser(description="SocketLink Client Configuration")
        parser.add_argument(
            "--host", default=DEFAULT_HOST, help=f"Server host IP (default: {DEFAULT_HOST})"
        )
        parser.add_argument(
            "--port", type=int, default=DEFAULT_PORT, help=f"Server port (default: {DEFAULT_PORT})"
        )
        parser.add_argument(
            "--mode",
            choices=["tcp", "udp"],
            default=TransportMode.TCP.value,
            help="Transport mode (default: tcp)",
        )
        parser.add_argument("--username", default="", help="Client username (3-16 chars)")
        parser.add_argument(
            "--download-dir",
            default=DOWNLOAD_DIR,
            help=f"Download directory (default: {DOWNLOAD_DIR})",
        )
        parser.add_argument(
            "--loss-rate",
            type=float,
            default=0.0,
            help=f"Simulated loss rate 0.0..{MAX_SIMULATED_LOSS}",
        )
        parser.add_argument(
            "--delay-ms",
            type=int,
            default=0,
            help=f"Simulated delay in ms 0..{MAX_SIMULATED_DELAY_MS}",
        )
        parser.add_argument(
            "--window-size",
            type=int,
            default=DEFAULT_WINDOW_SIZE,
            help=f"Reliable UDP window size 1..{MAX_WINDOW_SIZE}",
        )

        parsed = parser.parse_args(args)
        config = cls(
            host=parsed.host,
            port=parsed.port,
            mode=TransportMode(parsed.mode),
            username=parsed.username,
            download_dir=parsed.download_dir,
            loss_rate=parsed.loss_rate,
            delay_ms=parsed.delay_ms,
            window_size=parsed.window_size,
        )
        if config.username:
            config.validate()
        return config
