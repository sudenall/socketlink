"""Unit tests for transfer/file_transfer.py (T-14 without a network, T-15).

OWNER: Tina

No server is needed: FileSender's send function hands every packet to a FileReceiver,
going through encode/decode like the wire does. `_relay` also adds "from" to FILE_START,
which is the only thing the real server changes.
"""

from __future__ import annotations

import os
import queue
import zlib
from collections.abc import Callable
from pathlib import Path

import pytest

from socketlink.common.constants import (
    FILE_CHUNK_SIZE,
    MAX_FILE_SIZE,
    FileFailReason,
    MessageType,
)
from socketlink.common.events import Event, EventBus, EventType
from socketlink.common.exceptions import ConnectionClosedError, ValidationError
from socketlink.common.protocol import (
    Packet,
    make_file_chunk,
    make_file_end,
    make_file_start,
    make_ping,
)
from socketlink.transfer.file_transfer import FileReceiver, FileSender, safe_filename

SENDER = "alice"
RECEIVER = "bob"


# ---- helpers ------------------------------------------------------------------
def _drain(q: queue.Queue[Event]) -> list[Event]:
    events = []
    while True:
        try:
            events.append(q.get_nowait())
        except queue.Empty:
            return events


def _of(events: list[Event], event_type: EventType, direction: str) -> list[Event]:
    return [e for e in events if e.type == event_type and e.data["direction"] == direction]


def _relay(receiver: FileReceiver, sent: list[Packet] | None = None,
           drop: Callable[[Packet], bool] | None = None) -> Callable[[Packet], None]:
    """Send function that behaves like the server relaying packets to `receiver`."""

    def send(packet: Packet) -> None:
        if sent is not None:
            sent.append(packet)
        if drop is not None and drop(packet):
            return
        packet = Packet.decode(packet.encode())
        if packet.type == MessageType.FILE_START:
            f = packet.json_payload()
            packet = make_file_start(f["transfer_id"], f["filename"], f["size"],
                                     f["total_chunks"], f["checksum"], to=f["to"],
                                     sender=SENDER)
        receiver.handle_packet(packet)

    return send


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.fixture
def events(bus: EventBus) -> queue.Queue[Event]:
    return bus.subscribe_queue()


@pytest.fixture
def receiver(tmp_path: Path, bus: EventBus) -> FileReceiver:
    return FileReceiver(str(tmp_path / "downloads"), RECEIVER, bus)


def _make_file(folder: Path, name: str, data: bytes) -> Path:
    path = folder / name
    path.write_bytes(data)
    return path


def _transfer(path: Path, receiver: FileReceiver, bus: EventBus,
              transfer_id: int = 1, **relay_args: object) -> FileSender:
    sender = FileSender(str(path), transfer_id, _relay(receiver, **relay_args), bus, to=RECEIVER)
    sender.send()
    return sender


