"""Unit tests for common/protocol.py (T-01, T-02 and the framing helpers).

OWNER: Sude
"""

from __future__ import annotations

import struct

import pytest

from socketlink.common import protocol as p
from socketlink.common.constants import (
    HEADER_FORMAT,
    HEADER_SIZE,
    MAX_PAYLOAD_SIZE,
    PROTOCOL_VERSION,
    ByeReason,
    ClientErrorCode,
    ErrorCode,
    MessageType,
    PacketFlag,
)
from socketlink.common.exceptions import (
    BadChecksumError,
    MalformedPacketError,
    PayloadTooLargeError,
    ValidationError,
    VersionMismatchError,
)


def _all_packets() -> list[p.Packet]:
    return [
        p.make_hello("sude"),
        p.make_welcome(7, "SocketLink Server", ["sude", "yusuf"]),
        p.make_chat("Merhaba!", to=None),
        p.make_chat("Selam", to="yusuf", sender="sude", timestamp=1760688000.123),
        p.make_ack(41),
        p.make_ping(),
        p.make_pong(),
        p.make_user_list(["hamit", "sude"]),
        p.make_file_start(3, "notes.pdf", 48213, 48, 2882382797, to="yusuf", sender="sude"),
        p.make_file_chunk(3, 0, b"\x00\x01binary\xff"),
        p.make_file_end(3),
        p.make_error("USERNAME_TAKEN", "Username 'sude' is already in use."),
        p.make_bye(),
    ]


def _tamper(data: bytes, index: int) -> bytes:
    return data[:index] + bytes([data[index] ^ 0xFF]) + data[index + 1:]


@pytest.mark.parametrize("packet", _all_packets(), ids=lambda x: x.summary())
def test_encode_decode_roundtrip_returns_same_packet(packet: p.Packet) -> None:
    packet.seq, packet.ack = 5, 4
    packet.flags = PacketFlag.ACK_REQUIRED | PacketFlag.RETRANSMISSION
    assert p.Packet.decode(packet.encode()) == packet


def test_roundtrip_list_covers_every_message_type() -> None:
    assert {x.type for x in _all_packets()} == set(MessageType)


def test_encoded_header_has_the_documented_layout() -> None:
    data = p.make_ping().encode()
    assert len(data) == HEADER_SIZE
    assert data[:2] == b"SL" and data[2] == PROTOCOL_VERSION
    assert data[3] == MessageType.PING and data[5] == 0  # reserved byte


def test_decode_with_changed_payload_byte_raises_bad_checksum() -> None:
    data = p.make_chat("hello").encode()
    with pytest.raises(BadChecksumError):
        p.Packet.decode(_tamper(data, len(data) - 1))


def test_decode_with_changed_header_field_raises_bad_checksum() -> None:
    data = p.Packet(MessageType.PING, seq=9).encode()
    with pytest.raises(BadChecksumError):
        p.Packet.decode(_tamper(data, 9))  # low byte of seq


def test_decode_with_wrong_magic_raises_malformed() -> None:
    data = b"XX" + p.make_ping().encode()[2:]
    with pytest.raises(MalformedPacketError):
        p.Packet.decode(data)


def test_decode_with_wrong_version_raises_version_mismatch() -> None:
    data = bytearray(p.make_ping().encode())
    data[2] = PROTOCOL_VERSION + 1
    with pytest.raises(VersionMismatchError):
        p.Packet.decode(bytes(data))


def test_decode_with_unknown_type_raises_malformed() -> None:
    data = bytearray(p.make_ping().encode())
    data[3] = 99
    with pytest.raises(MalformedPacketError):
        p.Packet.decode(bytes(data))


def test_decode_with_short_input_raises_malformed() -> None:
    with pytest.raises(MalformedPacketError):
        p.Packet.decode(b"SL\x01")


def test_decode_with_truncated_payload_raises_malformed() -> None:
    data = p.make_chat("hello world").encode()
    with pytest.raises(MalformedPacketError):
        p.Packet.decode(data[:-3])


def test_decode_with_trailing_bytes_raises_malformed() -> None:
    with pytest.raises(MalformedPacketError):
        p.Packet.decode(p.make_ping().encode() + b"x")


def test_encode_with_oversized_payload_raises() -> None:
    packet = p.Packet(MessageType.FILE_CHUNK, payload=b"x" * (MAX_PAYLOAD_SIZE + 1))
    with pytest.raises(PayloadTooLargeError):
        packet.encode()


def test_encode_accepts_payload_of_exactly_the_limit() -> None:
    packet = p.Packet(MessageType.FILE_CHUNK, payload=b"x" * MAX_PAYLOAD_SIZE)
    assert p.Packet.decode(packet.encode()) == packet


def test_parse_header_with_oversized_length_raises_payload_too_large() -> None:
    header = struct.pack(HEADER_FORMAT, b"SL", PROTOCOL_VERSION, 9, 0, 0, 0, 0,
                         MAX_PAYLOAD_SIZE + 1, 0)
    with pytest.raises(PayloadTooLargeError):
        p.Packet.parse_header(header)


