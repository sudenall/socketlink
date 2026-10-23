"""Fault combination: a file transfer over lossy, slow reliable UDP loses its connection (T-16).

OWNER: Meryem
Scenario T-16 (README 13.2): 20 % loss and 200 ms delay; the connection of the sender
drops in the middle of a transfer. The transfer must end with FILE_FAILED, the program
must not crash, the sender must reconnect, and a new transfer must then arrive intact.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from benchmarks.harness import Cluster, wait_for_event
from socketlink.common.constants import FileFailReason, TransportMode
from socketlink.common.events import EventType

pytestmark = pytest.mark.integration

LOSS = 0.2
DELAY_MS = 200
FILE_SIZE = 64 * 1024  # small enough to send again after the reconnect
EVENT_TIMEOUT = 60.0
RECONNECT_TIMEOUT = 30.0  # RECONNECT_DELAYS add up to 15 s


@pytest.mark.slow
@pytest.mark.timeout(600)
def test_connection_drop_during_transfer_then_recovery(tmp_path: Path) -> None:
    payload = os.urandom(FILE_SIZE)
    first = tmp_path / "first.bin"
    first.write_bytes(payload)
    second = tmp_path / "second.bin"
    second.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()
    downloads = tmp_path / "downloads"

    with Cluster(TransportMode.UDP, loss_rate=LOSS, delay_ms=DELAY_MS) as cluster:
        alice = cluster.add_client("alice", auto_reconnect=True)
        bob = cluster.add_client("bob", download_dir=str(downloads))

        broken_id = alice.client.send_file(str(first), to="bob")
        wait_for_event(
            alice.events,
            EventType.FILE_PROGRESS,
            timeout=EVENT_TIMEOUT,
            predicate=lambda e: e.data["transfer_id"] == broken_id and e.data["done_bytes"] > 0,
        )
        alice.client._close_transport()  # the connection drops in the middle of the transfer

        failed = wait_for_event(
            alice.events,
            EventType.FILE_FAILED,
            timeout=EVENT_TIMEOUT,
            predicate=lambda e: e.data["transfer_id"] == broken_id,
        )
        assert failed.data["direction"] == "upload"
        assert failed.data["reason"] == FileFailReason.SEND_ERROR.value

        wait_for_event(alice.events, EventType.CONNECTED, timeout=RECONNECT_TIMEOUT)

        new_id = alice.client.send_file(str(second), to="bob")
        done = wait_for_event(
            bob.events,
            EventType.FILE_COMPLETED,
            timeout=EVENT_TIMEOUT,
            predicate=lambda e: e.data["transfer_id"] == new_id,
        )

    received = Path(done.data["path"]).read_bytes()
    assert hashlib.sha256(received).hexdigest() == expected
    assert len(received) == FILE_SIZE
