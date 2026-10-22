"""File transfer on top of any Transport (FILE_START -> FILE_CHUNK* -> FILE_END).

OWNER: Tina
SPEC:  docs/PROTOCOL.md section 5.4
USES:  common/protocol.py (make_file_*, parse_file_chunk), common/events.py
USED BY: client/client.py (Hamit) -- FileSender in send_file(), FileReceiver for incoming FILE_*
The server only RELAYS FILE_* packets to the `to` user; it never stores files.

Receiver saves to <download_dir>/<own_username>/<filename>. If the name exists,
append " (1)", " (2)" ... Never trust the filename from the network: only the last
path component is kept (path traversal protection).

Chunks are written to a hidden ".part" file while they arrive, so memory use stays at
one chunk per transfer. The real file appears only after the chunk count and CRC32 match.

`reason` of FILE_FAILED is always a FileFailReason value (common/constants.py):
    upload:   INVALID_FILE, READ_ERROR, SEND_ERROR, CANCELLED
    download: FILE_TOO_LARGE, BAD_PACKET, BAD_CHUNK, TRANSFER_ID_CONFLICT,
              MISSING_CHUNKS, CHECKSUM_MISMATCH, WRITE_ERROR, CONNECTION_LOST
"""

from __future__ import annotations

import math
import os
import tempfile
import threading
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any, BinaryIO

from socketlink.common.constants import (
    FILE_CHUNK_SIZE,
    MAX_FILE_SIZE,
    FileFailReason,
    MessageType,
)
from socketlink.common.events import Event, EventBus, EventType
from socketlink.common.exceptions import (
    FileTransferError,
    MalformedPacketError,
    SocketLinkError,
    ValidationError,
)
from socketlink.common.logger import get_logger
from socketlink.common.protocol import (
    Packet,
    make_file_chunk,
    make_file_end,
    make_file_start,
    parse_file_chunk,
)

log = get_logger(__name__)

SendFunction = Callable[[Packet], None]

# README asks for at most ~10 FILE_PROGRESS events per second.
# TODO(Sude): move to constants.py as FILE_PROGRESS_INTERVAL if approved.
_PROGRESS_INTERVAL = 0.1


class _ProgressThrottle:
    """Says when the next FILE_PROGRESS is allowed (at most one per _PROGRESS_INTERVAL)."""

    def __init__(self) -> None:
        self._last = 0.0

    def is_due(self) -> bool:
        now = time.monotonic()
        if now - self._last < _PROGRESS_INTERVAL:
            return False
        self._last = now
        return True


