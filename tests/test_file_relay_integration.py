"""File transfer through the real server (T-14): 1 MB file, TCP and reliable UDP at 10 % loss.

OWNER: Meryem
Scenario T-14 (README 13.2): the file must arrive with a matching checksum. TCP ignores the
simulated loss (it is handled by the operating system), so the TCP case is the control.
The UDP case is slow (every lost packet waits for a timeout), so it is marked `slow`.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from benchmarks.harness import Cluster, wait_for_event
from socketlink.common.constants import TransportMode
from socketlink.common.events import EventType

pytestmark = pytest.mark.integration

FILE_SIZE = 1024 * 1024  # 1 MB
LOSS = 0.1  # simulated loss on UDP; TCP ignores it
TIMEOUT = 300.0


@pytest.mark.parametrize(
    "mode",
    [
        TransportMode.TCP,
        pytest.param(TransportMode.UDP, marks=[pytest.mark.slow, pytest.mark.timeout(900)]),
    ],
    ids=["tcp", "udp"],
)
def test_one_megabyte_arrives_with_matching_checksum(mode: TransportMode, tmp_path: Path) -> None:
    payload = os.urandom(FILE_SIZE)
    source = tmp_path / "payload.bin"
    source.write_bytes(payload)
    expected = hashlib.sha256(payload).hexdigest()

    downloads = tmp_path / "downloads"
    with Cluster(mode, loss_rate=LOSS) as cluster:
        alice = cluster.add_client("alice")
        bob = cluster.add_client("bob", download_dir=str(downloads))

        transfer_id = alice.client.send_file(str(source), to="bob")
        done = wait_for_event(
            bob.events,
            EventType.FILE_COMPLETED,
            timeout=TIMEOUT,
            predicate=lambda e: e.data["transfer_id"] == transfer_id,
        )

    received = Path(done.data["path"]).read_bytes()
    assert hashlib.sha256(received).hexdigest() == expected
    assert len(received) == FILE_SIZE
