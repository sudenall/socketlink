"""Project-wide constants for SocketLink.

OWNER: Sude
RULE: Never hard-code any of these values in another module. Import them from here.
      Changing a value here requires a PR approved by the owner, because every
      module depends on it.
"""

from __future__ import annotations

from enum import Enum, IntEnum

# --------------------------------------------------------------------------- #
# Application
# --------------------------------------------------------------------------- #
APP_NAME = "SocketLink"
APP_VERSION = "0.1.0"
ENCODING = "utf-8"

# --------------------------------------------------------------------------- #
# Network defaults
# --------------------------------------------------------------------------- #
DEFAULT_HOST = "127.0.0.1"   # localhost; use "0.0.0.0" on the server to accept LAN clients
DEFAULT_PORT = 5050          # NOT 5000: macOS AirPlay uses 5000
MAX_CLIENTS = 50
LISTEN_BACKLOG = 10

# --------------------------------------------------------------------------- #
# Protocol (see docs/PROTOCOL.md)
# --------------------------------------------------------------------------- #
PROTOCOL_MAGIC = b"SL"
PROTOCOL_VERSION = 1
HEADER_FORMAT = "!2sBBBBIIII"  # magic, version, type, flags, reserved, seq, ack, length, checksum
HEADER_SIZE = 22               # struct.calcsize(HEADER_FORMAT)
MAX_PAYLOAD_SIZE = 60_000      # bytes; must stay below the UDP datagram limit (~65 507)
FILE_CHUNK_SIZE = 1024         # bytes of file data per FILE_CHUNK packet
FILE_CHUNK_PREFIX_FORMAT = "!II"  # transfer_id, chunk_index
FILE_CHUNK_PREFIX_SIZE = 8
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

USERNAME_MIN_LENGTH = 3
USERNAME_MAX_LENGTH = 16
USERNAME_PATTERN = r"^[A-Za-z0-9_]{3,16}$"
MAX_CHAT_LENGTH = 2000  # characters
MAX_CONSECUTIVE_MALFORMED = 5  # MALFORMED_PACKETs in a row before the server closes

# --------------------------------------------------------------------------- #
# Timing (seconds unless the name says otherwise)
# --------------------------------------------------------------------------- #
SOCKET_TIMEOUT = 1.0         # recv/accept timeout so threads can check their stop flag
CONNECT_TIMEOUT = 5.0
HEARTBEAT_INTERVAL = 5.0     # client sends PING this often
CONNECTION_TIMEOUT = 15.0    # no traffic for this long -> connection considered dead
RECONNECT_DELAYS = (1.0, 2.0, 4.0, 8.0)  # back-off between reconnect attempts
GUI_POLL_INTERVAL_MS = 50    # GUI reads the event queue this often
STATS_UPDATE_INTERVAL = 1.0  # STATS_UPDATED event period

# --------------------------------------------------------------------------- #
# Reliable UDP (see docs/PROTOCOL.md section 6)
# --------------------------------------------------------------------------- #
RETRANSMIT_TIMEOUT = 0.5     # seconds before an un-ACKed packet is resent
MAX_RETRIES = 8              # after this many resends the connection is declared dead
DEFAULT_WINDOW_SIZE = 4      # Go-Back-N window; 1 == Stop-and-Wait
MAX_WINDOW_SIZE = 32
MAX_SIMULATED_LOSS = 0.5     # GUI slider upper limit (50 %)
MAX_SIMULATED_DELAY_MS = 1000

# --------------------------------------------------------------------------- #
# Paths (relative to the folder the app is started from; all git-ignored)
# --------------------------------------------------------------------------- #
LOG_DIR = "logs"
LOG_FILE = "socketlink.log"
DOWNLOAD_DIR = "downloads"
RESULTS_DIR = "results"


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class MessageType(IntEnum):
    """Value of the `type` byte in the packet header. Never renumber."""

    HELLO = 1
    WELCOME = 2
    CHAT = 3
    ACK = 4
    PING = 5
    PONG = 6
    USER_LIST = 7
    FILE_START = 8
    FILE_CHUNK = 9
    FILE_END = 10
    ERROR = 11
    BYE = 12


class PacketFlag(IntEnum):
    """Bit flags for the `flags` byte. Combine with |."""

    NONE = 0
    ACK_REQUIRED = 1 << 0   # set by the reliable UDP transport
    RETRANSMISSION = 1 << 1  # set on a resent packet (for statistics only)


class ErrorCode(str, Enum):
    """`code` field of an ERROR payload."""

    BAD_CHECKSUM = "BAD_CHECKSUM"
    MALFORMED_PACKET = "MALFORMED_PACKET"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    NOT_AUTHENTICATED = "NOT_AUTHENTICATED"
    INVALID_USERNAME = "INVALID_USERNAME"
    USERNAME_TAKEN = "USERNAME_TAKEN"
    UNKNOWN_USER = "UNKNOWN_USER"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    SERVER_FULL = "SERVER_FULL"
    FILE_REJECTED = "FILE_REJECTED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ClientErrorCode(str, Enum):
    """`code` of an ERROR *event* raised on the client side. Never sent over the wire.

    Server-sent ERROR packets use `ErrorCode`; these cover failures the client detects
    itself, so GUIs can map a code to a friendly message instead of a Python class name.
    """

    CONNECTION_REFUSED = "CONNECTION_REFUSED"  # nobody is listening on host:port
    CONNECT_TIMEOUT = "CONNECT_TIMEOUT"        # no TCP connection or no WELCOME in time
    CONNECTION_LOST = "CONNECTION_LOST"        # reset, EOF or heartbeat timeout
    PROTOCOL_ERROR = "PROTOCOL_ERROR"          # malformed or unexpected packet from the server
    INVALID_STATE = "INVALID_STATE"            # operation not allowed in this ConnectionState