class FileSender:
    """Reads a file and sends it in FILE_CHUNK_SIZE pieces. Run `send()` in a worker thread."""

    def __init__(self, path: str, transfer_id: int, send: SendFunction,
                 event_bus: EventBus, to: str | None = None) -> None:
        self.path = path
        self.transfer_id = transfer_id
        self._send = send
        self.event_bus = event_bus
        self.to = to
        self._cancel_event = threading.Event()

    def validate(self) -> int:
        """Check the transfer can start and return the file size in bytes.

        Call it before starting the worker thread so the GUI gets the error at once.
        Raises ValidationError if `to` is empty, the path is not a file or the file is
        larger than MAX_FILE_SIZE.
        """
        if not self.to:
            raise ValidationError("A file needs a recipient; it cannot be sent to everyone.")
        file_path = Path(self.path)
        if not file_path.is_file():
            raise ValidationError(f"'{self.path}' is not a file.")
        size = file_path.stat().st_size
        if size > MAX_FILE_SIZE:
            raise ValidationError(
                f"'{file_path.name}' is {size} bytes; the limit is {MAX_FILE_SIZE}."
            )
        return size

    def send(self) -> None:
        """Validate size <= MAX_FILE_SIZE, send FILE_START (with CRC32 of the whole file),
        all chunks, FILE_END. Publish FILE_PROGRESS (max ~10 per second) and
        FILE_COMPLETED / FILE_FAILED (direction='upload').

        Never raises: every problem ends as a FILE_FAILED event.
        """
        try:
            size = self.validate()
        except (ValidationError, OSError) as exc:
            log.warning("Transfer %d not started: %s", self.transfer_id, exc)
            self._publish_failed(FileFailReason.INVALID_FILE.value)
            return

        try:
            checksum = _file_crc32(self.path)
        except OSError as exc:
            log.warning("Transfer %d: cannot read %s: %s", self.transfer_id, self.path, exc)
            self._publish_failed(FileFailReason.READ_ERROR.value)
            return

        total_chunks = math.ceil(size / FILE_CHUNK_SIZE)
        try:
            self._send(make_file_start(self.transfer_id, Path(self.path).name, size,
                                       total_chunks, checksum, to=self.to))
            if not self._send_chunks(size, total_chunks):
                return
            self._send(make_file_end(self.transfer_id))
        except (SocketLinkError, OSError) as exc:
            log.warning("Transfer %d failed while sending: %s", self.transfer_id, exc)
            self._publish_failed(FileFailReason.SEND_ERROR.value)
            return

        log.info("Transfer %d: sent %s (%d bytes) to %s",
                 self.transfer_id, self.path, size, self.to)
        self._publish(EventType.FILE_COMPLETED, {"path": self.path})

    def cancel(self) -> None:
        """Stop sending after the current chunk. Safe to call from any thread, more than once.

        The receiver gets an early FILE_END, so it drops the transfer (missing_chunks).
        """
        self._cancel_event.set()

    # ---- internals ----------------------------------------------------------
    def _send_chunks(self, size: int, total_chunks: int) -> bool:
        """Send every chunk. Return False if the transfer ended early (cancel / read error)."""
        progress = _ProgressThrottle()
        done_bytes = 0
        try:
            with open(self.path, "rb") as file:
                for chunk_index in range(total_chunks):
                    if self._cancel_event.is_set():
                        log.info("Transfer %d cancelled", self.transfer_id)
                        self._end_early(FileFailReason.CANCELLED.value)
                        return False
                    data = file.read(FILE_CHUNK_SIZE)
                    if not data:
                        raise FileTransferError("The file got shorter while it was sent.")
                    self._send(make_file_chunk(self.transfer_id, chunk_index, data))
                    done_bytes += len(data)
                    if progress.is_due():
                        self._publish_progress(done_bytes, size)
        except (FileTransferError, OSError) as exc:
            log.warning("Transfer %d: cannot read %s: %s", self.transfer_id, self.path, exc)
            self._end_early(FileFailReason.READ_ERROR.value)
            return False
        self._publish_progress(done_bytes, size)
        return True

    def _end_early(self, reason: str) -> None:
        """Send FILE_END before all chunks so the receiver drops its partial file,
        then publish FILE_FAILED(reason)."""
        try:
            self._send(make_file_end(self.transfer_id))
        except (SocketLinkError, OSError) as exc:
            log.debug("Transfer %d: early FILE_END not sent: %s", self.transfer_id, exc)
        self._publish_failed(reason)

    def _publish_progress(self, done_bytes: int, total_bytes: int) -> None:
        self._publish(EventType.FILE_PROGRESS,
                      {"done_bytes": done_bytes, "total_bytes": total_bytes})

    def _publish_failed(self, reason: str) -> None:
        self._publish(EventType.FILE_FAILED, {"reason": reason})

    def _publish(self, event_type: EventType, data: dict[str, Any]) -> None:
        self.event_bus.publish(Event(
            event_type,
            {"transfer_id": self.transfer_id, "direction": "upload", **data},
            source="transfer",
        ))


@dataclass
class _IncomingTransfer:
    """State of one download while its chunks arrive."""

    transfer_id: int
    sender: str
    filename: str
    size: int
    total_chunks: int
    checksum: int
    part_path: Path
    part_file: BinaryIO
    next_chunk: int = 0
    done_bytes: int = 0
    crc: int = 0
    progress: _ProgressThrottle = field(default_factory=_ProgressThrottle)