def _start(transfer_id: int, data: bytes, filename: str = "f.bin",
           checksum: int | None = None) -> Packet:
    total = -(-len(data) // FILE_CHUNK_SIZE)
    crc = zlib.crc32(data) if checksum is None else checksum
    return make_file_start(transfer_id, filename, len(data), total, crc, to=RECEIVER,
                           sender=SENDER)


def _part_files(receiver: FileReceiver) -> list[Path]:
    return list(receiver.target_dir.glob(".*.part"))


# ---- successful transfers ----------------------------------------------------------
@pytest.mark.parametrize("size", [0, 1, FILE_CHUNK_SIZE, FILE_CHUNK_SIZE + 1, 1024 * 1024])
def test_send_and_receive_with_various_sizes_saves_identical_file(
        tmp_path: Path, bus: EventBus, events: queue.Queue[Event],
        receiver: FileReceiver, size: int) -> None:
    data = os.urandom(size)
    _transfer(_make_file(tmp_path, "data.bin", data), receiver, bus)

    saved = receiver.target_dir / "data.bin"
    assert saved.read_bytes() == data
    assert _part_files(receiver) == []
    got = _drain(events)
    for event in got:
        event.validate()
    assert [e.data["path"] for e in _of(got, EventType.FILE_COMPLETED, "download")] == [
        str(saved)]
    assert len(_of(got, EventType.FILE_COMPLETED, "upload")) == 1
    assert not [e for e in got if e.type == EventType.FILE_FAILED]


def test_receiver_publishes_file_offered_with_sender(
        tmp_path: Path, bus: EventBus, events: queue.Queue[Event],
        receiver: FileReceiver) -> None:
    _transfer(_make_file(tmp_path, "notes.txt", b"hello"), receiver, bus, transfer_id=7)
    offered = [e for e in _drain(events) if e.type == EventType.FILE_OFFERED]
    assert [e.data for e in offered] == [{"transfer_id": 7, "direction": "download",
                                          "from": SENDER, "filename": "notes.txt", "size": 5}]


def test_progress_is_throttled_and_ends_at_total(
        tmp_path: Path, bus: EventBus, events: queue.Queue[Event],
        receiver: FileReceiver) -> None:
    size = 1024 * 1024
    _transfer(_make_file(tmp_path, "big.bin", os.urandom(size)), receiver, bus)
    got = _drain(events)
    for direction in ("upload", "download"):
        progress = _of(got, EventType.FILE_PROGRESS, direction)
        assert 1 <= len(progress) < size // FILE_CHUNK_SIZE
        assert progress[-1].data["done_bytes"] == progress[-1].data["total_bytes"] == size


def test_existing_name_gets_numbered_suffix(
        tmp_path: Path, bus: EventBus, receiver: FileReceiver) -> None:
    path = _make_file(tmp_path, "notes.txt", b"v1")
    _transfer(path, receiver, bus, transfer_id=1)
    path.write_bytes(b"v2")
    _transfer(path, receiver, bus, transfer_id=2)
    path.write_bytes(b"v3")
    _transfer(path, receiver, bus, transfer_id=3)

    folder = receiver.target_dir
    assert (folder / "notes.txt").read_bytes() == b"v1"
    assert (folder / "notes (1).txt").read_bytes() == b"v2"
    assert (folder / "notes (2).txt").read_bytes() == b"v3"


# ---- T-15: file names from the network ---------------------------------------------
@pytest.mark.parametrize("name", ["../../evil.txt", "..\\..\\evil.txt", "/etc/evil.txt",
                                  "C:\\Windows\\evil.txt", "sub/dir/evil.txt"])
def test_path_traversal_name_is_saved_inside_download_dir(
        tmp_path: Path, receiver: FileReceiver, name: str) -> None:
    data = b"not so evil"
    receiver.handle_packet(_start(1, data, filename=name))
    receiver.handle_packet(make_file_chunk(1, 0, data))
    receiver.handle_packet(make_file_end(1))

    assert (receiver.target_dir / "evil.txt").read_bytes() == data
    assert [p for p in tmp_path.rglob("evil.txt")] == [receiver.target_dir / "evil.txt"]


@pytest.mark.parametrize(("name", "expected"), [
    ("report.pdf", "report.pdf"),
    ("../../evil.txt", "evil.txt"),
    ("..\\evil.txt", "evil.txt"),
    ("", "fallback"),
    (".", "fallback"),
    ("..", "fallback"),
    ("folder/", "folder"),
])
def test_safe_filename(name: str, expected: str) -> None:
    assert safe_filename(name, "fallback") == expected


# ---- sender validation -----------------------------------------------------------
def test_validate_without_recipient_raises(tmp_path: Path, bus: EventBus) -> None:
    path = _make_file(tmp_path, "a.txt", b"x")
    with pytest.raises(ValidationError):
        FileSender(str(path), 1, lambda p: None, bus, to=None).validate()


def test_validate_missing_file_raises(tmp_path: Path, bus: EventBus) -> None:
    with pytest.raises(ValidationError):
        FileSender(str(tmp_path / "nope.txt"), 1, lambda p: None, bus, to=RECEIVER).validate()


def test_validate_too_large_file_raises(tmp_path: Path, bus: EventBus) -> None:
    path = tmp_path / "huge.bin"
    with open(path, "wb") as file:
        file.truncate(MAX_FILE_SIZE + 1)   # sparse, so the test stays fast
    with pytest.raises(ValidationError):
        FileSender(str(path), 1, lambda p: None, bus, to=RECEIVER).validate()


def test_validate_returns_size(tmp_path: Path, bus: EventBus) -> None:
    path = _make_file(tmp_path, "a.txt", b"12345")
    assert FileSender(str(path), 1, lambda p: None, bus, to=RECEIVER).validate() == 5


@pytest.mark.parametrize("to", [None, ""])
def test_send_without_recipient_sends_nothing_and_fails(
        tmp_path: Path, bus: EventBus, events: queue.Queue[Event], to: str | None) -> None:
    sent: list[Packet] = []
    FileSender(str(_make_file(tmp_path, "a.txt", b"x")), 1, sent.append, bus, to=to).send()
    assert sent == []
    failed = [e for e in _drain(events) if e.type == EventType.FILE_FAILED]
    assert [e.data["reason"] for e in failed] == [FileFailReason.INVALID_FILE.value]


def test_send_error_becomes_file_failed_and_does_not_raise(
        tmp_path: Path, bus: EventBus, events: queue.Queue[Event]) -> None:
    def broken_send(packet: Packet) -> None:
        raise ConnectionClosedError("server went away")

    path = _make_file(tmp_path, "a.txt", b"x" * 5000)
    FileSender(str(path), 1, broken_send, bus, to=RECEIVER).send()
    failed = _of(_drain(events), EventType.FILE_FAILED, "upload")
    assert [e.data["reason"] for e in failed] == [FileFailReason.SEND_ERROR.value]


def test_cancel_mid_transfer_fails_both_sides_without_saving(
        tmp_path: Path, bus: EventBus, events: queue.Queue[Event],
        receiver: FileReceiver) -> None:
    sent: list[Packet] = []
    relay = _relay(receiver, sent)
    sender = FileSender(str(_make_file(tmp_path, "a.bin", os.urandom(10_000))), 1,
                        lambda p: (relay(p), len(sent) == 3 and sender.cancel()), bus,
                        to=RECEIVER)
    sender.send()

    assert sent[-1].type == MessageType.FILE_END
    assert len([p for p in sent if p.type == MessageType.FILE_CHUNK]) == 2
    got = _drain(events)
    assert [e.data["reason"] for e in _of(got, EventType.FILE_FAILED, "upload")] == [
        FileFailReason.CANCELLED.value]
    assert [e.data["reason"] for e in _of(got, EventType.FILE_FAILED, "download")] == [
        FileFailReason.MISSING_CHUNKS.value]
    assert list(receiver.target_dir.iterdir()) == []


# ---- receiver failures (nothing may be written) -------------------------------------
def _assert_failed(events: queue.Queue[Event], receiver: FileReceiver, reason: str) -> None:
    failed = _of(_drain(events), EventType.FILE_FAILED, "download")
    assert [e.data["reason"] for e in failed] == [reason]
    if receiver.target_dir.exists():
        assert list(receiver.target_dir.iterdir()) == []


def test_missing_last_chunk_fails(
        tmp_path: Path, bus: EventBus, events: queue.Queue[Event],
        receiver: FileReceiver) -> None:
    def drop_last(packet: Packet) -> bool:
        return packet.type == MessageType.FILE_CHUNK and packet.payload[4:8] == b"\0\0\0\2"

    _transfer(_make_file(tmp_path, "a.bin", os.urandom(3 * FILE_CHUNK_SIZE)), receiver, bus,
              drop=drop_last)
    _assert_failed(events, receiver, FileFailReason.MISSING_CHUNKS.value)


def test_missing_middle_chunk_fails(
        tmp_path: Path, bus: EventBus, events: queue.Queue[Event],
        receiver: FileReceiver) -> None:
    def drop_second(packet: Packet) -> bool:
        return packet.type == MessageType.FILE_CHUNK and packet.payload[4:8] == b"\0\0\0\1"

    _transfer(_make_file(tmp_path, "a.bin", os.urandom(3 * FILE_CHUNK_SIZE)), receiver, bus,
              drop=drop_second)
    _assert_failed(events, receiver, FileFailReason.BAD_CHUNK.value)


def test_bad_crc_fails(events: queue.Queue[Event], receiver: FileReceiver) -> None:
    data = b"some data"
    receiver.handle_packet(_start(1, data, checksum=zlib.crc32(data) ^ 1))
    receiver.handle_packet(make_file_chunk(1, 0, data))
    receiver.handle_packet(make_file_end(1))
    _assert_failed(events, receiver, FileFailReason.CHECKSUM_MISMATCH.value)


def test_corrupted_chunk_data_fails_crc(
        events: queue.Queue[Event], receiver: FileReceiver) -> None:
    data = b"some data"
    receiver.handle_packet(_start(1, data))
    receiver.handle_packet(make_file_chunk(1, 0, b"SOME DATA"))
    receiver.handle_packet(make_file_end(1))
    _assert_failed(events, receiver, FileFailReason.CHECKSUM_MISMATCH.value)


def test_too_large_offer_is_refused(events: queue.Queue[Event], receiver: FileReceiver) -> None:
    size = MAX_FILE_SIZE + 1
    receiver.handle_packet(make_file_start(1, "huge.bin", size, -(-size // FILE_CHUNK_SIZE),
                                           0, to=RECEIVER, sender=SENDER))
    _assert_failed(events, receiver, FileFailReason.FILE_TOO_LARGE.value)


def test_wrong_chunk_count_is_refused(events: queue.Queue[Event], receiver: FileReceiver) -> None:
    receiver.handle_packet(make_file_start(1, "a.bin", 5000, 2, 0, to=RECEIVER, sender=SENDER))
    _assert_failed(events, receiver, FileFailReason.BAD_PACKET.value)


def test_same_transfer_id_from_two_senders_fails_both(
        events: queue.Queue[Event], receiver: FileReceiver) -> None:
    receiver.handle_packet(_start(1, b"from alice"))
    receiver.handle_packet(make_file_start(1, "b.bin", 3, 1, zlib.crc32(b"abc"), to=RECEIVER,
                                           sender="carol"))
    receiver.handle_packet(make_file_chunk(1, 0, b"abc"))
    receiver.handle_packet(make_file_end(1))
    failed = _of(_drain(events), EventType.FILE_FAILED, "download")
    assert [e.data["reason"] for e in failed] == [FileFailReason.TRANSFER_ID_CONFLICT.value] * 2
    assert list(receiver.target_dir.iterdir()) == []


def test_abort_all_fails_open_transfers_and_removes_part_files(
        events: queue.Queue[Event], receiver: FileReceiver) -> None:
    receiver.handle_packet(_start(1, b"x" * 3000))
    receiver.handle_packet(make_file_chunk(1, 0, b"x" * FILE_CHUNK_SIZE))
    receiver.handle_packet(_start(2, b"y" * 10))
    assert len(_part_files(receiver)) == 2

    receiver.abort_all()
    receiver.abort_all()   # second call is a no-op
    failed = _of(_drain(events), EventType.FILE_FAILED, "download")
    assert sorted(e.data["transfer_id"] for e in failed) == [1, 2]
    assert {e.data["reason"] for e in failed} == {FileFailReason.CONNECTION_LOST.value}
    assert _part_files(receiver) == []


@pytest.mark.parametrize("packet", [
    Packet(MessageType.FILE_START, payload=b"not json"),
    Packet(MessageType.FILE_START, payload=b'{"transfer_id": "one"}'),
    Packet(MessageType.FILE_CHUNK, payload=b"abc"),
    Packet(MessageType.FILE_END, payload=b"{}"),
    make_file_chunk(99, 0, b"unknown transfer"),
    make_file_end(99),
    make_ping(),
])
def test_bad_or_unexpected_packets_do_not_raise(
        events: queue.Queue[Event], receiver: FileReceiver, packet: Packet) -> None:
    receiver.handle_packet(packet)
    assert _drain(events) == []
