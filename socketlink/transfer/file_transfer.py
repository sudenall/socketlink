"""File transfer on top of any Transport (FILE_START -> FILE_CHUNK* -> FILE_END).

OWNER: Tina
SPEC:  docs/PROTOCOL.md section 5.4
The server only RELAYS FILE_* packets to the `to` user; it never stores files.

Receiver saves to <download_dir>/<own_username>/<filename>. If the name exists,
append " (1)", " (2)" ... Never trust the filename from the network: use
Path(filename).name to strip any directory parts (path traversal protection).
"""

from __future__ import annotations

from collections.abc import Callable

from socketlink.common.events import EventBus
from socketlink.common.protocol import Packet

SendFunction = Callable[[Packet], None]


class FileSender:
    """Reads a file and sends it in FILE_CHUNK_SIZE pieces. Run `send()` in a worker thread."""

    def __init__(self, path: str, transfer_id: int, send: SendFunction,
                 event_bus: EventBus, to: str | None = None) -> None:
        self.path = path
        self.transfer_id = transfer_id
        self._send = send
        self.event_bus = event_bus
        self.to = to

    def send(self) -> None:
        """Validate size <= MAX_FILE_SIZE, send FILE_START (with CRC32 of the whole file),
        all chunks, FILE_END. Publish FILE_PROGRESS (max ~10 per second) and
        FILE_COMPLETED / FILE_FAILED (direction='upload')."""
        raise NotImplementedError("TODO(Tina)")

    def cancel(self) -> None:
        raise NotImplementedError("TODO(Tina)")


class FileReceiver:
    """Collects chunks of incoming transfers. One instance per client."""

    def __init__(self, download_dir: str, username: str, event_bus: EventBus) -> None:
        self.download_dir = download_dir
        self.username = username
        self.event_bus = event_bus

    def handle_packet(self, packet: Packet) -> None:
        """Accept FILE_START / FILE_CHUNK / FILE_END. On FILE_END verify chunk count and
        CRC32, write the file, publish FILE_COMPLETED or FILE_FAILED (direction='download')."""
        raise NotImplementedError("TODO(Tina)")