class FileReceiver:
    """Collects chunks of incoming transfers. One instance per client."""

    def __init__(self, download_dir: str, username: str, event_bus: EventBus) -> None:
        self.download_dir = download_dir
        self.username = username
        self.event_bus = event_bus
        self._transfers: dict[int, _IncomingTransfer] = {}
        self._lock = threading.Lock()

    @property
    def target_dir(self) -> Path:
        """Folder that receives this user's downloads: <download_dir>/<username>."""
        return Path(self.download_dir) / safe_filename(self.username, "user")

    def handle_packet(self, packet: Packet) -> None:
        """Accept FILE_START / FILE_CHUNK / FILE_END. On FILE_END verify chunk count and
        CRC32, write the file, publish FILE_COMPLETED or FILE_FAILED (direction='download').

        Never raises: a bad packet only fails its own transfer, the connection stays open.
        """
        with self._lock:
            try:
                if packet.type == MessageType.FILE_START:
                    self._handle_start(packet)
                elif packet.type == MessageType.FILE_CHUNK:
                    self._handle_chunk(packet)
                elif packet.type == MessageType.FILE_END:
                    self._handle_end(packet)
                else:
                    log.debug("FileReceiver ignores %s", packet.type.name)
            except MalformedPacketError as exc:
                log.warning("Ignoring malformed %s: %s", packet.type.name, exc)

    def abort_all(self, reason: str = FileFailReason.CONNECTION_LOST.value) -> None:
        """Drop every unfinished download (e.g. the connection was lost) and publish
        FILE_FAILED for each one. Safe to call more than once."""
        with self._lock:
            for transfer in list(self._transfers.values()):
                self._fail(transfer, reason)

    # ---- internals ----------------------------------------------------------
    def _handle_start(self, packet: Packet) -> None:
        fields = packet.json_payload()
        transfer_id = _int_field(fields, "transfer_id")
        try:
            size = _int_field(fields, "size")
            total_chunks = _int_field(fields, "total_chunks")
            checksum = _int_field(fields, "checksum")
            sender = str(fields.get("from") or "")
            filename = str(fields.get("filename") or "")
        except MalformedPacketError as exc:
            log.warning("Transfer %d: bad FILE_START: %s", transfer_id, exc)
            self._publish_failed(transfer_id, FileFailReason.BAD_PACKET.value)
            return

        # FILE_CHUNK carries no sender, so two senders using the same transfer_id at
        # the same time cannot be told apart: drop both instead of mixing their data.
        old = self._transfers.get(transfer_id)
        if old is not None:
            log.warning("Transfer %d from %s collides with one from %s",
                        transfer_id, sender, old.sender)
            self._fail(old, FileFailReason.TRANSFER_ID_CONFLICT.value)
            self._publish_failed(transfer_id, FileFailReason.TRANSFER_ID_CONFLICT.value)
            return

        if size > MAX_FILE_SIZE:
            log.warning("Transfer %d from %s is too large (%d bytes)", transfer_id, sender, size)
            self._publish_failed(transfer_id, FileFailReason.FILE_TOO_LARGE.value)
            return
        if size < 0 or total_chunks != math.ceil(size / FILE_CHUNK_SIZE):
            log.warning("Transfer %d: %d chunks do not fit %d bytes",
                        transfer_id, total_chunks, size)
            self._publish_failed(transfer_id, FileFailReason.BAD_PACKET.value)
            return

        try:
            self.target_dir.mkdir(parents=True, exist_ok=True)
            fd, part_name = tempfile.mkstemp(prefix=".", suffix=".part", dir=self.target_dir)
            part_file = os.fdopen(fd, "wb")
        except OSError as exc:
            log.error("Transfer %d: cannot create a file in %s: %s",
                      transfer_id, self.target_dir, exc)
            self._publish_failed(transfer_id, FileFailReason.WRITE_ERROR.value)
            return

        self._transfers[transfer_id] = _IncomingTransfer(
            transfer_id=transfer_id,
            sender=sender,
            filename=safe_filename(filename, f"file_{transfer_id}"),
            size=size,
            total_chunks=total_chunks,
            checksum=checksum,
            part_path=Path(part_name),
            part_file=part_file,
        )
        log.info("Transfer %d: receiving %r (%d bytes) from %s",
                 transfer_id, filename, size, sender)
        self._publish(EventType.FILE_OFFERED, transfer_id,
                      {"from": sender, "filename": filename, "size": size})

    def _handle_chunk(self, packet: Packet) -> None:
        transfer_id, chunk_index, data = parse_file_chunk(packet)
        transfer = self._transfers.get(transfer_id)
        if transfer is None:
            log.debug("Chunk %d of unknown transfer %d ignored", chunk_index, transfer_id)
            return
        # TCP and reliable UDP both deliver in order, so anything else is an error.
        if (chunk_index != transfer.next_chunk or len(data) > FILE_CHUNK_SIZE
                or transfer.done_bytes + len(data) > transfer.size):
            log.warning("Transfer %d: unexpected chunk %d (expected %d, %d bytes)",
                        transfer_id, chunk_index, transfer.next_chunk, len(data))
            self._fail(transfer, FileFailReason.BAD_CHUNK.value)
            return
        try:
            transfer.part_file.write(data)
        except OSError as exc:
            log.error("Transfer %d: write failed: %s", transfer_id, exc)
            self._fail(transfer, FileFailReason.WRITE_ERROR.value)
            return
        transfer.crc = zlib.crc32(data, transfer.crc)
        transfer.next_chunk += 1
        transfer.done_bytes += len(data)
        if transfer.progress.is_due():
            self._publish_progress(transfer)

    def _handle_end(self, packet: Packet) -> None:
        transfer_id = _int_field(packet.json_payload(), "transfer_id")
        transfer = self._transfers.get(transfer_id)
        if transfer is None:
            log.debug("FILE_END of unknown transfer %d ignored", transfer_id)
            return
        if transfer.next_chunk != transfer.total_chunks or transfer.done_bytes != transfer.size:
            log.warning("Transfer %d: got %d of %d chunks",
                        transfer_id, transfer.next_chunk, transfer.total_chunks)
            self._fail(transfer, FileFailReason.MISSING_CHUNKS.value)
            return
        if transfer.crc != transfer.checksum:
            log.warning("Transfer %d: CRC32 %d != %d",
                        transfer_id, transfer.crc, transfer.checksum)
            self._fail(transfer, FileFailReason.CHECKSUM_MISMATCH.value)
            return
        target: Path | None = None
        try:
            transfer.part_file.close()
            target = _reserve_free_path(self.target_dir, transfer.filename)
            os.replace(transfer.part_path, target)
        except OSError as exc:
            log.error("Transfer %d: cannot save %s: %s", transfer_id, transfer.filename, exc)
            if target is not None:
                target.unlink(missing_ok=True)
            self._fail(transfer, FileFailReason.WRITE_ERROR.value)
            return
        del self._transfers[transfer_id]
        self._publish_progress(transfer)
        log.info("Transfer %d: saved %s", transfer_id, target)
        self._publish(EventType.FILE_COMPLETED, transfer_id, {"path": str(target)})

    def _fail(self, transfer: _IncomingTransfer, reason: str) -> None:
        """Forget the transfer, delete its .part file and publish FILE_FAILED."""
        self._transfers.pop(transfer.transfer_id, None)
        try:
            transfer.part_file.close()
            transfer.part_path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Could not delete %s: %s", transfer.part_path, exc)
        self._publish_failed(transfer.transfer_id, reason)

    def _publish_progress(self, transfer: _IncomingTransfer) -> None:
        self._publish(EventType.FILE_PROGRESS, transfer.transfer_id,
                      {"done_bytes": transfer.done_bytes, "total_bytes": transfer.size})

    def _publish_failed(self, transfer_id: int, reason: str) -> None:
        self._publish(EventType.FILE_FAILED, transfer_id, {"reason": reason})

    def _publish(self, event_type: EventType, transfer_id: int, data: dict[str, Any]) -> None:
        self.event_bus.publish(Event(
            event_type,
            {"transfer_id": transfer_id, "direction": "download", **data},
            source="transfer",
        ))


