"""Tests for the enums in common/constants.py that act as shared vocabularies.

OWNER: Sude
"""

from __future__ import annotations

import pytest

from socketlink.common.constants import (
    ByeReason,
    ClientErrorCode,
    DisconnectReason,
    ErrorCode,
)


def test_disconnect_reason_values_are_the_documented_set() -> None:
    assert {r.value for r in DisconnectReason} == {
        "user", "server_shutdown", "kicked_by_admin", "timeout",
        "connection_lost", "rejected", "connect_failed", "internal_error",
    }


@pytest.mark.parametrize("bye", list(ByeReason))
def test_from_bye_maps_every_bye_reason(bye: ByeReason) -> None:
    assert isinstance(DisconnectReason.from_bye(bye.value), DisconnectReason)
    assert DisconnectReason.from_bye(bye) is DisconnectReason.from_bye(bye.value)


def test_from_bye_specific_mappings() -> None:
    assert DisconnectReason.from_bye("client_quit") is DisconnectReason.USER
    assert DisconnectReason.from_bye("server_shutdown") is DisconnectReason.SERVER_SHUTDOWN
    assert DisconnectReason.from_bye("kicked_by_admin") is DisconnectReason.KICKED_BY_ADMIN
    assert DisconnectReason.from_bye("timeout") is DisconnectReason.TIMEOUT


@pytest.mark.parametrize("unknown", ["", "whatever", "KICKED_BY_ADMIN"])
def test_from_bye_unknown_reason_means_server_ended_the_session(unknown: str) -> None:
    assert DisconnectReason.from_bye(unknown) is DisconnectReason.SERVER_SHUTDOWN


def test_enum_members_compare_equal_to_their_string_values() -> None:
    assert DisconnectReason.USER == "user"
    assert ByeReason.TIMEOUT == "timeout"


def test_all_vocabulary_enums_use_unique_values() -> None:
    for enum in (DisconnectReason, ByeReason, ClientErrorCode, ErrorCode):
        values = [m.value for m in enum]
        assert len(values) == len(set(values)), enum.__name__