class ByeReason(str, Enum):
    """`reason` field of a BYE payload (docs/PROTOCOL.md section 4)."""

    CLIENT_QUIT = "client_quit"
    SERVER_SHUTDOWN = "server_shutdown"
    KICKED_BY_ADMIN = "kicked_by_admin"
    TIMEOUT = "timeout"


class DisconnectReason(str, Enum):
    """`reason` of DISCONNECTED, CLIENT_LEFT and SERVER_STOPPED events.

    The ONLY allowed values for those events (see docs/ARCHITECTURE.md, "Olay veri
    sozlesmesi"). GUIs map each member to a user-friendly sentence. The detail of why a
    connection failed or was rejected travels in a separate ERROR event.
    """

    USER = "user"                        # the user (or admin on server stop) ended it normally
    SERVER_SHUTDOWN = "server_shutdown"  # the server closed all connections
    KICKED_BY_ADMIN = "kicked_by_admin"  # an admin removed this client
    TIMEOUT = "timeout"                  # no traffic for CONNECTION_TIMEOUT
    CONNECTION_LOST = "connection_lost"  # reset, EOF or I/O error without a BYE
    REJECTED = "rejected"                # the server refused HELLO (reason in the ERROR event)
    CONNECT_FAILED = "connect_failed"    # the connection could not be established
    INTERNAL_ERROR = "internal_error"    # unexpected exception inside SocketLink

    @classmethod
    def from_bye(cls, reason: str) -> DisconnectReason:
        """Translate the `reason` of a received BYE payload.

        An unknown or missing BYE reason means the server ended the session, so it maps
        to SERVER_SHUTDOWN.
        """
        mapping = {
            ByeReason.CLIENT_QUIT.value: cls.USER,
            ByeReason.SERVER_SHUTDOWN.value: cls.SERVER_SHUTDOWN,
            ByeReason.KICKED_BY_ADMIN.value: cls.KICKED_BY_ADMIN,
            ByeReason.TIMEOUT.value: cls.TIMEOUT,
        }
        return mapping.get(str(getattr(reason, "value", reason)), cls.SERVER_SHUTDOWN)


class FileFailReason(str, Enum):
    """`reason` of FILE_FAILED events (both directions). The ONLY allowed values.

    Values come from the list Tina documented in transfer/file_transfer.py.
    """

    # upload (FileSender)
    INVALID_FILE = "invalid_file"          # missing, empty, directory or too large to start
    READ_ERROR = "read_error"              # the local file could not be read
    SEND_ERROR = "send_error"              # the transport failed while sending
    CANCELLED = "cancelled"                # the user cancelled the transfer
    # download (FileReceiver)
    FILE_TOO_LARGE = "file_too_large"      # announced size exceeds MAX_FILE_SIZE
    BAD_PACKET = "bad_packet"              # FILE_* packet with missing/invalid fields
    BAD_CHUNK = "bad_chunk"                # chunk index out of range or wrong size
    TRANSFER_ID_CONFLICT = "transfer_id_conflict"  # same (sender, transfer_id) started twice
    MISSING_CHUNKS = "missing_chunks"      # FILE_END arrived before all chunks
    CHECKSUM_MISMATCH = "checksum_mismatch"  # whole-file CRC32 differs
    WRITE_ERROR = "write_error"            # the file could not be written to disk
    CONNECTION_LOST = "connection_lost"    # the connection died during the transfer


class TransportMode(str, Enum):
    TCP = "tcp"
    UDP = "udp"


class ConnectionState(str, Enum):
    """Client connection states (State pattern, see docs/ARCHITECTURE.md)."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    DISCONNECTING = "disconnecting"


# Allowed state transitions. Any other transition raises InvalidStateError.
STATE_TRANSITIONS: dict[ConnectionState, frozenset[ConnectionState]] = {
    ConnectionState.DISCONNECTED: frozenset({ConnectionState.CONNECTING}),
    ConnectionState.CONNECTING: frozenset(
        {ConnectionState.CONNECTED, ConnectionState.DISCONNECTED}
    ),
    ConnectionState.CONNECTED: frozenset(
        {ConnectionState.DISCONNECTING, ConnectionState.RECONNECTING}
    ),
    ConnectionState.RECONNECTING: frozenset(
        {ConnectionState.CONNECTED, ConnectionState.DISCONNECTED}
    ),
    ConnectionState.DISCONNECTING: frozenset({ConnectionState.DISCONNECTED}),
}