def safe_filename(name: str, fallback: str) -> str:
    """Return only the last path component of `name`, or `fallback` if nothing usable is left.

    Both '/' and '\\' count as separators on every OS, so '../../evil.txt' and
    '..\\..\\evil.txt' both become 'evil.txt'.
    """
    cleaned = PureWindowsPath(name).name.strip()
    if cleaned in ("", ".", ".."):
        return fallback
    return cleaned


def _file_crc32(path: str) -> int:
    """CRC32 of the whole file, read in FILE_CHUNK_SIZE pieces."""
    crc = 0
    with open(path, "rb") as file:
        while data := file.read(FILE_CHUNK_SIZE):
            crc = zlib.crc32(data, crc)
    return crc


def _int_field(fields: dict[str, Any], key: str) -> int:
    value = fields.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise MalformedPacketError(f"Field '{key}' must be an integer, got {value!r}.")
    return value


def _reserve_free_path(folder: Path, filename: str) -> Path:
    """Create an empty file named `filename`, or 'name (1).ext', 'name (2).ext' ... if taken.

    Creating it with mode 'x' reserves the name, so two downloads never overwrite each other.
    """
    stem, suffix = Path(filename).stem, Path(filename).suffix
    candidate = folder / filename
    number = 0
    while True:
        try:
            with open(candidate, "xb"):
                return candidate
        except FileExistsError:
            number += 1
            candidate = folder / f"{stem} ({number}){suffix}"
