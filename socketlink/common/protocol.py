"""SocketLink application-layer protocol: packet model, encoding, decoding, factories.

OWNER: Sude
SPEC:  docs/PROTOCOL.md  (this file must always match the spec; change the spec first)

Wire format (22-byte header + payload), network byte order:

    | magic 2B | version 1B | type 1B | flags 1B | reserved 1B |
    | seq 4B | ack 4B | length 4B | checksum 4B | payload (length bytes) |

checksum = zlib.crc32(header_with_checksum_zero + payload)
"""

from __future__ import annotations

import json
import struct
import zlib
from dataclasses import dataclass
from typing import Any

from socketlink.common.constants import (
    ENCODING,
    FILE_CHUNK_PREFIX_FORMAT,
    FILE_CHUNK_PREFIX_SIZE,
    HEADER_FORMAT,
    HEADER_SIZE,
    MAX_PAYLOAD_SIZE,
    PROTOCOL_MAGIC,
    PROTOCOL_VERSION,
    MessageType,
    PacketFlag,
)
from socketlink.common.exceptions import (
    BadChecksumError,
    MalformedPacketError,
    PayloadTooLargeError,
    VersionMismatchError,
)

_CHECKSUM_MASK = 0xFFFFFFFF
_CHECKSUM_SIZE = 4


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
        length = len(self.payload)
        if length > MAX_PAYLOAD_SIZE:
            raise PayloadTooLargeError(
                f"Payload is {length} bytes; the limit is {MAX_PAYLOAD_SIZE}."
            )
        fields = (PROTOCOL_MAGIC, PROTOCOL_VERSION, int(self.type), int(self.flags), 0,
                  self.seq, self.ack, length)
        header = struct.pack(HEADER_FORMAT, *fields, 0)
        checksum = zlib.crc32(header + self.payload) & _CHECKSUM_MASK
        return struct.pack(HEADER_FORMAT, *fields, checksum) + self.payload

    @classmethod
    def decode(cls, data: bytes) -> Packet:
        """Parse one complete packet (header + payload).

        Raises MalformedPacketError, BadChecksumError or VersionMismatchError.
        """
        message_type, flags, seq, ack, length, checksum = cls.parse_header(data)
        payload = data[HEADER_SIZE:]
        if len(payload) != length:
            raise MalformedPacketError(
                f"Header announces {length} payload bytes but {len(payload)} arrived."
            )
        header_without_checksum = data[: HEADER_SIZE - _CHECKSUM_SIZE]
        expected = zlib.crc32(
            header_without_checksum + bytes(_CHECKSUM_SIZE) + payload
        ) & _CHECKSUM_MASK
        if expected != checksum:
            raise BadChecksumError("Checksum mismatch; the packet is corrupted.")
        return cls(type=message_type, payload=payload, seq=seq, ack=ack, flags=flags)

    @staticmethod
    def parse_header(header: bytes) -> tuple[MessageType, int, int, int, int, int]:
        """Parse only the 22-byte header -> (type, flags, seq, ack, length, checksum).

        Used by TCP framing: read HEADER_SIZE bytes, call this, then read `length`
        more bytes. Raises MalformedPacketError / VersionMismatchError.
        Extra bytes after the header are ignored.
        """
        if len(header) < HEADER_SIZE:
            raise MalformedPacketError(
                f"A header needs {HEADER_SIZE} bytes, got {len(header)}."
            )
        magic, version, raw_type, flags, _reserved, seq, ack, length, checksum = (
            struct.unpack(HEADER_FORMAT, header[:HEADER_SIZE])
        )
        if magic != PROTOCOL_MAGIC:
            raise MalformedPacketError(f"Wrong magic bytes: {magic!r}.")
        if version != PROTOCOL_VERSION:
            raise VersionMismatchError(
                f"Peer speaks protocol v{version}; this build speaks v{PROTOCOL_VERSION}."
            )
        try:
            message_type = MessageType(raw_type)
        except ValueError:
            raise MalformedPacketError(f"Unknown message type: {raw_type}.") from None
        if length > MAX_PAYLOAD_SIZE:
            raise PayloadTooLargeError(
                f"Header announces {length} payload bytes; the limit is {MAX_PAYLOAD_SIZE}."
            )
        return message_type, flags, seq, ack, length, checksum

    def json_payload(self) -> dict[str, Any]:
        """Decode the payload as UTF-8 JSON. Raises MalformedPacketError."""
        try:
            data = json.loads(self.payload.decode(ENCODING))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MalformedPacketError(f"Payload is not valid UTF-8 JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise MalformedPacketError("A JSON payload must be an object.")
        return data

    def summary(self) -> str:
        """Short human-readable form for logs/GUI, e.g. 'CHAT seq=5 ack=0 len=42'."""
        return f"{self.type.name} seq={self.seq} ack={self.ack} len={len(self.payload)}"


# ---------------------------------------------------------------------- #
# Factory functions (Factory Method pattern).
# ALWAYS create packets through these; never build JSON payloads by hand
# in other modules. Field names follow docs/PROTOCOL.md section 4.
# ---------------------------------------------------------------------- #
def _json_packet(message_type: MessageType, fields: dict[str, Any]) -> Packet:
    """Build a packet whose payload is `fields` as compact UTF-8 JSON."""
    payload = json.dumps(fields, ensure_ascii=False, separators=(",", ":"))
    return Packet(type=message_type, payload=payload.encode(ENCODING))


def make_hello(username: str) -> Packet:
    return _json_packet(MessageType.HELLO, {"username": username})


def make_welcome(client_id: int, server_name: str, users: list[str]) -> Packet:
    return _json_packet(
        MessageType.WELCOME,
        {"client_id": client_id, "server_name": server_name, "users": users},
    )


def make_chat(text: str, to: str | None = None, sender: str | None = None,
              timestamp: float | None = None) -> Packet:
    """Client->server: sender=None. Server->client: sender and timestamp are set."""
    fields: dict[str, Any] = {"text": text, "to": to}
    if sender is not None:
        fields["from"] = sender
    if timestamp is not None:
        fields["timestamp"] = timestamp
    return _json_packet(MessageType.CHAT, fields)


def make_ack(ack: int) -> Packet:
    return Packet(type=MessageType.ACK, ack=ack)


def make_ping() -> Packet:
    return Packet(type=MessageType.PING)


def make_pong() -> Packet:
    return Packet(type=MessageType.PONG)


def make_user_list(users: list[str]) -> Packet:
    return _json_packet(MessageType.USER_LIST, {"users": users})


def make_file_start(transfer_id: int, filename: str, size: int, total_chunks: int,
                    checksum: int, to: str | None = None,
                    sender: str | None = None) -> Packet:
    fields: dict[str, Any] = {
        "transfer_id": transfer_id,
        "filename": filename,
        "size": size,
        "total_chunks": total_chunks,
        "checksum": checksum,
        "to": to,
    }
    if sender is not None:
        fields["from"] = sender
    return _json_packet(MessageType.FILE_START, fields)


def make_file_chunk(transfer_id: int, chunk_index: int, data: bytes) -> Packet:
    """Payload = struct.pack(FILE_CHUNK_PREFIX_FORMAT, transfer_id, chunk_index) + data."""
    prefix = struct.pack(FILE_CHUNK_PREFIX_FORMAT, transfer_id, chunk_index)
    return Packet(type=MessageType.FILE_CHUNK, payload=prefix + data)


def parse_file_chunk(packet: Packet) -> tuple[int, int, bytes]:
    """Inverse of make_file_chunk -> (transfer_id, chunk_index, data)."""
    if packet.type != MessageType.FILE_CHUNK:
        raise MalformedPacketError(f"Expected FILE_CHUNK, got {packet.type.name}.")
    if len(packet.payload) < FILE_CHUNK_PREFIX_SIZE:
        raise MalformedPacketError("FILE_CHUNK payload is shorter than its prefix.")
    transfer_id, chunk_index = struct.unpack(
        FILE_CHUNK_PREFIX_FORMAT, packet.payload[:FILE_CHUNK_PREFIX_SIZE]
    )
    return transfer_id, chunk_index, packet.payload[FILE_CHUNK_PREFIX_SIZE:]


def make_file_end(transfer_id: int) -> Packet:
    return _json_packet(MessageType.FILE_END, {"transfer_id": transfer_id})


def make_error(code: str, message: str) -> Packet:
    return _json_packet(MessageType.ERROR, {"code": code, "message": message})


def make_bye(reason: str = "client_quit") -> Packet:
    return _json_packet(MessageType.BYE, {"reason": reason})
