"""Exception hierarchy for SocketLink.

OWNER: Sude
RULES:
- Raise these instead of bare Exception / ValueError for anything network or protocol related.
- Catch the most specific class you can. Never use a bare `except:`.
- Network threads must never let an exception escape: catch it, log it and publish an
  EventType.ERROR event (see events.py).
"""


class SocketLinkError(Exception):
    """Base class for every SocketLink error."""


# --- Protocol errors (raised by common/protocol.py) ------------------------- #
class ProtocolError(SocketLinkError):
    """The bytes received do not form a valid SocketLink packet."""


class MalformedPacketError(ProtocolError):
    """Wrong magic bytes, wrong length, unknown type or undecodable payload."""


class BadChecksumError(ProtocolError):
    """CRC32 in the header does not match the packet contents."""


class VersionMismatchError(ProtocolError):
    """Peer speaks a different PROTOCOL_VERSION."""


class PayloadTooLargeError(ProtocolError):
    """Payload exceeds MAX_PAYLOAD_SIZE."""


# --- Connection / transport errors ----------------------------------------- #
class TransportError(SocketLinkError):
    """Base class for transport-level problems."""


class ConnectionClosedError(TransportError):
    """The peer closed the connection (recv returned b"" or BYE received)."""


class TransportTimeoutError(TransportError):
    """No data within the allowed time, or MAX_RETRIES exceeded in reliable UDP."""


# --- Application errors ----------------------------------------------------- #
class InvalidStateError(SocketLinkError):
    """Operation not allowed in the current ConnectionState."""


class ValidationError(SocketLinkError):
    """User input (username, IP, port, message text, file) is invalid."""


class FileTransferError(SocketLinkError):
    """File could not be read, sent, received or verified."""
