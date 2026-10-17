"""SocketLink application-layer protocol: packet model, encoding, decoding, factories.

OWNER: Sude
SPEC:  docs/PROTOCOL.md  (this file must always match the spec; change the spec first)

Wire format (22-byte header + payload), network byte order:

    | magic 2B | version 1B | type 1B | flags 1B | reserved 1B |
    | seq 4B | ack 4B | length 4B | checksum 4B | payload (length bytes) |

checksum = zlib.crc32(header_with_checksum_zero + payload)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from socketlink.common.constants import MessageType, PacketFlag


@dataclass
class Packet:
    """One protocol message.

    `payload` is always raw bytes. For JSON message types use `json_payload()`
    to read it and the factory functions below to create it.
    """

    type: MessageType
    payload: bytes = b""
    seq: int = 0
    ack: int = 0
    flags: int = PacketFlag.NONE

    # ------------------------------------------------------------------ #
    # Encoding / decoding
    # ------------------------------------------------------------------ #
    def encode(self) -> bytes:
        """Return header + payload as bytes, with checksum filled in.

        Raises PayloadTooLargeError if len(payload) > MAX_PAYLOAD_SIZE.
        """
        raise NotImplementedError("TODO(Sude)")

    @classmethod
    def decode(cls, data: bytes) -> Packet:
        """Parse one complete packet (header + payload).

        Raises MalformedPacketError, BadChecksumError or VersionMismatchError.
        """
        raise NotImplementedError("TODO(Sude)")

    @staticmethod
    def parse_header(header: bytes) -> tuple[MessageType, int, int, int, int, int]:
        """Parse only the 22-byte header -> (type, flags, seq, ack, length, checksum).

        Used by TCP framing: read HEADER_SIZE bytes, call this, then read `length`
        more bytes. Raises MalformedPacketError / VersionMismatchError.
        """
        raise NotImplementedError("TODO(Sude)")

    def json_payload(self) -> dict[str, Any]:
        """Decode the payload as UTF-8 JSON. Raises MalformedPacketError."""
        raise NotImplementedError("TODO(Sude)")

    def summary(self) -> str:
        """Short human-readable form for logs/GUI, e.g. 'CHAT seq=5 ack=0 len=42'."""
        raise NotImplementedError("TODO(Sude)")


# ---------------------------------------------------------------------- #
# Factory functions (Factory Method pattern).
# ALWAYS create packets through these; never build JSON payloads by hand
# in other modules. Field names follow docs/PROTOCOL.md section 4.
# ---------------------------------------------------------------------- #
def make_hello(username: str) -> Packet:
    raise NotImplementedError("TODO(Sude)")


def make_welcome(client_id: int, server_name: str, users: list[str]) -> Packet:
    raise NotImplementedError("TODO(Sude)")


def make_chat(text: str, to: str | None = None, sender: str | None = None,
              timestamp: float | None = None) -> Packet:
    """Client->server: sender=None. Server->client: sender and timestamp are set."""
    raise NotImplementedError("TODO(Sude)")


def make_ack(ack: int) -> Packet:
    raise NotImplementedError("TODO(Sude)")


def make_ping() -> Packet:
    raise NotImplementedError("TODO(Sude)")


def make_pong() -> Packet:
    raise NotImplementedError("TODO(Sude)")


def make_user_list(users: list[str]) -> Packet:
    raise NotImplementedError("TODO(Sude)")


def make_file_start(transfer_id: int, filename: str, size: int, total_chunks: int,
                    checksum: int, to: str | None = None,
                    sender: str | None = None) -> Packet:
    raise NotImplementedError("TODO(Sude)")


def make_file_chunk(transfer_id: int, chunk_index: int, data: bytes) -> Packet:
    """Payload = struct.pack(FILE_CHUNK_PREFIX_FORMAT, transfer_id, chunk_index) + data."""
    raise NotImplementedError("TODO(Sude)")


def parse_file_chunk(packet: Packet) -> tuple[int, int, bytes]:
    """Inverse of make_file_chunk -> (transfer_id, chunk_index, data)."""
    raise NotImplementedError("TODO(Sude)")


def make_file_end(transfer_id: int) -> Packet:
    raise NotImplementedError("TODO(Sude)")


def make_error(code: str, message: str) -> Packet:
    raise NotImplementedError("TODO(Sude)")


def make_bye(reason: str = "client_quit") -> Packet:
    raise NotImplementedError("TODO(Sude)")
