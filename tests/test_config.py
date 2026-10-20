"""Unit tests for ServerConfig and ClientConfig validation and CLI argument parsing.

OWNER: Nevin
"""

from __future__ import annotations

import unittest

from socketlink.common.config import ClientConfig, ServerConfig
from socketlink.common.constants import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    MAX_CLIENTS,
    MAX_SIMULATED_DELAY_MS,
    MAX_SIMULATED_LOSS,
    MAX_WINDOW_SIZE,
    TransportMode,
)
from socketlink.common.exceptions import ValidationError


class TestServerConfig(unittest.TestCase):
    def test_default_config_is_valid(self) -> None:
        cfg = ServerConfig()
        cfg.validate()
        self.assertEqual(cfg.host, "0.0.0.0")
        self.assertEqual(cfg.port, DEFAULT_PORT)
        self.assertEqual(cfg.mode, TransportMode.TCP)
        self.assertEqual(cfg.max_clients, MAX_CLIENTS)

    def test_valid_custom_config(self) -> None:
        cfg = ServerConfig(
            host="127.0.0.1",
            port=8080,
            mode=TransportMode.UDP,
            max_clients=25,
            server_name="TestServer",
            loss_rate=0.2,
            delay_ms=50,
            window_size=8,
        )
        cfg.validate()
        self.assertEqual(cfg.loss_rate, 0.2)
        self.assertEqual(cfg.delay_ms, 50)
        self.assertEqual(cfg.window_size, 8)

    def test_invalid_ip_raises_validation_error(self) -> None:
        invalid_hosts = ["999.999.999.999", "not_an_ip", "", "192.168.1.500"]
        for host in invalid_hosts:
            with self.subTest(host=host):
                cfg = ServerConfig(host=host)
                with self.assertRaises(ValidationError):
                    cfg.validate()

    def test_localhost_is_accepted(self) -> None:
        cfg = ServerConfig(host="localhost")
        cfg.validate()

    def test_invalid_port_raises_validation_error(self) -> None:
        invalid_ports = [80, 1023, 65536, 100000, -1]
        for port in invalid_ports:
            with self.subTest(port=port):
                cfg = ServerConfig(port=port)
                with self.assertRaises(ValidationError):
                    cfg.validate()

    def test_port_zero_is_accepted_for_ephemeral_binding(self) -> None:
        cfg = ServerConfig(port=0)
        cfg.validate()
        self.assertEqual(cfg.port, 0)

    def test_invalid_max_clients(self) -> None:
        invalid_counts = [0, -5, MAX_CLIENTS + 1, 100]
        for count in invalid_counts:
            with self.subTest(count=count):
                cfg = ServerConfig(max_clients=count)
                with self.assertRaises(ValidationError):
                    cfg.validate()

    def test_invalid_simulation_params(self) -> None:
        # loss_rate out of range
        with self.assertRaises(ValidationError):
            ServerConfig(loss_rate=-0.01).validate()
        with self.assertRaises(ValidationError):
            ServerConfig(loss_rate=MAX_SIMULATED_LOSS + 0.05).validate()

        # delay_ms out of range
        with self.assertRaises(ValidationError):
            ServerConfig(delay_ms=-1).validate()
        with self.assertRaises(ValidationError):
            ServerConfig(delay_ms=MAX_SIMULATED_DELAY_MS + 1).validate()

        # window_size out of range
        with self.assertRaises(ValidationError):
            ServerConfig(window_size=0).validate()
        with self.assertRaises(ValidationError):
            ServerConfig(window_size=MAX_WINDOW_SIZE + 1).validate()

    def test_from_args_parsing(self) -> None:
        args = [
            "--host",
            "127.0.0.1",
            "--port",
            "6060",
            "--mode",
            "udp",
            "--max-clients",
            "20",
            "--loss-rate",
            "0.15",
            "--delay-ms",
            "30",
            "--window-size",
            "6",
        ]
        cfg = ServerConfig.from_args(args)
        self.assertEqual(cfg.host, "127.0.0.1")
        self.assertEqual(cfg.port, 6060)
        self.assertEqual(cfg.mode, TransportMode.UDP)
        self.assertEqual(cfg.max_clients, 20)
        self.assertAlmostEqual(cfg.loss_rate, 0.15)
        self.assertEqual(cfg.delay_ms, 30)
        self.assertEqual(cfg.window_size, 6)


class TestClientConfig(unittest.TestCase):
    def test_valid_client_config(self) -> None:
        cfg = ClientConfig(username="alice_123")
        cfg.validate()
        self.assertEqual(cfg.host, DEFAULT_HOST)
        self.assertEqual(cfg.port, DEFAULT_PORT)
        self.assertEqual(cfg.username, "alice_123")

    def test_empty_or_invalid_username_raises(self) -> None:
        invalid_usernames = [
            "",
            "a",             # too short (<3)
            "ab",            # too short
            "user@name",     # invalid character
            "user-name",     # hyphen not allowed by pattern ^[A-Za-z0-9_]{3,16}$
            "toolongusernameexceeds16",  # >16
            "has space",
            "alice\n",       # trailing newline rejected by re.fullmatch
        ]
        for name in invalid_usernames:
            with self.subTest(username=name):
                cfg = ClientConfig(username=name)
                with self.assertRaises(ValidationError):
                    cfg.validate()

    def test_valid_username_patterns(self) -> None:
        valid_names = ["bob", "Alice_99", "admin_user", "DEV123"]
        for name in valid_names:
            with self.subTest(username=name):
                cfg = ClientConfig(username=name)
                cfg.validate()

    def test_client_invalid_port_and_host(self) -> None:
        with self.assertRaises(ValidationError):
            ClientConfig(username="alice", host="bad_host").validate()
        with self.assertRaises(ValidationError):
            ClientConfig(username="alice", port=80).validate()

    def test_client_from_args(self) -> None:
        args = [
            "--host",
            "192.168.1.100",
            "--port",
            "7070",
            "--mode",
            "udp",
            "--username",
            "charlie",
            "--loss-rate",
            "0.25",
        ]
        cfg = ClientConfig.from_args(args)
        self.assertEqual(cfg.host, "192.168.1.100")
        self.assertEqual(cfg.port, 7070)
        self.assertEqual(cfg.mode, TransportMode.UDP)
        self.assertEqual(cfg.username, "charlie")
        self.assertAlmostEqual(cfg.loss_rate, 0.25)


if __name__ == "__main__":
    unittest.main()