def test_parse_header_returns_fields_for_tcp_framing() -> None:
    data = p.Packet(MessageType.ACK, ack=12).encode()
    message_type, flags, seq, ack, length, checksum = p.Packet.parse_header(data)
    assert (message_type, flags, seq, ack, length) == (MessageType.ACK, 0, 0, 12, 0)
    assert checksum == struct.unpack(HEADER_FORMAT, data)[-1]


def test_json_payload_reads_back_unicode_fields() -> None:
    packet = p.make_chat("Merhaba dünya ğüşiöç 👋", to="yusuf")
    assert p.Packet.decode(packet.encode()).json_payload() == {
        "text": "Merhaba dünya ğüşiöç 👋", "to": "yusuf",
    }


def test_json_payload_with_invalid_json_raises_malformed() -> None:
    with pytest.raises(MalformedPacketError):
        p.Packet(MessageType.CHAT, payload=b"{not json").json_payload()


def test_json_payload_with_invalid_utf8_raises_malformed() -> None:
    with pytest.raises(MalformedPacketError):
        p.Packet(MessageType.CHAT, payload=b"\xff\xfe").json_payload()


def test_json_payload_with_non_object_raises_malformed() -> None:
    with pytest.raises(MalformedPacketError):
        p.Packet(MessageType.CHAT, payload=b"[1, 2]").json_payload()


def test_chat_client_to_server_has_no_sender_fields() -> None:
    assert p.make_chat("hi").json_payload() == {"text": "hi", "to": None}


def test_chat_server_to_client_carries_from_and_timestamp() -> None:
    fields = p.make_chat("hi", sender="sude", timestamp=1.5).json_payload()
    assert fields == {"text": "hi", "to": None, "from": "sude", "timestamp": 1.5}


def test_file_start_uses_documented_field_names() -> None:
    fields = p.make_file_start(3, "a.txt", 10, 1, 123, to="yusuf").json_payload()
    assert fields == {"transfer_id": 3, "filename": "a.txt", "size": 10,
                      "total_chunks": 1, "checksum": 123, "to": "yusuf"}


def test_file_chunk_roundtrip_through_parse_file_chunk() -> None:
    packet = p.Packet.decode(p.make_file_chunk(7, 12, b"\x00data\xff").encode())
    assert p.parse_file_chunk(packet) == (7, 12, b"\x00data\xff")


def test_parse_file_chunk_with_short_payload_raises_malformed() -> None:
    with pytest.raises(MalformedPacketError):
        p.parse_file_chunk(p.Packet(MessageType.FILE_CHUNK, payload=b"abc"))


def test_parse_file_chunk_with_wrong_type_raises_malformed() -> None:
    with pytest.raises(MalformedPacketError):
        p.parse_file_chunk(p.make_ping())


def test_summary_format() -> None:
    packet = p.make_chat("hi")
    packet.seq = 5
    assert packet.summary() == f"CHAT seq=5 ack=0 len={len(packet.payload)}"


def test_bye_reason_values_match_the_spec() -> None:
    assert {r.value for r in ByeReason} == {
        "client_quit", "server_shutdown", "kicked_by_admin", "timeout",
    }


def test_make_bye_default_reason_is_client_quit() -> None:
    assert p.make_bye().json_payload() == {"reason": "client_quit"}


@pytest.mark.parametrize("reason", list(ByeReason))
def test_make_bye_accepts_enum_member_and_plain_string(reason: ByeReason) -> None:
    assert p.make_bye(reason).json_payload() == {"reason": reason.value}
    assert p.make_bye(reason.value).json_payload() == {"reason": reason.value}


def test_client_error_codes_do_not_collide_with_wire_error_codes() -> None:
    assert {c.value for c in ClientErrorCode}.isdisjoint({c.value for c in ErrorCode})


def test_transfer_id_packs_client_id_and_counter() -> None:
    assert p.make_transfer_id(3, 7) == (3 << 16) | 7
    assert p.transfer_id_client(p.make_transfer_id(3, 7)) == 3


def test_transfer_ids_of_different_clients_never_collide() -> None:
    ids = {p.make_transfer_id(client, counter) for client in range(1, 6) for counter in range(1, 6)}
    assert len(ids) == 25


def test_transfer_id_fits_the_file_chunk_prefix() -> None:
    tid = p.make_transfer_id(65535, 65535)
    packet = p.Packet.decode(p.make_file_chunk(tid, 0, b"x").encode())
    assert p.parse_file_chunk(packet)[0] == tid


@pytest.mark.parametrize(("client_id", "counter"), [(0, 1), (65536, 1), (1, 0), (1, 65536)])
def test_make_transfer_id_rejects_out_of_range_values(client_id: int, counter: int) -> None:
    with pytest.raises(ValidationError):
        p.make_transfer_id(client_id, counter)
